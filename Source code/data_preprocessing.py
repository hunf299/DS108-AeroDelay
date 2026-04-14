import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


AIRPORTS = ("sgn", "han", "dad")
ROUTES = [
    ("sgn", "dad"),
    ("sgn", "han"),
    ("dad", "sgn"),
    ("dad", "han"),
    ("han", "sgn"),
    ("han", "dad"),
]

NA_TOKENS = {"", "nan", "none", "na", "n/a", "null"}
RUNWAY_REGEX = r"^(0[1-9]|[1-3][0-9])[LR]$"

RETURN_THRESHOLD_MINUTES_DEFAULT = 90
RETURN_THRESHOLD_MAX_MINUTES = 120
ROUTE_MATCH_MAX_HOURS = 12.0

DROP_SAME_ORIGIN_CATEGORIES = {"passenger", "unknown", "cargo"}
TERMINAL_NON_PASSENGER_CATEGORIES = {
    "cargo",
    "business jet",
    "military or government",
    "helicopter",
    "general aviation",
    "ground vehicle",
    "non-categorized",
}
MILITARY_SIGNAL_CATEGORIES = {"military or government", "helicopter", "business jet"}

VIETNAMESE_CARRIER_BY_PREFIX = {
    "0V": "VASCO",
    "VN": "Vietnam Airlines",
    "QH": "Bamboo Airways",
    "VU": "Vietravel Airlines",
    "9G": "Sun PhuQuoc Airways",
    "VJ": "VietJet Air",
}

SGN_DOMESTIC_PREFIX_T3 = {"0V", "VN", "QH", "VU", "9G"}

DOMESTIC_IATA_CODES = {
    "SGN",
    "HAN",
    "DAD",
    "PQC",
    "VCA",
    "CXR",
    "HPH",
    "HUI",
    "UIH",
    "VCL",
    "VCS",
    "DLI",
    "DIN",
    "THD",
    "PXU",
    "TBB",
    "VDH",
    "VDO",
    "VKG",
    "VII",
    "BMV",
    "CAH",
    "VCT",
    "VGL",
}

RUNWAY_RULES = {
    "SGN": {
        "arrival": {
            "default": "25R",
            "reverse": "07L",
            "emergency_map": {"25R": "25L", "07L": "07R"},
        },
        "departure": {"default": "25L", "reverse": "07R"},
    },
    "HAN": {
        "arrival": {
            "default": "11L",
            "reverse": "29R",
            "emergency_map": {"11L": "11R", "29R": "29L"},
        },
        "departure": {"default": "11R", "reverse": "29L"},
    },
    "DAD": {
        "arrival": {
            "default": "35L",
            "reverse": "17R",
            "emergency_map": {"35L": "35R", "17R": "17L"},
        },
        "departure": {"default": "35R", "reverse": "17L"},
    },
}

STATUS_PRIORITY = {
    "ARRIVED": 3.0,
    "DEPARTED": 3.0,
    "LANDED": 3.0,
    "BAGS DELIVERED": 2.0,
    "ON TIME": 1.0,
    "SCHEDULED": 0.5,
}


def runway_column(mode: str) -> str:
    return "Arrival_Runway" if mode == "arrival" else "Departure_Runway"


def route_column(mode: str) -> str:
    return "Origin" if mode == "arrival" else "Destination"


def event_datetime_series(df: pd.DataFrame) -> pd.Series:
    if "Actual_DateTime" in df.columns and "Scheduled_DateTime" in df.columns:
        mixed = df["Actual_DateTime"].where(df["Actual_DateTime"].notna(), df["Scheduled_DateTime"])
        return mixed.astype("datetime64[ns]")
    if "Actual_DateTime" in df.columns:
        return df["Actual_DateTime"].astype("datetime64[ns]")
    if "Scheduled_DateTime" in df.columns:
        return df["Scheduled_DateTime"].astype("datetime64[ns]")
    return pd.Series(pd.NaT, index=df.index)


def normalize_na_tokens(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    for col in cleaned.columns:
        if pd.api.types.is_object_dtype(cleaned[col]) or pd.api.types.is_string_dtype(cleaned[col]):
            series = cleaned[col].astype("string").str.strip()
            series = series.mask(series.str.lower().isin(NA_TOKENS))
            cleaned[col] = series
    return cleaned


def remove_header_like_rows(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    suspect = pd.Series(False, index=df.index)
    for col in df.columns:
        col_name = str(col).strip().upper()
        values = df[col].astype("string").fillna("").str.strip().str.upper()
        suspect = suspect | (values == col_name)
    removed = int(suspect.sum())
    if removed:
        df = df.loc[~suspect].copy()
    return df, removed


def ensure_required_columns(df: pd.DataFrame, airport: str, mode: str) -> pd.DataFrame:
    ensured = df.copy()

    if "Scheduled_Time" not in ensured.columns and "Flight_Time" in ensured.columns:
        ensured = ensured.rename(columns={"Flight_Time": "Scheduled_Time"})

    rw_col = runway_column(mode)
    if rw_col not in ensured.columns:
        ensured[rw_col] = pd.NA

    if "Terminal" not in ensured.columns:
        ensured["Terminal"] = pd.NA

    route_col = route_column(mode)
    if route_col not in ensured.columns:
        ensured[route_col] = pd.NA

    if "IATA" not in ensured.columns:
        ensured["IATA"] = pd.NA

    if "Category" not in ensured.columns:
        ensured["Category"] = pd.NA

    if "Airline" not in ensured.columns:
        ensured["Airline"] = pd.NA

    return ensured


def validate_iata_column(df: pd.DataFrame) -> int:
    if "IATA" not in df.columns:
        return 0
    series = df["IATA"].astype("string").str.upper().str.strip()
    series = series.mask(series.str.lower().isin(NA_TOKENS))
    valid_mask = series.isna() | series.str.match(r"^[A-Z]{3}$")
    fixed_count = int((~valid_mask).sum())
    df["IATA"] = series.where(valid_mask, pd.NA)
    return fixed_count


def sanitize_runway_values(df: pd.DataFrame, mode: str) -> int:
    col = runway_column(mode)
    if col not in df.columns:
        return 0
    series = df[col].astype("string").str.upper().str.strip()
    series = series.mask(series.str.lower().isin(NA_TOKENS))
    valid_mask = series.isna() | series.str.match(RUNWAY_REGEX)
    fixed_count = int((~valid_mask).sum())
    df[col] = series.where(valid_mask, pd.NA)
    return fixed_count


def add_datetime_columns_with_rollover(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "Crawl_Date" not in out.columns:
        out["Crawl_Date"] = pd.NA

    if "Scheduled_Time" in out.columns:
        out["Scheduled_DateTime"] = pd.to_datetime(
            out["Crawl_Date"].fillna("") + " " + out["Scheduled_Time"].fillna(""),
            errors="coerce",
        ).astype("datetime64[ns]")
    else:
        out["Scheduled_DateTime"] = pd.NaT

    if "Actual_Time" in out.columns:
        out["Actual_DateTime"] = pd.to_datetime(
            out["Crawl_Date"].fillna("") + " " + out["Actual_Time"].fillna(""),
            errors="coerce",
        ).astype("datetime64[ns]")
    else:
        out["Actual_DateTime"] = pd.NaT

    if "Scheduled_Time" in out.columns and "Actual_Time" in out.columns:
        sched_clock = pd.to_datetime(out["Scheduled_Time"], format="%H:%M", errors="coerce")
        actual_clock = pd.to_datetime(out["Actual_Time"], format="%H:%M", errors="coerce")

        sched_minutes = sched_clock.dt.hour * 60 + sched_clock.dt.minute
        actual_minutes = actual_clock.dt.hour * 60 + actual_clock.dt.minute

        rollover_mask = sched_minutes.notna() & actual_minutes.notna() & ((actual_minutes + 720) < sched_minutes)
        out.loc[rollover_mask & out["Actual_DateTime"].notna(), "Actual_DateTime"] = (
            out.loc[rollover_mask & out["Actual_DateTime"].notna(), "Actual_DateTime"] + pd.Timedelta(days=1)
        )

    return out


def row_quality_score(row: pd.Series, mode: str) -> float:
    score = 0.0
    rw_col = runway_column(mode)
    runway = row.get(rw_col)
    if pd.notna(runway) and bool(pd.Series([str(runway)]).str.match(RUNWAY_REGEX).iloc[0]):
        score += 5.0

    tail_col = "Tail_Number" if "Tail_Number" in row else "Scheduled_Tail"
    if pd.notna(row.get(tail_col)):
        score += 2.0
    if pd.notna(row.get("Aircraft_Type")):
        score += 1.0
    if pd.notna(row.get("Actual_DateTime")):
        score += 0.5

    status_text = str(row.get("Status", "")).strip().upper()
    score += STATUS_PRIORITY.get(status_text, 0.0)
    return score


def deduplicate_flights(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, List[Dict[str, object]], Dict[str, int]]:
    deduped = df.copy()
    audit_rows: List[Dict[str, object]] = []

    exact_removed = int(deduped.duplicated().sum())
    if exact_removed:
        deduped = deduped.drop_duplicates().copy()

    route_col = route_column(mode)
    group_cols = [
        c
        for c in [
            "Crawl_Date",
            "Flight_No",
            "Scheduled_Time",
            "IATA",
            route_col,
            "Tail_Number",
            "Aircraft_Type",
            "Category",
        ]
        if c in deduped.columns
    ]

    if not group_cols:
        stats = {"exact_duplicate_removed": exact_removed, "cluster_duplicate_removed": 0}
        return deduped, audit_rows, stats

    to_drop: List[int] = []
    cluster_removed = 0

    grouped = deduped.groupby(group_cols, dropna=False, sort=False)
    for _, group in grouped:
        if len(group) <= 1:
            continue

        actual_times = group["Actual_DateTime"].dropna().sort_values()
        should_collapse = False
        span_minutes = np.nan

        if len(actual_times) >= 2:
            span_minutes = (actual_times.max() - actual_times.min()).total_seconds() / 60.0
            should_collapse = span_minutes <= 10
        else:
            should_collapse = True

        if not should_collapse:
            continue

        scored = group.copy()
        scored["_score"] = scored.apply(lambda row: row_quality_score(row, mode), axis=1)
        scored["_actual_sort"] = scored["Actual_DateTime"].fillna(pd.Timestamp("1900-01-01"))
        best_idx = scored.sort_values(["_score", "_actual_sort"], ascending=[False, False]).index[0]

        drop_indices = [idx for idx in group.index if idx != best_idx]
        if not drop_indices:
            continue

        for idx in drop_indices:
            to_drop.append(idx)
            cluster_removed += 1
            audit_rows.append(
                {
                    "Airport": airport,
                    "Mode": mode,
                    "Dropped_Index": int(idx),
                    "Kept_Index": int(best_idx),
                    "Flight_No": deduped.at[idx, "Flight_No"] if "Flight_No" in deduped.columns else pd.NA,
                    "Crawl_Date": deduped.at[idx, "Crawl_Date"] if "Crawl_Date" in deduped.columns else pd.NA,
                    "Scheduled_Time": deduped.at[idx, "Scheduled_Time"] if "Scheduled_Time" in deduped.columns else pd.NA,
                    "Actual_Time": deduped.at[idx, "Actual_Time"] if "Actual_Time" in deduped.columns else pd.NA,
                    "Reason": "near_duplicate_cluster",
                    "Cluster_Span_Minutes": span_minutes,
                }
            )

    if to_drop:
        deduped = deduped.drop(index=to_drop).copy()

    stats = {"exact_duplicate_removed": exact_removed, "cluster_duplicate_removed": cluster_removed}
    return deduped, audit_rows, stats


def infer_runway_orientation(
    df: pd.DataFrame,
    airport: str,
    mode: str,
    window_minutes: int = 30,
    min_ratio: float = 0.6,
) -> pd.Series:
    orientation = pd.Series(pd.NA, index=df.index, dtype="string")
    rw_col = runway_column(mode)

    event_time = event_datetime_series(df)
    valid_rows = event_time.notna()
    if not valid_rows.any():
        return orientation

    idx_sorted = event_time.loc[valid_rows].sort_values().index
    times_ns = event_time.loc[idx_sorted].astype("datetime64[ns]").astype("int64").to_numpy()
    runways = df.loc[idx_sorted, rw_col].astype("string").fillna("").str.upper().to_numpy()

    default_rw = RUNWAY_RULES[airport][mode]["default"]
    reverse_rw = RUNWAY_RULES[airport][mode]["reverse"]

    window_ns = int(pd.Timedelta(minutes=window_minutes).value)

    left = 0
    right = 0
    count_default = 0
    count_reverse = 0
    n = len(idx_sorted)

    for center_pos in range(n):
        center_time = times_ns[center_pos]
        lower = center_time - window_ns
        upper = center_time + window_ns

        while left < n and times_ns[left] < lower:
            rw = runways[left]
            if rw == default_rw:
                count_default -= 1
            elif rw == reverse_rw:
                count_reverse -= 1
            left += 1

        while right < n and times_ns[right] <= upper:
            rw = runways[right]
            if rw == default_rw:
                count_default += 1
            elif rw == reverse_rw:
                count_reverse += 1
            right += 1

        total = count_default + count_reverse
        if total <= 0:
            continue

        if count_default >= count_reverse:
            top_label = "default"
            top_count = count_default
        else:
            top_label = "reverse"
            top_count = count_reverse

        if top_count / float(total) >= min_ratio:
            orientation.at[idx_sorted[center_pos]] = top_label

    return orientation


def fill_runway_values(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, Dict[str, int]]:
    out = df.copy()
    rw_col = runway_column(mode)
    stats = {
        "runway_missing_before": int(out[rw_col].isna().sum()),
        "runway_filled_orientation": 0,
        "runway_filled_nearest": 0,
        "runway_filled_default": 0,
        "runway_marked_unknown_dad": 0,
    }

    if airport == "DAD":
        dad_missing = out[rw_col].isna()
        stats["runway_marked_unknown_dad"] = int(dad_missing.sum())
        out.loc[dad_missing, rw_col] = "Unknown"
        out["_Runway_Orientation"] = pd.NA
        return out, stats

    orientation = infer_runway_orientation(out, airport=airport, mode=mode)
    out["_Runway_Orientation"] = orientation

    default_rw = RUNWAY_RULES[airport][mode]["default"]
    reverse_rw = RUNWAY_RULES[airport][mode]["reverse"]

    missing_mask = out[rw_col].isna()
    fill_default = missing_mask & out["_Runway_Orientation"].eq("default")
    fill_reverse = missing_mask & out["_Runway_Orientation"].eq("reverse")

    out.loc[fill_default, rw_col] = default_rw
    out.loc[fill_reverse, rw_col] = reverse_rw
    stats["runway_filled_orientation"] = int(fill_default.sum() + fill_reverse.sum())

    remaining_mask = out[rw_col].isna()
    if remaining_mask.any():
        event_time = event_datetime_series(out)
        order = event_time.sort_values().index
        propagated = out.loc[order, rw_col].ffill().bfill()

        before_remaining = int(remaining_mask.sum())
        out.loc[order, rw_col] = out.loc[order, rw_col].fillna(propagated)
        after_nearest = int(out[rw_col].isna().sum())
        stats["runway_filled_nearest"] = before_remaining - after_nearest

    remaining_mask = out[rw_col].isna()
    if remaining_mask.any():
        stats["runway_filled_default"] = int(remaining_mask.sum())
        out.loc[remaining_mask, rw_col] = default_rw

    return out, stats


def normalize_category_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    if text in NA_TOKENS:
        return ""
    return text


def handle_same_origin_anomalies(
    arrival_df: pd.DataFrame,
    departure_df: pd.DataFrame,
    airport: str,
    return_threshold_minutes: int,
) -> Tuple[pd.DataFrame, List[Dict[str, object]], Dict[str, int]]:
    arr = arrival_df.copy()
    audit_rows: List[Dict[str, object]] = []

    arr["Is_Return_Emergency"] = False
    arr["Is_Same_Origin_Unmatched"] = False
    arr["Same_Origin_Action"] = pd.NA

    dep_event = event_datetime_series(departure_df)
    dep_valid = departure_df.loc[departure_df["Flight_No"].notna() & dep_event.notna(), ["Flight_No"]].copy()
    dep_valid["Event_DateTime"] = dep_event.loc[dep_valid.index]
    dep_valid["Flight_Key"] = dep_valid["Flight_No"].astype("string").str.upper().str.strip()

    dep_times_by_flight: Dict[str, np.ndarray] = {}
    for flight_key, grp in dep_valid.groupby("Flight_Key"):
        dep_times_by_flight[str(flight_key)] = grp["Event_DateTime"].sort_values().to_numpy(dtype="datetime64[ns]")

    arr_event = event_datetime_series(arr)
    same_origin_mask = arr["IATA"].astype("string").str.upper().eq(airport)
    same_origin_indices = arr.loc[same_origin_mask].index.tolist()

    drop_indices: List[int] = []
    matched_count = 0
    unmatched_drop_count = 0
    unmatched_keep_count = 0

    for idx in same_origin_indices:
        flight_no = arr.at[idx, "Flight_No"] if "Flight_No" in arr.columns else pd.NA
        category = normalize_category_value(arr.at[idx, "Category"] if "Category" in arr.columns else pd.NA)
        event_time = arr_event.at[idx]

        flight_key = ""
        if pd.notna(flight_no):
            flight_key = str(flight_no).strip().upper()

        best_gap = np.nan
        is_return = False
        if flight_key and pd.notna(event_time) and flight_key in dep_times_by_flight:
            dep_times = dep_times_by_flight[flight_key]
            pos = np.searchsorted(dep_times, np.datetime64(event_time), side="right") - 1
            if pos >= 0:
                dep_time = pd.Timestamp(dep_times[pos])
                gap_minutes = (event_time - dep_time).total_seconds() / 60.0
                best_gap = gap_minutes
                if 0 <= gap_minutes <= float(return_threshold_minutes):
                    is_return = True

        if is_return:
            arr.at[idx, "Is_Return_Emergency"] = True
            arr.at[idx, "Same_Origin_Action"] = "keep_return_emergency"
            matched_count += 1
            audit_rows.append(
                {
                    "Airport": airport,
                    "Row_Index": int(idx),
                    "Flight_No": flight_no,
                    "Category": category,
                    "Action": "keep_return_emergency",
                    "Gap_Minutes": best_gap,
                }
            )
            continue

        arr.at[idx, "Is_Same_Origin_Unmatched"] = True

        if category in DROP_SAME_ORIGIN_CATEGORIES:
            arr.at[idx, "Same_Origin_Action"] = "drop_unmatched_same_origin"
            drop_indices.append(idx)
            unmatched_drop_count += 1
            audit_rows.append(
                {
                    "Airport": airport,
                    "Row_Index": int(idx),
                    "Flight_No": flight_no,
                    "Category": category,
                    "Action": "drop_unmatched_same_origin",
                    "Gap_Minutes": best_gap,
                }
            )
        else:
            arr.at[idx, "Same_Origin_Action"] = "keep_noncommercial_same_origin"
            unmatched_keep_count += 1

            for col in ["Origin", "IATA", "Airline", "Flight_No", "Terminal"]:
                if col in arr.columns:
                    arr.at[idx, col] = pd.NA

            orientation = arr.at[idx, "_Runway_Orientation"] if "_Runway_Orientation" in arr.columns else pd.NA
            normal_runway = RUNWAY_RULES[airport]["arrival"]["reverse"] if orientation == "reverse" else RUNWAY_RULES[airport]["arrival"]["default"]
            arr.at[idx, "Arrival_Runway"] = normal_runway

            audit_rows.append(
                {
                    "Airport": airport,
                    "Row_Index": int(idx),
                    "Flight_No": flight_no,
                    "Category": category,
                    "Action": "keep_noncommercial_same_origin",
                    "Gap_Minutes": best_gap,
                }
            )

    if drop_indices:
        arr = arr.drop(index=drop_indices).copy()

    stats = {
        "same_origin_rows": len(same_origin_indices),
        "same_origin_return_matched": matched_count,
        "same_origin_dropped": unmatched_drop_count,
        "same_origin_kept_noncommercial": unmatched_keep_count,
    }
    return arr, audit_rows, stats


def apply_emergency_arrival_runway_mapping(arrival_df: pd.DataFrame, airport: str) -> int:
    if "Is_Return_Emergency" not in arrival_df.columns or "Arrival_Runway" not in arrival_df.columns:
        return 0

    emergency_map = RUNWAY_RULES[airport]["arrival"]["emergency_map"]
    changed = 0

    mask = arrival_df["Is_Return_Emergency"] == True  # noqa: E712
    for idx in arrival_df.loc[mask].index:
        current = arrival_df.at[idx, "Arrival_Runway"]

        if pd.isna(current):
            orientation = arrival_df.at[idx, "_Runway_Orientation"] if "_Runway_Orientation" in arrival_df.columns else pd.NA
            current = RUNWAY_RULES[airport]["arrival"]["reverse"] if orientation == "reverse" else RUNWAY_RULES[airport]["arrival"]["default"]

        current_text = str(current).strip().upper()
        mapped = emergency_map.get(current_text, current_text)
        if mapped != current_text:
            changed += 1
        arrival_df.at[idx, "Arrival_Runway"] = mapped

    return changed


def extract_flight_prefix(flight_series: pd.Series) -> pd.Series:
    if flight_series is None:
        return pd.Series(pd.NA)
    return flight_series.astype("string").str.upper().str.strip().str.extract(r"^([0-9A-Z]{2})", expand=False)


def normalize_airline_values(df: pd.DataFrame) -> int:
    if "Airline" not in df.columns:
        return 0

    before = df["Airline"].astype("string").copy()
    prefix = extract_flight_prefix(df.get("Flight_No", pd.Series(pd.NA, index=df.index)))

    korean_mask = df["Airline"].astype("string").str.upper().eq("KOREAN AIRLINES")
    df.loc[korean_mask, "Airline"] = "Korean Air"

    vn_mask = prefix.isin(VIETNAMESE_CARRIER_BY_PREFIX.keys())
    df.loc[vn_mask, "Airline"] = prefix.map(VIETNAMESE_CARRIER_BY_PREFIX)

    airline_series = df["Airline"].astype("string")
    all_caps_mask = airline_series.notna() & (airline_series == airline_series.str.upper())
    df.loc[all_caps_mask, "Airline"] = airline_series.loc[all_caps_mask].str.title()

    # Restore canonical form for VN carriers after title-casing.
    df.loc[vn_mask, "Airline"] = prefix.map(VIETNAMESE_CARRIER_BY_PREFIX)
    df.loc[df["Airline"].astype("string").str.upper().eq("KOREAN AIRLINES"), "Airline"] = "Korean Air"

    after = df["Airline"].astype("string")
    changed = int((before.fillna("") != after.fillna("")).sum())
    return changed


def normalize_category_unknown(df: pd.DataFrame) -> int:
    if "Category" not in df.columns:
        return 0

    category = df["Category"].astype("string").str.strip().str.lower()
    category = category.mask(category.str.lower().isin(NA_TOKENS))
    df["Category"] = category

    tail_col = "Tail_Number"
    if "Tail_Number" not in df.columns and "Scheduled_Tail" in df.columns:
        tail_col = "Scheduled_Tail"
    if "Tail_Number" not in df.columns and "Actual_Tail" in df.columns:
        tail_col = "Actual_Tail"

    key_cols = [c for c in ["Flight_No", "Airline", tail_col, "Aircraft_Type", "IATA"] if c in df.columns]
    if not key_cols:
        return 0

    missing_score = pd.Series(0, index=df.index, dtype="int64")
    for col in key_cols:
        missing_score = missing_score + df[col].isna().astype("int64")

    non_passenger_with_identity = (
        df["Category"].isin(TERMINAL_NON_PASSENGER_CATEGORIES)
        & df.get(tail_col, pd.Series(pd.NA, index=df.index)).notna()
        & df.get("Aircraft_Type", pd.Series(pd.NA, index=df.index)).notna()
    )

    assign_unknown = (missing_score >= 3) & ~non_passenger_with_identity
    changed = int((assign_unknown & df["Category"].ne("unknown")).sum())
    df.loc[assign_unknown, "Category"] = "unknown"
    return changed


def normalize_terminal_values(df: pd.DataFrame, airport: str, mode: str) -> int:
    if "Terminal" not in df.columns:
        return 0

    before = df["Terminal"].astype("string").copy()
    terminal = before.str.strip()
    terminal = terminal.mask(terminal.str.lower().isin(NA_TOKENS))

    route_col = route_column(mode)
    route_missing = df[route_col].isna() if route_col in df.columns else pd.Series(True, index=df.index)

    iata = df["IATA"].astype("string").str.upper() if "IATA" in df.columns else pd.Series(pd.NA, index=df.index)
    same_origin_arrival = pd.Series(False, index=df.index)
    if mode == "arrival":
        same_origin_arrival = iata.eq(airport)

    category = df["Category"].astype("string").str.lower() if "Category" in df.columns else pd.Series(pd.NA, index=df.index)
    non_passenger = category.isin(TERMINAL_NON_PASSENGER_CATEGORIES)

    # Priority 1: route missing or same-origin arrival => N/A.
    terminal = terminal.mask(route_missing | same_origin_arrival, pd.NA)

    # Priority 2: non-passenger rows (except rows already forced to N/A above).
    non_passenger_effective = non_passenger & ~route_missing & ~same_origin_arrival
    terminal = terminal.mask(non_passenger_effective, "0")

    assignable = ~route_missing & ~same_origin_arrival & ~non_passenger_effective
    domestic = iata.isin(DOMESTIC_IATA_CODES)
    international = iata.notna() & ~domestic

    terminal = terminal.mask(assignable & international, "2")

    if airport == "SGN":
        prefix = extract_flight_prefix(df.get("Flight_No", pd.Series(pd.NA, index=df.index)))
        terminal = terminal.mask(assignable & domestic & prefix.eq("VJ"), "1")
        terminal = terminal.mask(assignable & domestic & prefix.isin(SGN_DOMESTIC_PREFIX_T3), "3")
        terminal = terminal.mask(assignable & domestic & terminal.isna(), "3")
    else:
        terminal = terminal.mask(assignable & domestic, "1")

    df["Terminal"] = terminal
    changed = int((before.fillna("") != df["Terminal"].astype("string").fillna("")).sum())
    return changed


def rename_tail_column(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    out = df.copy()
    if "Tail_Number" not in out.columns:
        return out

    if mode == "arrival":
        out = out.rename(columns={"Tail_Number": "Actual_Tail"})
    else:
        out = out.rename(columns={"Tail_Number": "Scheduled_Tail"})
    return out


def build_swap_matches_for_route(
    departure_df: pd.DataFrame,
    arrival_df: pd.DataFrame,
    origin: str,
    dest: str,
    max_gap_hours: float,
) -> pd.DataFrame:
    dep_time = departure_df["Scheduled_DateTime"].where(
        departure_df["Scheduled_DateTime"].notna(), departure_df["Actual_DateTime"]
    )
    arr_time = arrival_df["Scheduled_DateTime"].where(arrival_df["Scheduled_DateTime"].notna(), arrival_df["Actual_DateTime"])

    dep_work = departure_df.loc[departure_df["Flight_No"].notna() & dep_time.notna(), ["Flight_No", "Scheduled_Tail"]].copy()
    arr_work = arrival_df.loc[arrival_df["Flight_No"].notna() & arr_time.notna(), ["Flight_No", "Actual_Tail"]].copy()

    if dep_work.empty or arr_work.empty:
        return pd.DataFrame()

    dep_work["dep_index"] = dep_work.index
    dep_work["dep_time"] = dep_time.loc[dep_work.index]
    dep_work["Flight_Key"] = dep_work["Flight_No"].astype("string").str.upper().str.strip()

    arr_work["arr_index"] = arr_work.index
    arr_work["arr_time"] = arr_time.loc[arr_work.index]
    arr_work["Flight_Key"] = arr_work["Flight_No"].astype("string").str.upper().str.strip()

    merged = dep_work.merge(arr_work, on="Flight_Key", suffixes=("_dep", "_arr"), how="inner")
    if merged.empty:
        return pd.DataFrame()

    merged["gap_hours"] = (merged["arr_time"] - merged["dep_time"]).dt.total_seconds() / 3600.0
    merged = merged[(merged["gap_hours"] > 0) & (merged["gap_hours"] <= max_gap_hours)].copy()

    if merged.empty:
        return pd.DataFrame()

    nearest = merged.sort_values(["dep_index", "gap_hours"]).groupby("dep_index", as_index=False).first()
    nearest["Route"] = f"{origin.upper()}->{dest.upper()}"
    return nearest


def add_aircraft_swap_flags(
    departures: Dict[str, pd.DataFrame],
    arrivals: Dict[str, pd.DataFrame],
    routes: List[Tuple[str, str]],
    max_gap_hours: float,
) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, int]]:
    swap_audit_rows: List[Dict[str, object]] = []
    per_route_counts: Dict[str, int] = {}

    for airport, dep_df in departures.items():
        dep_df["Matched_Actual_Tail"] = pd.NA
        dep_df["Swap_Match_Gap_Minutes"] = pd.NA
        dep_df["Is_Aircraft_Swapped"] = False

    for origin, dest in routes:
        dep_df = departures[origin]
        arr_df = arrivals[dest]

        route_matches = build_swap_matches_for_route(
            dep_df,
            arr_df,
            origin=origin,
            dest=dest,
            max_gap_hours=max_gap_hours,
        )

        route_label = f"{origin}->{dest}"
        if route_matches.empty:
            per_route_counts[route_label] = 0
            continue

        swapped_count = 0
        for _, row in route_matches.iterrows():
            dep_index = int(row["dep_index"])
            scheduled_tail = dep_df.at[dep_index, "Scheduled_Tail"] if "Scheduled_Tail" in dep_df.columns else pd.NA
            matched_actual_tail = row["Actual_Tail"]

            dep_df.at[dep_index, "Matched_Actual_Tail"] = matched_actual_tail
            dep_df.at[dep_index, "Swap_Match_Gap_Minutes"] = round(float(row["gap_hours"]) * 60.0, 2)

            is_swapped = False
            if pd.notna(scheduled_tail) and pd.notna(matched_actual_tail):
                is_swapped = str(scheduled_tail).strip().upper() != str(matched_actual_tail).strip().upper()

            dep_df.at[dep_index, "Is_Aircraft_Swapped"] = bool(is_swapped)
            if is_swapped:
                swapped_count += 1

            swap_audit_rows.append(
                {
                    "Route": row["Route"],
                    "Dep_Index": dep_index,
                    "Arr_Index": int(row["arr_index"]),
                    "Flight_No_Dep": row["Flight_No_dep"],
                    "Flight_No_Arr": row["Flight_No_arr"],
                    "Scheduled_Tail": scheduled_tail,
                    "Actual_Tail": matched_actual_tail,
                    "Gap_Hours": round(float(row["gap_hours"]), 4),
                    "Is_Aircraft_Swapped": bool(is_swapped),
                }
            )

        departures[origin] = dep_df
        per_route_counts[route_label] = swapped_count

    for airport, dep_df in departures.items():
        dep_df["Is_Aircraft_Swapped"] = dep_df["Is_Aircraft_Swapped"].fillna(False).astype(bool)
        departures[airport] = dep_df

    audit_df = pd.DataFrame(swap_audit_rows)
    counts = {
        "swap_matched_rows": int(len(audit_df)),
        "swap_true_rows": int(audit_df["Is_Aircraft_Swapped"].sum()) if not audit_df.empty else 0,
    }
    return departures, audit_df, {**counts, **{f"swap_true_{k}": v for k, v in per_route_counts.items()}}


def compute_window_counts(target_time: pd.Series, event_ns: np.ndarray, window_minutes: int) -> pd.Series:
    counts = pd.Series(0, index=target_time.index, dtype="int64")
    if event_ns.size == 0:
        return counts

    valid = target_time.notna()
    if not valid.any():
        return counts

    target_ns = target_time.loc[valid].astype("datetime64[ns]").astype("int64").to_numpy()
    window_ns = int(window_minutes * 60 * 1_000_000_000)

    left = np.searchsorted(event_ns, target_ns - window_ns, side="left")
    right = np.searchsorted(event_ns, target_ns, side="right")
    counts.loc[valid] = (right - left).astype("int64")
    return counts


def build_military_events(arrivals: Dict[str, pd.DataFrame], departures: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    records: List[Dict[str, object]] = []

    for mode, datasets in [("arrival", arrivals), ("departure", departures)]:
        rw_col = runway_column(mode)
        for airport, df in datasets.items():
            if "Category" not in df.columns:
                continue

            category = df["Category"].astype("string").str.lower()
            event_time = event_datetime_series(df)
            signal_mask = category.isin(MILITARY_SIGNAL_CATEGORIES) & event_time.notna()
            if not signal_mask.any():
                continue

            subset = df.loc[signal_mask].copy()
            subset["Event_DateTime"] = event_time.loc[signal_mask]
            subset["Airport"] = airport.upper()
            subset["Mode"] = mode

            cols = [
                "Airport",
                "Mode",
                "Event_DateTime",
                "Flight_No",
                "Category",
                rw_col,
            ]
            cols = [c for c in cols if c in subset.columns]
            records.extend(subset[cols].to_dict("records"))

    events = pd.DataFrame(records)
    if not events.empty:
        events = events.sort_values(["Airport", "Event_DateTime"]).reset_index(drop=True)
    return events


def build_event_time_index(events_df: pd.DataFrame) -> Dict[str, np.ndarray]:
    index: Dict[str, np.ndarray] = {}
    if events_df.empty:
        return index

    grouped = events_df.groupby("Airport")
    for airport, grp in grouped:
        if "Event_DateTime" not in grp.columns:
            index[str(airport)] = np.array([], dtype="int64")
            continue
        event_ns = grp["Event_DateTime"].astype("datetime64[ns]").astype("int64").to_numpy()
        index[str(airport)] = np.sort(event_ns)
    return index


def add_military_features(df: pd.DataFrame, airport: str, event_index: Dict[str, np.ndarray]) -> pd.DataFrame:
    out = df.copy()
    event_time = event_datetime_series(out)
    event_ns = event_index.get(airport, np.array([], dtype="int64"))

    count_1h = compute_window_counts(event_time, event_ns, window_minutes=60)
    count_3h = compute_window_counts(event_time, event_ns, window_minutes=180)

    out["Military_Count_1h"] = count_1h.astype("int64")
    out["Military_Count_3h"] = count_3h.astype("int64")
    out["Is_Military_Active"] = out["Military_Count_1h"] > 0
    return out


def finalize_dataframe_for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    helper_cols = ["_Runway_Orientation"]
    drop_cols = [c for c in helper_cols if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)

    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            out[col] = out[col].fillna("N/A")
        elif pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].astype("string").fillna("N/A")

    return out


def normalize_file_common(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, Dict[str, int]]:
    stats: Dict[str, int] = {}

    df = normalize_na_tokens(df)
    df, header_removed = remove_header_like_rows(df)
    stats["header_rows_removed"] = header_removed

    df = ensure_required_columns(df, airport=airport, mode=mode)
    stats["invalid_iata_fixed"] = validate_iata_column(df)
    stats["invalid_runway_fixed"] = sanitize_runway_values(df, mode=mode)

    df = add_datetime_columns_with_rollover(df)
    return df, stats


def write_audit_csv(path: Path, records: List[Dict[str, object]]) -> None:
    if records:
        pd.DataFrame(records).to_csv(path, index=False)
    else:
        pd.DataFrame().to_csv(path, index=False)


def run_pipeline(project_root: Path, return_threshold_minutes: int) -> None:
    if return_threshold_minutes <= 0:
        raise ValueError("return_threshold_minutes must be positive")

    if return_threshold_minutes > RETURN_THRESHOLD_MAX_MINUTES:
        print(
            f"[WARN] Return threshold {return_threshold_minutes} > {RETURN_THRESHOLD_MAX_MINUTES}. "
            f"Keeping provided value, but recommended range is <= {RETURN_THRESHOLD_MAX_MINUTES}."
        )

    bronze_dir = project_root / "Data crawl" / "Bronze_layer"
    arrival_dir = bronze_dir / "Arrival"
    departure_dir = bronze_dir / "Departure"

    silver_dir = project_root / "Data crawl" / "Silver_layer"
    silver_arrival_dir = silver_dir / "Arrival"
    silver_departure_dir = silver_dir / "Departure"
    silver_audit_dir = silver_dir / "Audit"
    silver_feature_dir = silver_dir / "Features"

    silver_arrival_dir.mkdir(parents=True, exist_ok=True)
    silver_departure_dir.mkdir(parents=True, exist_ok=True)
    silver_audit_dir.mkdir(parents=True, exist_ok=True)
    silver_feature_dir.mkdir(parents=True, exist_ok=True)

    arrivals: Dict[str, pd.DataFrame] = {}
    departures: Dict[str, pd.DataFrame] = {}

    summary_rows: List[Dict[str, object]] = []
    duplicate_audit_rows: List[Dict[str, object]] = []
    same_origin_audit_rows: List[Dict[str, object]] = []

    # 1) Load and clean basic schema.
    for airport in AIRPORTS:
        for mode in ("arrival", "departure"):
            src_dir = arrival_dir if mode == "arrival" else departure_dir
            src_name = f"{airport}_flights_{mode}_bronze_layer.csv"
            src_path = src_dir / src_name
            if not src_path.exists():
                raise FileNotFoundError(f"Missing input file: {src_path}")

            df = pd.read_csv(src_path, dtype=str)
            row_before = len(df)

            df, basic_stats = normalize_file_common(df, airport=airport.upper(), mode=mode)
            row_after_basic = len(df)

            deduped, dedup_audit, dedup_stats = deduplicate_flights(df, airport=airport.upper(), mode=mode)
            duplicate_audit_rows.extend(dedup_audit)

            runway_filled, runway_stats = fill_runway_values(deduped, airport=airport.upper(), mode=mode)

            target = arrivals if mode == "arrival" else departures
            target[airport] = runway_filled

            summary_rows.extend(
                [
                    {"Airport": airport.upper(), "Mode": mode, "Metric": "rows_input", "Value": row_before},
                    {"Airport": airport.upper(), "Mode": mode, "Metric": "rows_after_basic_clean", "Value": row_after_basic},
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "header_rows_removed",
                        "Value": basic_stats.get("header_rows_removed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "invalid_iata_fixed",
                        "Value": basic_stats.get("invalid_iata_fixed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "invalid_runway_fixed",
                        "Value": basic_stats.get("invalid_runway_fixed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "exact_duplicate_removed",
                        "Value": dedup_stats.get("exact_duplicate_removed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "cluster_duplicate_removed",
                        "Value": dedup_stats.get("cluster_duplicate_removed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "runway_missing_before",
                        "Value": runway_stats.get("runway_missing_before", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "runway_filled_orientation",
                        "Value": runway_stats.get("runway_filled_orientation", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "runway_filled_nearest",
                        "Value": runway_stats.get("runway_filled_nearest", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "runway_filled_default",
                        "Value": runway_stats.get("runway_filled_default", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "runway_marked_unknown_dad",
                        "Value": runway_stats.get("runway_marked_unknown_dad", 0),
                    },
                ]
            )

    # 2) Same-origin anomaly handling on arrival, using departure of the same airport.
    for airport in AIRPORTS:
        arr_df = arrivals[airport]
        dep_df = departures[airport]

        arr_df, anomaly_audit, anomaly_stats = handle_same_origin_anomalies(
            arr_df,
            dep_df,
            airport=airport.upper(),
            return_threshold_minutes=return_threshold_minutes,
        )
        same_origin_audit_rows.extend(anomaly_audit)

        emergency_changed = apply_emergency_arrival_runway_mapping(arr_df, airport=airport.upper())
        arrivals[airport] = arr_df

        summary_rows.extend(
            [
                {
                    "Airport": airport.upper(),
                    "Mode": "arrival",
                    "Metric": "same_origin_rows",
                    "Value": anomaly_stats.get("same_origin_rows", 0),
                },
                {
                    "Airport": airport.upper(),
                    "Mode": "arrival",
                    "Metric": "same_origin_return_matched",
                    "Value": anomaly_stats.get("same_origin_return_matched", 0),
                },
                {
                    "Airport": airport.upper(),
                    "Mode": "arrival",
                    "Metric": "same_origin_dropped",
                    "Value": anomaly_stats.get("same_origin_dropped", 0),
                },
                {
                    "Airport": airport.upper(),
                    "Mode": "arrival",
                    "Metric": "same_origin_kept_noncommercial",
                    "Value": anomaly_stats.get("same_origin_kept_noncommercial", 0),
                },
                {
                    "Airport": airport.upper(),
                    "Mode": "arrival",
                    "Metric": "emergency_runway_remapped",
                    "Value": emergency_changed,
                },
            ]
        )

    # 3) Airline/category/terminal normalization.
    for airport in AIRPORTS:
        for mode, datasets in (("arrival", arrivals), ("departure", departures)):
            df = datasets[airport]

            airline_changed = normalize_airline_values(df)
            category_unknown_assigned = normalize_category_unknown(df)
            terminal_changed = normalize_terminal_values(df, airport=airport.upper(), mode=mode)

            df = rename_tail_column(df, mode=mode)
            datasets[airport] = df

            summary_rows.extend(
                [
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "airline_values_changed",
                        "Value": airline_changed,
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "category_unknown_assigned",
                        "Value": category_unknown_assigned,
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "terminal_values_changed",
                        "Value": terminal_changed,
                    },
                ]
            )

    # 4) Aircraft swap matching and flagging.
    departures, swap_audit_df, swap_stats = add_aircraft_swap_flags(
        departures,
        arrivals,
        routes=ROUTES,
        max_gap_hours=ROUTE_MATCH_MAX_HOURS,
    )

    for metric, value in swap_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "departure", "Metric": metric, "Value": int(value)})

    # 5) Build military events and military context features.
    military_events = build_military_events(arrivals, departures)
    military_event_index = build_event_time_index(military_events)

    for airport in AIRPORTS:
        arrivals[airport] = add_military_features(arrivals[airport], airport=airport.upper(), event_index=military_event_index)
        departures[airport] = add_military_features(departures[airport], airport=airport.upper(), event_index=military_event_index)

    # 6) Export cleaned files.
    commercial_frames: List[pd.DataFrame] = []
    for airport in AIRPORTS:
        arr_clean = finalize_dataframe_for_export(arrivals[airport])
        dep_clean = finalize_dataframe_for_export(departures[airport])

        arr_out = silver_arrival_dir / f"{airport}_flights_arrival_silver_layer.csv"
        dep_out = silver_departure_dir / f"{airport}_flights_departure_silver_layer.csv"

        arr_clean.to_csv(arr_out, index=False)
        dep_clean.to_csv(dep_out, index=False)

        summary_rows.append({"Airport": airport.upper(), "Mode": "arrival", "Metric": "rows_output", "Value": len(arr_clean)})
        summary_rows.append({"Airport": airport.upper(), "Mode": "departure", "Metric": "rows_output", "Value": len(dep_clean)})

        arr_passenger = arr_clean[arr_clean["Category"].astype(str).str.lower() == "passenger"].copy()
        dep_passenger = dep_clean[dep_clean["Category"].astype(str).str.lower() == "passenger"].copy()

        if not arr_passenger.empty:
            arr_passenger["Mode"] = "arrival"
            arr_passenger["Airport"] = airport.upper()
            commercial_frames.append(arr_passenger)

        if not dep_passenger.empty:
            dep_passenger["Mode"] = "departure"
            dep_passenger["Airport"] = airport.upper()
            commercial_frames.append(dep_passenger)

    # 7) Export audits and feature tables.
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(silver_audit_dir / "audit_summary.csv", index=False)

    write_audit_csv(silver_audit_dir / "audit_duplicates.csv", duplicate_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_same_origin_actions.csv", same_origin_audit_rows)

    if swap_audit_df.empty:
        pd.DataFrame().to_csv(silver_audit_dir / "audit_aircraft_swap_matches.csv", index=False)
    else:
        swap_audit_df.to_csv(silver_audit_dir / "audit_aircraft_swap_matches.csv", index=False)

    if military_events.empty:
        pd.DataFrame().to_csv(silver_feature_dir / "military_activity_events.csv", index=False)
    else:
        military_events_export = military_events.copy()
        if "Event_DateTime" in military_events_export.columns:
            military_events_export["Event_DateTime"] = military_events_export["Event_DateTime"].dt.strftime("%Y-%m-%d %H:%M:%S")
        military_events_export = finalize_dataframe_for_export(military_events_export)
        military_events_export.to_csv(silver_feature_dir / "military_activity_events.csv", index=False)

    if commercial_frames:
        commercial_df = pd.concat(commercial_frames, ignore_index=True)
    else:
        commercial_df = pd.DataFrame()
    commercial_df.to_csv(silver_feature_dir / "commercial_flights_with_military_features.csv", index=False)

    print("=" * 72)
    print("Silver preprocessing completed")
    print(f"Project root: {project_root}")
    print(f"Return threshold (minutes): {return_threshold_minutes}")
    print(f"Output arrival dir: {silver_arrival_dir}")
    print(f"Output departure dir: {silver_departure_dir}")
    print(f"Audit dir: {silver_audit_dir}")
    print(f"Feature dir: {silver_feature_dir}")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Silver layer preprocessing for DS108-AeroDelay")
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root path. Default: parent folder of this script.",
    )
    parser.add_argument(
        "--return-threshold-minutes",
        type=int,
        default=RETURN_THRESHOLD_MINUTES_DEFAULT,
        help=f"Threshold for return/emergency matching in minutes (recommended <= {RETURN_THRESHOLD_MAX_MINUTES}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]
    project_root = Path(args.project_root).resolve() if args.project_root else default_root

    run_pipeline(
        project_root=project_root,
        return_threshold_minutes=int(args.return_threshold_minutes),
    )


if __name__ == "__main__":
    main()