import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple

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

RETURN_THRESHOLD_MINUTES_DEFAULT = 150
RETURN_THRESHOLD_MAX_MINUTES = 150
DEFAULT_SILVER_LAYER_NAME = "Silver_layer"
ROUTE_MATCH_MAX_HOURS = 6.0
MISSING_ROUTE_MATCH_MAX_HOURS = 6.0
DROP_DEPARTURES_WITHOUT_ARRIVAL = False
DROP_ARRIVAL_WITHOUT_DEPARTURE_ROUTES: Set[Tuple[str, str]] = set()
DEDUP_NEAR_TIME_WINDOW_MINUTES = 10
DEDUP_CLUSTER_WINDOW_MINUTES = 150
DEPARTURE_ARRIVAL_MATCH_EARLY_TOLERANCE_HOURS = 2.0

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
            "emergency": "25L",
            "emergency_map": {"25R": "25L", "07L": "07R"},
        },
        "departure": {"default": "25L", "reverse": "07R"},
    },
    "HAN": {
        "arrival": {
            "default": "11L",
            "reverse": "29R",
            "emergency": "11R",
            "emergency_map": {"11L": "11R", "29R": "29L"},
        },
        "departure": {"default": "11R", "reverse": "29L"},
    },
    "DAD": {
        "arrival": {
            "default": "35L",
            "reverse": "17R",
            "emergency": "35R",
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
    if "Arrival_Actual_Landing_DateTime" in df.columns:
        return df["Arrival_Actual_Landing_DateTime"].astype("datetime64[ns]")
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

    if mode == "departure" and "Scheduled_Time" not in ensured.columns and "Flight_Time" in ensured.columns:
        ensured = ensured.rename(columns={"Flight_Time": "Scheduled_Time"})

    if mode == "arrival" and "Scheduled_Time" not in ensured.columns:
        ensured["Scheduled_Time"] = pd.NA

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


def parse_datetime_from_clock(crawl_date: pd.Series, clock_series: pd.Series) -> pd.Series:
    date_text = crawl_date.astype("string").str.strip()
    date_text = date_text.mask(date_text.str.lower().isin(NA_TOKENS))

    clock_text = clock_series.astype("string").str.strip()
    clock_text = clock_text.mask(clock_text.str.lower().isin(NA_TOKENS))

    parsed = pd.Series(pd.NaT, index=clock_series.index, dtype="datetime64[ns]")
    valid = date_text.notna() & clock_text.notna()
    if valid.any():
        valid_clock = clock_text.loc[valid]
        has_date = valid_clock.str.match(r"^\d{4}-\d{1,2}-\d{1,2}\b", na=False)

        if has_date.any():
            parsed.loc[valid_clock.loc[has_date].index] = pd.to_datetime(
                valid_clock.loc[has_date],
                errors="coerce",
            )

        clock_only = valid_clock.loc[~has_date]
        if not clock_only.empty:
            combined = date_text.loc[clock_only.index] + " " + clock_only
            parsed.loc[clock_only.index] = pd.to_datetime(combined, errors="coerce")
    return parsed


def parse_datetime_on_crawl_date(crawl_date: pd.Series, clock_series: pd.Series) -> pd.Series:
    date_text = crawl_date.astype("string").str.strip()
    date_text = date_text.mask(date_text.str.lower().isin(NA_TOKENS))

    clock_text = clock_series.astype("string").str.strip()
    clock_text = clock_text.mask(clock_text.str.lower().isin(NA_TOKENS))
    clock_part = clock_text.str.extract(r"(?P<clock>\d{1,2}:\d{2}(?::\d{2})?)", expand=False)

    parsed = pd.Series(pd.NaT, index=clock_series.index, dtype="datetime64[ns]")
    valid = date_text.notna() & clock_part.notna()
    if valid.any():
        combined = date_text.loc[valid] + " " + clock_part.loc[valid]
        parsed.loc[valid] = pd.to_datetime(combined, errors="coerce")
    return parsed


def parse_duration_minutes(duration_series: pd.Series) -> pd.Series:
    text = duration_series.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(NA_TOKENS))
    minutes = pd.Series(pd.NA, index=duration_series.index, dtype="Int64")

    extracted = text.str.extract(r"^(?P<hours>\d{1,2}):(?P<minutes>\d{2})$")
    valid = extracted["hours"].notna() & extracted["minutes"].notna()
    if valid.any():
        total_minutes = extracted.loc[valid, "hours"].astype("int64") * 60 + extracted.loc[valid, "minutes"].astype("int64")
        minutes.loc[valid] = total_minutes
    return minutes


def shift_datetime_near_reference(
    target_dt: pd.Series,
    reference_dt: pd.Series,
    threshold_hours: float = 12.0,
) -> pd.Series:
    adjusted = target_dt.copy()
    valid = target_dt.notna() & reference_dt.notna()
    if not valid.any():
        return adjusted

    valid_idx = valid[valid].index
    delta_hours = (
        (target_dt.loc[valid_idx] - reference_dt.loc[valid_idx]).dt.total_seconds() / 3600.0
    )
    too_ahead = delta_hours > threshold_hours
    too_behind = delta_hours < -threshold_hours

    if too_ahead.any():
        adjusted.loc[valid_idx[too_ahead]] = adjusted.loc[valid_idx[too_ahead]] - pd.Timedelta(days=1)
    if too_behind.any():
        adjusted.loc[valid_idx[too_behind]] = adjusted.loc[valid_idx[too_behind]] + pd.Timedelta(days=1)

    return adjusted


def shift_datetime_forward_if_far_behind(
    target_dt: pd.Series,
    reference_dt: pd.Series,
    threshold_hours: float = 12.0,
) -> pd.Series:
    adjusted = target_dt.copy()
    valid = target_dt.notna() & reference_dt.notna()
    if not valid.any():
        return adjusted

    valid_idx = valid[valid].index
    delta_hours = (
        (target_dt.loc[valid_idx] - reference_dt.loc[valid_idx]).dt.total_seconds() / 3600.0
    )
    too_behind = delta_hours < -threshold_hours
    if too_behind.any():
        adjusted.loc[valid_idx[too_behind]] = adjusted.loc[valid_idx[too_behind]] + pd.Timedelta(days=1)

    return adjusted


def set_crawl_date_from_datetime(df: pd.DataFrame, datetime_series: pd.Series) -> int:
    valid = datetime_series.notna()
    if not valid.any():
        return 0

    current = df["Crawl_Date"].astype("string").str.strip()
    current = current.mask(current.str.lower().isin(NA_TOKENS))
    new_date = datetime_series.dt.strftime("%Y-%m-%d")
    changed = valid & (current != new_date)
    df.loc[valid, "Crawl_Date"] = new_date.loc[valid]
    return int(changed.sum())


def adjust_dad_arrival_crawl_date(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    out = df.copy()
    stats = {"dad_arrival_crawl_date_shifted": 0}

    if "Crawl_Date" not in out.columns or "Scheduled_Time" not in out.columns:
        return out, stats

    crawl_date = out["Crawl_Date"].astype("string").str.strip()
    crawl_date = crawl_date.mask(crawl_date.str.lower().isin(NA_TOKENS))

    scheduled_time = out["Scheduled_Time"].astype("string").str.strip()
    scheduled_time = scheduled_time.mask(scheduled_time.str.lower().isin(NA_TOKENS))

    scheduled_dt = parse_datetime_from_clock(crawl_date, scheduled_time)

    if scheduled_dt.notna().any():
        new_date = scheduled_dt.dt.strftime("%Y-%m-%d")
        changed_mask = scheduled_dt.notna() & crawl_date.notna() & (new_date != crawl_date)
        out.loc[scheduled_dt.notna(), "Crawl_Date"] = new_date
        stats["dad_arrival_crawl_date_shifted"] = int(changed_mask.sum())

    return out, stats


def canonicalize_arrival_time_by_source(df: pd.DataFrame, airport: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    out = df.copy()
    stats: Dict[str, object] = {
        "rows_total_arrival": int(len(out)),
        "rows_actual_landing_parsed": 0,
        "rows_planned_landing_parsed": 0,
        "rows_duration_parsed": 0,
        "rows_duration_parse_failed": 0,
        "rows_actual_landing_missing": 0,
        "mapping_profile_applied": "DAD_SOURCE" if airport == "DAD" else "FR_SOURCE",
    }

    crawl_date = out.get("Crawl_Date", pd.Series(pd.NA, index=out.index, dtype="string"))
    actual_time_raw = out.get("Actual_Time", pd.Series(pd.NA, index=out.index, dtype="string")).astype("string").str.strip()
    scheduled_time_raw = out.get("Scheduled_Time", pd.Series(pd.NA, index=out.index, dtype="string")).astype("string").str.strip()
    flight_time_raw = out.get("Flight_Time", pd.Series(pd.NA, index=out.index, dtype="string")).astype("string").str.strip()

    actual_time_raw = actual_time_raw.mask(actual_time_raw.str.lower().isin(NA_TOKENS))
    scheduled_time_raw = scheduled_time_raw.mask(scheduled_time_raw.str.lower().isin(NA_TOKENS))
    flight_time_raw = flight_time_raw.mask(flight_time_raw.str.lower().isin(NA_TOKENS))

    if airport == "DAD":
        # DAD source: Scheduled_Time = planned landing time, Actual_Time = actual landing time.
        planned_landing_time = scheduled_time_raw.astype("string")
        actual_landing_time = actual_time_raw.astype("string")
        duration_minutes = pd.Series(pd.NA, index=out.index, dtype="Int64")
    else:
        planned_landing_time = pd.Series(pd.NA, index=out.index, dtype="string")
        actual_landing_time = actual_time_raw.astype("string")
        duration_minutes = parse_duration_minutes(flight_time_raw)
        if "Arrival_Flight_Duration_Minutes" in out.columns:
            existing_duration = pd.to_numeric(out["Arrival_Flight_Duration_Minutes"], errors="coerce")
            duration_minutes = duration_minutes.where(duration_minutes.notna(), existing_duration)

        duration_input = flight_time_raw.notna()
        if "Arrival_Flight_Duration_Minutes" in out.columns:
            duration_input = duration_input | out["Arrival_Flight_Duration_Minutes"].notna()
        stats["rows_duration_parsed"] = int(duration_minutes.notna().sum())
        stats["rows_duration_parse_failed"] = int((duration_input & duration_minutes.isna()).sum())

    if airport == "DAD":
        planned_dt = parse_datetime_on_crawl_date(crawl_date, planned_landing_time)
        actual_dt = parse_datetime_on_crawl_date(crawl_date, actual_landing_time)
    else:
        planned_dt = parse_datetime_from_clock(crawl_date, planned_landing_time)
        actual_dt = parse_datetime_from_clock(crawl_date, actual_landing_time)

    iata_series = out.get("IATA", pd.Series(pd.NA, index=out.index, dtype="string")).astype("string").str.upper().str.strip()
    domestic_mask = iata_series.isin(DOMESTIC_IATA_CODES)

    # Arrival rule:
    #   - DAD: Crawl_Date is the planned/scheduled landing date; actual may shift +/-1 day.
    #   - SGN/HAN: Crawl_Date is the actual landing date.
    if airport == "DAD":
        actual_dt = shift_datetime_near_reference(actual_dt, planned_dt)

    out["Arrival_Planned_Landing_Time"] = planned_landing_time.astype("string")
    out["Arrival_Actual_Landing_Time"] = actual_landing_time.astype("string")
    out["Arrival_Flight_Duration_Minutes"] = duration_minutes
    out["Arrival_Planned_Landing_DateTime"] = planned_dt
    out["Arrival_Actual_Landing_DateTime"] = actual_dt

    # Keep raw source columns and route downstream logic to canonical arrival times.
    out["Scheduled_Time"] = planned_landing_time.astype("string")
    out["Scheduled_DateTime"] = planned_dt
    out["Actual_DateTime"] = actual_dt

    if airport == "DAD":
        stats["crawl_date_realigned"] = set_crawl_date_from_datetime(out, planned_dt)
    else:
        stats["crawl_date_realigned"] = set_crawl_date_from_datetime(out, actual_dt)

    stats["rows_actual_landing_parsed"] = int(actual_dt.notna().sum())
    stats["rows_planned_landing_parsed"] = int(planned_dt.notna().sum())
    stats["rows_actual_landing_missing"] = int(actual_dt.isna().sum())
    return out, stats


def add_datetime_columns_with_rollover(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    out = df.copy()

    if "Crawl_Date" not in out.columns:
        out["Crawl_Date"] = pd.NA

    if mode == "arrival":
        return canonicalize_arrival_time_by_source(out, airport=airport)

    parse_departure_datetime = parse_datetime_on_crawl_date if airport == "DAD" else parse_datetime_from_clock

    if "Scheduled_Time" in out.columns:
        out["Scheduled_DateTime"] = parse_departure_datetime(out["Crawl_Date"], out["Scheduled_Time"])
    else:
        out["Scheduled_DateTime"] = pd.NaT

    if "Actual_Time" in out.columns:
        out["Actual_DateTime"] = parse_departure_datetime(out["Crawl_Date"], out["Actual_Time"])
    else:
        out["Actual_DateTime"] = pd.NaT

    # Departure rule:
    #   - DAD: Crawl_Date is the scheduled departure date; actual may shift +/-1 day.
    #   - SGN/HAN: Crawl_Date is the actual departure date; scheduled may shift +/-1 day.
    if airport == "DAD":
        out["Actual_DateTime"] = shift_datetime_near_reference(
            out["Actual_DateTime"],
            out["Scheduled_DateTime"],
        )
        stats = {"crawl_date_realigned": set_crawl_date_from_datetime(out, out["Scheduled_DateTime"])}
    else:
        out["Scheduled_DateTime"] = shift_datetime_near_reference(
            out["Scheduled_DateTime"],
            out["Actual_DateTime"],
        )
        stats = {"crawl_date_realigned": set_crawl_date_from_datetime(out, out["Actual_DateTime"])}

    return out, stats


def collect_time_gap_over_12h_audit(df: pd.DataFrame, airport: str, mode: str) -> List[Dict[str, object]]:
    audit_rows: List[Dict[str, object]] = []

    if "Crawl_Date" not in df.columns:
        return audit_rows

    if mode == "arrival":
        if "Scheduled_Time" not in df.columns or "Actual_Time" not in df.columns:
            return audit_rows
        scheduled_raw = df["Scheduled_Time"].astype("string").str.strip()
        actual_raw = df["Actual_Time"].astype("string").str.strip()
    else:
        if "Scheduled_Time" not in df.columns or "Actual_Time" not in df.columns:
            return audit_rows
        scheduled_raw = df["Scheduled_Time"].astype("string").str.strip()
        actual_raw = df["Actual_Time"].astype("string").str.strip()

    crawl_date = df["Crawl_Date"].astype("string").str.strip()
    crawl_date = crawl_date.mask(crawl_date.str.lower().isin(NA_TOKENS))
    scheduled_raw = scheduled_raw.mask(scheduled_raw.str.lower().isin(NA_TOKENS))
    actual_raw = actual_raw.mask(actual_raw.str.lower().isin(NA_TOKENS))

    scheduled_dt = parse_datetime_from_clock(crawl_date, scheduled_raw)
    actual_dt = parse_datetime_from_clock(crawl_date, actual_raw)

    for idx in df.index:
        sched = scheduled_dt.at[idx]
        actual = actual_dt.at[idx]
        if pd.isna(sched) or pd.isna(actual):
            continue

        candidate_shifts = [-1, 0, 1]
        candidate_gaps: Dict[int, float] = {}
        for shift_days in candidate_shifts:
            shifted_sched = sched + pd.Timedelta(days=shift_days)
            candidate_gaps[shift_days] = abs((actual - shifted_sched).total_seconds() / 3600.0)

        best_shift = min(candidate_gaps, key=candidate_gaps.get)
        best_gap = candidate_gaps[best_shift]
        raw_gap = abs((actual - sched).total_seconds() / 3600.0)

        if best_gap <= 12:
            continue

        audit_rows.append(
            {
                "airport": airport,
                "mode": mode,
                "row_index": int(idx),
                "crawl_date": df.at[idx, "Crawl_Date"] if "Crawl_Date" in df.columns else pd.NA,
                "scheduled_time": df.at[idx, "Scheduled_Time"] if "Scheduled_Time" in df.columns else pd.NA,
                "actual_time": df.at[idx, "Actual_Time"] if "Actual_Time" in df.columns else pd.NA,
                "scheduled_datetime_raw": scheduled_dt.at[idx],
                "actual_datetime_raw": actual_dt.at[idx],
                "gap_hours_abs": round(raw_gap, 4),
                "best_shift_days": best_shift,
                "best_gap_hours_abs": round(best_gap, 4),
            }
        )

    return audit_rows


def cross_correct_arrival_dates(
    departures: Dict[str, pd.DataFrame],
    arrivals: Dict[str, pd.DataFrame],
    routes: List[Tuple[str, str]],
    max_gap_hours: float = 6.0,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    """Correct arrival actual datetimes by cross-matching with corresponding departures.

    When FR24 assigns the wrong crawl date to an arrival (midnight overlap),
    the naive Actual_DateTime can be off by +/- 1 day.  This function looks up
    the matching departure record (same Flight_No + Tail_Number + route) and
    shifts the arrival date so that the departure-arrival gap falls within a
    realistic flight-time window.
    """
    stats = {"arrivals_corrected": 0}

    for origin, dest in routes:
        dep_df = departures.get(origin)
        arr_df = arrivals.get(dest)
        if dep_df is None or arr_df is None or dep_df.empty or arr_df.empty:
            continue

        dep_time = event_datetime_series(dep_df)
        arr_time = event_datetime_series(arr_df)

        # Build departure lookup with flight/route keys (tail intentionally omitted
        # so that cross-correction still works when departure and arrival tails differ).
        dep_valid = dep_df.loc[
            dep_df["Flight_No"].notna() & dep_time.notna() & dep_df["IATA"].notna()
        ].copy()
        if dep_valid.empty:
            continue
        dep_valid["Event_Time"] = dep_time.loc[dep_valid.index]
        dep_valid["Flight_Key"] = dep_valid["Flight_No"].astype("string").str.upper().str.strip()
        dep_valid["Route_Key"] = dep_valid["IATA"].astype("string").str.upper().str.strip()

        # Build arrival working set for this origin only
        arr_valid = arr_df.loc[
            arr_df["Flight_No"].notna() & arr_time.notna() & arr_df["IATA"].notna()
        ].copy()
        if arr_valid.empty:
            continue
        arr_valid["Event_Time"] = arr_time.loc[arr_valid.index]
        arr_valid["Flight_Key"] = arr_valid["Flight_No"].astype("string").str.upper().str.strip()
        arr_valid["Route_Key"] = arr_valid["IATA"].astype("string").str.upper().str.strip()
        arr_valid = arr_valid.loc[arr_valid["Route_Key"] == origin.upper()].copy()
        if arr_valid.empty:
            continue

        merged = arr_valid.merge(
            dep_valid,
            on=["Flight_Key", "Route_Key"],
            how="left",
            suffixes=("_arr", "_dep"),
        )
        if merged.empty:
            continue

        merged["gap_hours"] = (merged["Event_Time_arr"] - merged["Event_Time_dep"]).dt.total_seconds() / 3600.0

        corrections: Dict[int, pd.Timestamp] = {}
        for idx in merged.index.unique():
            subset = merged.loc[[idx]]

            # Already valid?
            naive_ok = subset.loc[(subset["gap_hours"] > 0) & (subset["gap_hours"] <= max_gap_hours)]
            if not naive_ok.empty:
                continue

            # Try +1 day on arrival
            plus1_gap = ((subset["Event_Time_arr"] + pd.Timedelta(days=1)) - subset["Event_Time_dep"]).dt.total_seconds() / 3600.0
            plus1_ok = subset.loc[(plus1_gap > 0) & (plus1_gap <= max_gap_hours)]
            if not plus1_ok.empty:
                corrections[int(idx)] = subset.at[idx, "Event_Time_arr"] + pd.Timedelta(days=1)
                continue

            # Try -1 day on arrival
            minus1_gap = ((subset["Event_Time_arr"] - pd.Timedelta(days=1)) - subset["Event_Time_dep"]).dt.total_seconds() / 3600.0
            minus1_ok = subset.loc[(minus1_gap > 0) & (minus1_gap <= max_gap_hours)]
            if not minus1_ok.empty:
                corrections[int(idx)] = subset.at[idx, "Event_Time_arr"] - pd.Timedelta(days=1)
                continue

        corrected = 0
        for idx, new_time in corrections.items():
            if pd.notna(new_time):
                arr_df.at[idx, "Actual_DateTime"] = new_time
                if "Arrival_Actual_Landing_DateTime" in arr_df.columns:
                    arr_df.at[idx, "Arrival_Actual_Landing_DateTime"] = new_time
                corrected += 1

        stats["arrivals_corrected"] += corrected
        arrivals[dest] = arr_df

    return arrivals, stats


def reconcile_tails_from_arrivals(
    departures: Dict[str, pd.DataFrame],
    arrivals: Dict[str, pd.DataFrame],
    routes: List[Tuple[str, str]],
    max_gap_hours: float = 6.0,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, object]], Dict[str, int]]:
    """Overwrite departure Tail_Number and Aircraft_Type from matched arrivals.

    FR24 sometimes reports different tail numbers (and therefore different
    aircraft types) for the same flight on the departure page vs the arrival
    page.  This function treats the arrival record as the source of truth:
    it matches each departure to its corresponding arrival by
    (Flight_No, Route, time window) and, when the tails differ, overwrites
    the departure tail (and aircraft type) with the arrival values.
    """
    audit_rows: List[Dict[str, object]] = []
    stats = {"dep_tail_overwritten": 0, "dep_ac_overwritten": 0}

    for origin, dest in routes:
        dep_df = departures.get(origin)
        arr_df = arrivals.get(dest)
        if dep_df is None or arr_df is None or dep_df.empty or arr_df.empty:
            continue

        dep_time = event_datetime_series(dep_df)
        arr_time = event_datetime_series(arr_df)

        # Filter arrivals to this origin only (arrival.IATA = origin airport)
        arr_filtered = arr_df.loc[
            arr_df["IATA"].astype("string").str.upper().str.strip() == origin.upper()
        ].copy()

        # Build arrival lookup: flight_key -> list of candidates
        arr_lookup: Dict[str, List[Dict[str, object]]] = {}
        for idx in arr_filtered.index:
            if pd.isna(arr_time.at[idx]) or pd.isna(arr_filtered.at[idx, "Flight_No"]):
                continue
            flight_key = str(arr_filtered.at[idx, "Flight_No"]).strip().upper()
            candidate = {
                "arr_idx": int(idx),
                "arr_time": arr_time.at[idx],
                "tail": str(arr_filtered.at[idx, "Tail_Number"]).strip().upper()
                if pd.notna(arr_filtered.at[idx, "Tail_Number"])
                else "",
                "ac_type": str(arr_filtered.at[idx, "Aircraft_Type"]).strip().upper()
                if pd.notna(arr_filtered.at[idx, "Aircraft_Type"])
                else "",
            }
            arr_lookup.setdefault(flight_key, []).append(candidate)

        if not arr_lookup:
            continue

        # Filter departures to this destination only (departure.IATA = destination airport)
        dep_filtered = dep_df.loc[
            dep_df["IATA"].astype("string").str.upper().str.strip() == dest.upper()
        ].copy()

        overwritten = 0
        ac_overwritten = 0

        for dep_idx in dep_filtered.index:
            if pd.isna(dep_time.at[dep_idx]) or pd.isna(dep_filtered.at[dep_idx, "Flight_No"]):
                continue

            flight_key = str(dep_filtered.at[dep_idx, "Flight_No"]).strip().upper()
            dep_tail = (
                str(dep_filtered.at[dep_idx, "Tail_Number"]).strip().upper()
                if pd.notna(dep_filtered.at[dep_idx, "Tail_Number"])
                else ""
            )
            dep_ac = (
                str(dep_filtered.at[dep_idx, "Aircraft_Type"]).strip().upper()
                if pd.notna(dep_filtered.at[dep_idx, "Aircraft_Type"])
                else ""
            )

            candidates = arr_lookup.get(flight_key, [])
            if not candidates:
                continue

            best: Dict[str, object] | None = None
            best_gap: float | None = None
            for cand in candidates:
                gap = (cand["arr_time"] - dep_time.at[dep_idx]).total_seconds() / 3600.0
                if 0 < gap <= max_gap_hours:
                    if best is None or gap < best_gap:
                        best = cand
                        best_gap = gap

            if best is None:
                continue

            if best["tail"] and best["tail"] != dep_tail:
                dep_df.at[dep_idx, "Tail_Number"] = best["tail"]
                overwritten += 1

                if best["ac_type"] and best["ac_type"] != dep_ac:
                    dep_df.at[dep_idx, "Aircraft_Type"] = best["ac_type"]
                    ac_overwritten += 1

                audit_rows.append(
                    {
                        "Route": f"{origin.upper()}->{dest.upper()}",
                        "Dep_Index": int(dep_idx),
                        "Arr_Index": best["arr_idx"],
                        "Flight_No": flight_key,
                        "Dep_Tail_Before": dep_tail,
                        "Arr_Tail_After": best["tail"],
                        "Dep_AC_Before": dep_ac,
                        "Arr_AC_After": best["ac_type"],
                        "Gap_Hours": round(float(best_gap), 4) if best_gap is not None else None,
                    }
                )

        departures[origin] = dep_df
        stats["dep_tail_overwritten"] += overwritten
        stats["dep_ac_overwritten"] += ac_overwritten

    return departures, audit_rows, stats


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


def compute_return_emergency_mask(
    arrival_df: pd.DataFrame,
    departure_df: pd.DataFrame | None,
    airport: str,
    return_threshold_minutes: int | None,
) -> pd.Series:
    mask = pd.Series(False, index=arrival_df.index)
    if departure_df is None or return_threshold_minutes is None:
        return mask
    if "Flight_No" not in arrival_df.columns or "IATA" not in arrival_df.columns:
        return mask

    dep_event = event_datetime_series(departure_df)
    dep_valid = departure_df.loc[departure_df["Flight_No"].notna() & dep_event.notna(), ["Flight_No"]].copy()
    if dep_valid.empty:
        return mask

    dep_valid["Event_DateTime"] = dep_event.loc[dep_valid.index]
    dep_valid["Flight_Key"] = dep_valid["Flight_No"].astype("string").str.upper().str.strip()

    dep_times_by_flight: Dict[str, np.ndarray] = {}
    for flight_key, grp in dep_valid.groupby("Flight_Key"):
        dep_times_by_flight[str(flight_key)] = grp["Event_DateTime"].sort_values().to_numpy(dtype="datetime64[ns]")

    arr_event = event_datetime_series(arrival_df)
    same_origin_mask = arrival_df["IATA"].astype("string").str.upper().eq(airport)
    for idx in arrival_df.loc[same_origin_mask & arr_event.notna()].index:
        flight_no = arrival_df.at[idx, "Flight_No"]
        if pd.isna(flight_no):
            continue
        flight_key = str(flight_no).strip().upper()
        dep_times = dep_times_by_flight.get(flight_key)
        if dep_times is None or dep_times.size == 0:
            continue
        event_time = arr_event.at[idx]
        pos = np.searchsorted(dep_times, np.datetime64(event_time), side="right") - 1
        if pos < 0:
            continue
        gap_minutes = (pd.Timestamp(event_time) - pd.Timestamp(dep_times[pos])).total_seconds() / 60.0
        if 0 <= gap_minutes <= float(return_threshold_minutes):
            mask.at[idx] = True
    return mask


def compute_departure_return_emergency_link_mask(
    departure_df: pd.DataFrame,
    arrival_df: pd.DataFrame | None,
    airport: str,
    return_threshold_minutes: int | None,
) -> pd.Series:
    mask = pd.Series(False, index=departure_df.index)
    if arrival_df is None or return_threshold_minutes is None:
        return mask
    if "Flight_No" not in departure_df.columns or "Flight_No" not in arrival_df.columns:
        return mask
    if "IATA" not in arrival_df.columns:
        return mask

    dep_event = event_datetime_series(departure_df)
    dep_valid = departure_df.loc[departure_df["Flight_No"].notna() & dep_event.notna(), ["Flight_No"]].copy()
    if dep_valid.empty:
        return mask

    dep_valid["Event_DateTime"] = dep_event.loc[dep_valid.index]
    dep_valid["Flight_Key"] = dep_valid["Flight_No"].astype("string").str.upper().str.strip()

    dep_by_flight: Dict[str, pd.DataFrame] = {}
    for flight_key, grp in dep_valid.groupby("Flight_Key"):
        dep_by_flight[str(flight_key)] = grp.sort_values("Event_DateTime")

    arr_event = event_datetime_series(arrival_df)
    same_origin = arrival_df["IATA"].astype("string").str.upper().eq(airport)
    explicit_return = (
        arrival_df["Is_Return_Emergency"].astype("string").str.lower().eq("true")
        if "Is_Return_Emergency" in arrival_df.columns
        else pd.Series(False, index=arrival_df.index)
    )
    arrival_candidates = same_origin & arr_event.notna()
    if explicit_return.any():
        arrival_candidates = arrival_candidates | explicit_return

    for idx in arrival_df.loc[arrival_candidates].index:
        flight_no = arrival_df.at[idx, "Flight_No"]
        if pd.isna(flight_no):
            continue
        flight_key = str(flight_no).strip().upper()
        dep_group = dep_by_flight.get(flight_key)
        if dep_group is None or dep_group.empty:
            continue

        event_time = pd.Timestamp(arr_event.at[idx])
        lower = event_time - pd.Timedelta(minutes=float(return_threshold_minutes))
        linked = dep_group[
            (dep_group["Event_DateTime"] >= lower)
            & (dep_group["Event_DateTime"] <= event_time)
        ]
        if not linked.empty:
            mask.loc[linked.index] = True

    return mask


def deduplicate_flights(
    df: pd.DataFrame,
    airport: str,
    mode: str,
    departure_df: pd.DataFrame | None = None,
    arrival_df: pd.DataFrame | None = None,
    return_threshold_minutes: int | None = None,
) -> Tuple[pd.DataFrame, List[Dict[str, object]], Dict[str, int]]:
    deduped = df.copy()
    audit_rows: List[Dict[str, object]] = []
    event_time = event_datetime_series(deduped)

    if "Crawl_Date" not in deduped.columns:
        deduped["Crawl_Date"] = pd.NA

    dest_col = "Destination"
    if mode == "arrival":
        dest_col = "_Dedup_Destination"
        deduped[dest_col] = airport.upper()
    elif dest_col not in deduped.columns:
        deduped[dest_col] = pd.NA

    if "Scheduled_DateTime" in deduped.columns:
        scheduled_dt = pd.to_datetime(deduped["Scheduled_DateTime"], errors="coerce")
    elif "Scheduled_Time" in deduped.columns:
        scheduled_dt = parse_datetime_from_clock(deduped["Crawl_Date"], deduped["Scheduled_Time"])
    else:
        scheduled_dt = pd.Series(pd.NaT, index=deduped.index, dtype="datetime64[ns]")

    deduped["_Dedup_Service_Date"] = scheduled_dt.dt.date
    crawl_date = pd.to_datetime(deduped["Crawl_Date"], errors="coerce")
    missing_service_date = deduped["_Dedup_Service_Date"].isna()
    deduped.loc[missing_service_date, "_Dedup_Service_Date"] = crawl_date.loc[missing_service_date].dt.date

    group_cols = ["_Dedup_Service_Date", "Flight_No", "IATA", dest_col]
    group_cols = [c for c in group_cols if c in deduped.columns]

    if not group_cols:
        stats = {
            "exact_duplicate_removed": 0,
            "cluster_duplicate_removed": 0,
            "same_day_60m_duplicate_removed": 0,
            "dual_runway_duplicate_removed": 0,
        }
        return deduped, audit_rows, stats

    return_emergency_mask = pd.Series(False, index=deduped.index)
    if mode == "arrival":
        return_emergency_mask = compute_return_emergency_mask(
            deduped,
            departure_df,
            airport.upper(),
            return_threshold_minutes,
        )
    elif mode == "departure":
        return_emergency_mask = compute_departure_return_emergency_link_mask(
            deduped,
            arrival_df,
            airport.upper(),
            return_threshold_minutes,
        )

    to_drop: Set[int] = set()
    cluster_removed = 0

    grouped = deduped.groupby(group_cols, dropna=False, sort=False)
    for _, group in grouped:
        if len(group) <= 1:
            continue
        if "Flight_No" in group.columns and group["Flight_No"].isna().all():
            continue

        group_event = event_time.loc[group.index].dropna().sort_values()
        if len(group_event) < 2:
            continue

        # 1. Gom nhóm theo NGÀY của actual time
        event_dates = group_event.dt.date
        for date_value, date_events in group_event.groupby(event_dates):
            if len(date_events) <= 1:
                continue

            # 2. LOGIC: Trong cung 1 ngay, phan cum neu cach nhau qua dedup window.
            sub_clusters = (date_events.diff() > pd.Timedelta(minutes=DEDUP_CLUSTER_WINDOW_MINUTES)).cumsum()

            for cluster_id, cluster_events in date_events.groupby(sub_clusters):
                indices = [int(idx) for idx in cluster_events.index]
                if len(indices) <= 1:
                    continue

                if mode == "arrival" and return_emergency_mask.loc[indices].any():
                    gaps = cluster_events.diff().dropna().dt.total_seconds().abs() / 60.0
                    if not gaps.empty and gaps.min() <= DEDUP_NEAR_TIME_WINDOW_MINUTES:
                        continue
                if mode == "departure" and return_emergency_mask.loc[indices].any():
                    continue

                kept_idx = int(cluster_events.idxmax())
                kept_event = event_time.at[kept_idx]

                key_signature = "|".join([
                    f"Service_Date={deduped.at[kept_idx, '_Dedup_Service_Date'] if '_Dedup_Service_Date' in deduped.columns else 'N/A'}",
                    f"Flight_No={deduped.at[kept_idx, 'Flight_No'] if 'Flight_No' in deduped.columns else 'N/A'}",
                    f"IATA={deduped.at[kept_idx, 'IATA'] if 'IATA' in deduped.columns else 'N/A'}",
                    f"Destination={deduped.at[kept_idx, dest_col] if dest_col in deduped.columns else 'N/A'}",
                ])

                for idx in indices:
                    if idx == kept_idx:
                        continue
                    to_drop.add(int(idx))
                    cluster_removed += 1

                    gap_minutes = np.nan
                    dropped_event = event_time.at[idx]
                    if pd.notna(kept_event) and pd.notna(dropped_event):
                        gap_minutes = abs((pd.Timestamp(kept_event) - pd.Timestamp(dropped_event)).total_seconds()) / 60.0

                    audit_rows.append({
                        "airport": airport,
                        "mode": mode,
                        "row_index_dropped": int(idx),
                        "row_index_kept": int(kept_idx),
                        "dedup_reason": f"same_day_{DEDUP_CLUSTER_WINDOW_MINUTES}m_window",
                        "actual_time_gap_minutes": gap_minutes,
                        "key_signature": key_signature,
                    })

    if to_drop:
        deduped = deduped.drop(index=list(sorted(to_drop))).copy()

    helper_dedup_cols = [c for c in ["_Dedup_Destination", "_Dedup_Service_Date"] if c in deduped.columns]
    if helper_dedup_cols:
        deduped = deduped.drop(columns=helper_dedup_cols)

    stats = {
        "exact_duplicate_removed": 0,
        "cluster_duplicate_removed": cluster_removed,
        "same_day_60m_duplicate_removed": cluster_removed,
        "dual_runway_duplicate_removed": 0,
    }
    return deduped, audit_rows, stats


def infer_runway_orientation(
    df: pd.DataFrame,
    airport: str,
    mode: str,
    window_minutes: int = 30,
    min_ratio: float = 0.6,
    event_time: pd.Series | None = None,
) -> pd.Series:
    orientation = pd.Series(pd.NA, index=df.index, dtype="string")
    rw_col = runway_column(mode)

    if event_time is None:
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


def runway_from_orientation(airport: str, mode: str, orientation: object) -> str:
    if pd.notna(orientation) and str(orientation).strip().lower() == "reverse":
        return RUNWAY_RULES[airport][mode]["reverse"]
    return RUNWAY_RULES[airport][mode]["default"]


def fill_runway_from_nearest_window(
    df: pd.DataFrame,
    rw_col: str,
    event_time: pd.Series,
    needs_fill: pd.Series,
    window_minutes: int = 30,
    use_nearest: bool = False,
    fallback_to_nearest_any: bool = False,
) -> int:
    valid_runway = df[rw_col].astype("string").str.match(RUNWAY_REGEX, na=False)
    filled_count = 0

    if not valid_runway.any() or not needs_fill.any() or not event_time.notna().any():
        return filled_count

    known_idx = df.loc[valid_runway].index
    known_times = event_time.loc[known_idx]
    known_runways = df.loc[known_idx, rw_col].astype("string")

    window_ns = int(pd.Timedelta(minutes=window_minutes).value)
    sorted_known = known_times.sort_values()
    sorted_times_ns = sorted_known.astype("datetime64[ns]").astype("int64").to_numpy()
    sorted_runways = known_runways.loc[sorted_known.index].to_numpy()

    target_idx = event_time.loc[needs_fill & event_time.notna()].sort_values().index
    target_times_ns = event_time.loc[target_idx].astype("datetime64[ns]").astype("int64").to_numpy()

    left = 0
    right = 0
    n_known = len(sorted_times_ns)

    for pos, t_ns in enumerate(target_times_ns):
        idx = target_idx[pos]
        lower = t_ns - window_ns
        upper = t_ns + window_ns

        while left < n_known and sorted_times_ns[left] < lower:
            left += 1
        while right < n_known and sorted_times_ns[right] <= upper:
            right += 1

        window_runways = sorted_runways[left:right]
        if len(window_runways) > 0:
            if use_nearest:
                window_times = sorted_times_ns[left:right]
                nearest_pos = int(np.argmin(np.abs(window_times - t_ns)))
                df.at[idx, rw_col] = str(window_runways[nearest_pos])
                filled_count += 1
            else:
                mode_rw = pd.Series(window_runways).mode()
                if not mode_rw.empty:
                    df.at[idx, rw_col] = str(mode_rw.iloc[0])
                    filled_count += 1
        elif fallback_to_nearest_any and n_known > 0:
            insert_pos = int(np.searchsorted(sorted_times_ns, t_ns, side="left"))
            candidate_positions = []
            if insert_pos < n_known:
                candidate_positions.append(insert_pos)
            if insert_pos > 0:
                candidate_positions.append(insert_pos - 1)
            if candidate_positions:
                nearest_pos = min(candidate_positions, key=lambda p: abs(sorted_times_ns[p] - t_ns))
                df.at[idx, rw_col] = str(sorted_runways[nearest_pos])
                filled_count += 1

    return filled_count


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

    if airport == "DAD" and mode == "departure":
        if "Scheduled_DateTime" in out.columns:
            event_time = pd.to_datetime(out["Scheduled_DateTime"], errors="coerce")
        else:
            event_time = event_datetime_series(out)
        out["_Runway_Orientation"] = infer_runway_orientation(
            out,
            airport=airport,
            mode=mode,
            event_time=event_time,
        )
        needs_fill = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")

        filled_count = fill_runway_from_nearest_window(
            out,
            rw_col=rw_col,
            event_time=event_time,
            needs_fill=needs_fill,
            window_minutes=30,
            use_nearest=True,
            fallback_to_nearest_any=True,
        )

        stats["runway_filled_nearest"] = filled_count
        remaining = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")
        stats["runway_filled_default"] = int(remaining.sum())
        if remaining.any():
            out.loc[remaining, rw_col] = [
                runway_from_orientation(airport, mode, out.at[idx, "_Runway_Orientation"])
                for idx in out.loc[remaining].index
            ]
        return out, stats

    if airport == "DAD" and mode == "arrival":
        if "Scheduled_DateTime" in out.columns:
            event_time = pd.to_datetime(out["Scheduled_DateTime"], errors="coerce")
        else:
            event_time = event_datetime_series(out)
        out["_Runway_Orientation"] = infer_runway_orientation(
            out,
            airport=airport,
            mode=mode,
            event_time=event_time,
        )
        needs_fill = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")
        stats["runway_filled_nearest"] = fill_runway_from_nearest_window(
            out,
            rw_col=rw_col,
            event_time=event_time,
            needs_fill=needs_fill,
            window_minutes=30,
            use_nearest=True,
            fallback_to_nearest_any=True,
        )

        remaining_mask = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")
        if remaining_mask.any():
            stats["runway_filled_default"] = int(remaining_mask.sum())
            out.loc[remaining_mask, rw_col] = [
                runway_from_orientation(airport, mode, out.at[idx, "_Runway_Orientation"])
                for idx in out.loc[remaining_mask].index
            ]

        return out, stats

    if "Actual_DateTime" in out.columns:
        event_time = pd.to_datetime(out["Actual_DateTime"], errors="coerce")
    else:
        event_time = event_datetime_series(out)

    out["_Runway_Orientation"] = infer_runway_orientation(
        out,
        airport=airport,
        mode=mode,
        event_time=event_time,
    )
    needs_fill = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")
    stats["runway_filled_nearest"] = fill_runway_from_nearest_window(
        out,
        rw_col=rw_col,
        event_time=event_time,
        needs_fill=needs_fill,
        window_minutes=30,
        use_nearest=True,
        fallback_to_nearest_any=False,
    )

    remaining_mask = out[rw_col].isna() | out[rw_col].astype("string").str.strip().str.lower().eq("unknown")
    if remaining_mask.any():
        stats["runway_filled_default"] = int(remaining_mask.sum())
        out.loc[remaining_mask, rw_col] = [
            runway_from_orientation(airport, mode, out.at[idx, "_Runway_Orientation"])
            for idx in out.loc[remaining_mask].index
        ]

    return out, stats


def normalize_category_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    if text in NA_TOKENS:
        return ""
    return text


def emergency_arrival_runway_mask(arrival_df: pd.DataFrame, airport: str) -> pd.Series:
    if "Arrival_Runway" not in arrival_df.columns:
        return pd.Series(False, index=arrival_df.index)

    emergency_runway = RUNWAY_RULES[airport]["arrival"]["emergency"]
    runway = arrival_df["Arrival_Runway"].astype("string").str.strip().str.upper()
    return runway.eq(emergency_runway).fillna(False).astype(bool)


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
    emergency_runway = emergency_arrival_runway_mask(arr, airport)
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
        is_emergency_runway = bool(emergency_runway.at[idx])
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
                    "Arrival_Runway": arr.at[idx, "Arrival_Runway"] if "Arrival_Runway" in arr.columns else pd.NA,
                    "Is_Emergency_Runway": is_emergency_runway,
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
                    "Arrival_Runway": arr.at[idx, "Arrival_Runway"] if "Arrival_Runway" in arr.columns else pd.NA,
                    "Is_Emergency_Runway": is_emergency_runway,
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
            normal_runway = (
                RUNWAY_RULES[airport]["arrival"]["reverse"]
                if pd.notna(orientation) and str(orientation) == "reverse"
                else RUNWAY_RULES[airport]["arrival"]["default"]
            )
            arr.at[idx, "Arrival_Runway"] = normal_runway

            audit_rows.append(
                {
                    "Airport": airport,
                    "Row_Index": int(idx),
                    "Flight_No": flight_no,
                    "Category": category,
                    "Arrival_Runway": arr.at[idx, "Arrival_Runway"] if "Arrival_Runway" in arr.columns else pd.NA,
                    "Is_Emergency_Runway": is_emergency_runway,
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


def add_dad_departure_gate_features(df: pd.DataFrame) -> pd.DataFrame:
    if "Gate" not in df.columns or "Terminal" not in df.columns:
        return df

    out = df.copy()
    terminal = out["Terminal"].astype("string").str.strip()
    terminal = terminal.str.replace(r"\.0$", "", regex=True)
    terminal = terminal.mask(terminal.str.lower().isin(NA_TOKENS))

    gate_text = out["Gate"].astype("string").str.strip()
    gate_text = gate_text.mask(gate_text.str.lower().isin(NA_TOKENS))
    gate_num = gate_text.str.extract(r"(\d{1,2})", expand=False)
    gate_num = pd.to_numeric(gate_num, errors="coerce").astype("Int64")

    is_jet_bridge = pd.Series(pd.NA, index=out.index, dtype="Int64")

    term1_mask = terminal.eq("1") & gate_num.notna()
    term2_mask = terminal.eq("2") & gate_num.notna()

    term1_bus = {1, 2, 3, 9, 10, 11}
    term1_jet = {4, 5, 6, 7, 8}
    term2_bus = {1, 2, 3, 8, 9, 10}
    term2_jet = {4, 5, 6, 7}

    term1_bus_mask = term1_mask & gate_num.isin(term1_bus)
    term1_jet_mask = term1_mask & gate_num.isin(term1_jet)
    term2_bus_mask = term2_mask & gate_num.isin(term2_bus)
    term2_jet_mask = term2_mask & gate_num.isin(term2_jet)

    is_jet_bridge.loc[term1_bus_mask | term2_bus_mask] = 0
    is_jet_bridge.loc[term1_jet_mask | term2_jet_mask] = 1

    out["Is_Jet_Bridge"] = is_jet_bridge
    out["Is_Remote_Stand"] = is_jet_bridge.where(is_jet_bridge.isna(), 1 - is_jet_bridge)
    return out


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
    origin_upper = origin.upper()
    dest_upper = dest.upper()
    dep_time = event_datetime_series(departure_df)
    arr_time = event_datetime_series(arrival_df)

    rename_tail_column(departure_df, mode = "departure")
    rename_tail_column(arrival_df, mode = "arrival")

    dep_mask = departure_df["Flight_No"].notna() & dep_time.notna()
    if "IATA" in departure_df.columns:
        dep_mask = dep_mask & (departure_df["IATA"].astype("string").str.upper().str.strip() == dest_upper)

    arr_mask = arrival_df["Flight_No"].notna() & arr_time.notna()
    if "IATA" in arrival_df.columns:
        arr_mask = arr_mask & (arrival_df["IATA"].astype("string").str.upper().str.strip() == origin_upper)

    dep_work = departure_df.loc[dep_mask, ["Flight_No", "Scheduled_Tail"]].copy()
    arr_work = arrival_df.loc[arr_mask, ["Flight_No", "Actual_Tail"]].copy()

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
    nearest["Route"] = f"{origin_upper}->{dest_upper}"
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


def apply_swap_tail_overrides_for_dad(
    departures: Dict[str, pd.DataFrame],
    arrivals: Dict[str, pd.DataFrame],
    swap_audit_df: pd.DataFrame,
) -> Dict[str, int]:
    if swap_audit_df.empty:
        return {"swap_true_rows_used": 0, "dad_arrival_tail_overrides": 0, "dad_departure_tail_overrides": 0}

    dad_arr = arrivals.get("dad")
    dad_dep = departures.get("dad")
    if dad_arr is None or dad_dep is None:
        return {"swap_true_rows_used": 0, "dad_arrival_tail_overrides": 0, "dad_departure_tail_overrides": 0}

    swapped_mask = swap_audit_df["Is_Aircraft_Swapped"].astype("string").str.strip().str.lower() == "true"
    override_rows = swap_audit_df.loc[
        swapped_mask & swap_audit_df["Route"].isin(["SGN->DAD", "HAN->DAD", "DAD->SGN", "DAD->HAN"])
    ].copy()
    if override_rows.empty:
        return {"swap_true_rows_used": 0, "dad_arrival_tail_overrides": 0, "dad_departure_tail_overrides": 0}

    arrival_overrides = 0
    departure_overrides = 0

    def normalize_tail(value: object) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if text.lower() in NA_TOKENS:
            return None
        return text.upper()

    for _, row in override_rows.iterrows():
        route = str(row.get("Route", "")).strip().upper()
        if route in ("SGN->DAD", "HAN->DAD"):
            arr_idx = row.get("Arr_Index")
            new_tail = normalize_tail(row.get("Scheduled_Tail"))
            if new_tail is None or arr_idx is None:
                continue
            try:
                arr_idx = int(arr_idx)
            except (TypeError, ValueError):
                continue
            if arr_idx not in dad_arr.index:
                continue
            if "Actual_Tail" in dad_arr.columns and normalize_tail(dad_arr.at[arr_idx, "Actual_Tail"]) != new_tail:
                dad_arr.at[arr_idx, "Actual_Tail"] = new_tail
                arrival_overrides += 1
        elif route in ("DAD->SGN", "DAD->HAN"):
            dep_idx = row.get("Dep_Index")
            new_tail = normalize_tail(row.get("Actual_Tail"))
            if new_tail is None or dep_idx is None:
                continue
            try:
                dep_idx = int(dep_idx)
            except (TypeError, ValueError):
                continue
            if dep_idx not in dad_dep.index:
                continue
            if "Scheduled_Tail" in dad_dep.columns and normalize_tail(dad_dep.at[dep_idx, "Scheduled_Tail"]) != new_tail:
                dad_dep.at[dep_idx, "Scheduled_Tail"] = new_tail
                departure_overrides += 1

    arrivals["dad"] = dad_arr
    departures["dad"] = dad_dep
    return {
        "swap_true_rows_used": int(len(override_rows)),
        "dad_arrival_tail_overrides": arrival_overrides,
        "dad_departure_tail_overrides": departure_overrides,
    }


def audit_departures_without_arrival(
    departures: Dict[str, pd.DataFrame],
    arrivals: Dict[str, pd.DataFrame],
    routes: List[Tuple[str, str]],
    max_gap_hours: float,
) -> List[Dict[str, object]]:
    audit_rows: List[Dict[str, object]] = []

    for origin, dest in routes:
        origin_upper = origin.upper()
        dest_upper = dest.upper()

        dep_df = departures.get(origin)
        if dep_df is None or dep_df.empty:
            continue

        arr_df = arrivals.get(dest)
        dep_time = event_datetime_series(dep_df)
        if "Scheduled_DateTime" in dep_df.columns:
            dep_service_time = pd.to_datetime(dep_df["Scheduled_DateTime"], errors="coerce")
        elif "Scheduled_Time" in dep_df.columns:
            dep_service_time = pd.to_datetime(dep_df["Scheduled_Time"], errors="coerce")
        else:
            dep_service_time = dep_time

        dep_mask = dep_df["Flight_No"].notna() & dep_time.notna()
        if "IATA" in dep_df.columns:
            dep_mask = dep_mask & (dep_df["IATA"].astype("string").str.upper().str.strip() == dest_upper)
        if "Category" in dep_df.columns:
            category = dep_df["Category"].astype("string").str.strip()
            category = category.mask(category.str.lower().isin(NA_TOKENS))
            dep_mask = dep_mask & category.str.lower().eq("passenger")

        dep_work = dep_df.loc[dep_mask, ["Flight_No", "Scheduled_Time"]].copy()
        if dep_work.empty:
            continue

        dep_work["Dep_Index"] = dep_work.index
        dep_work["Dep_Time"] = dep_time.loc[dep_work.index]
        dep_work["Dep_Service_Date"] = dep_service_time.loc[dep_work.index].dt.strftime("%Y-%m-%d")
        dep_work["Flight_Key"] = dep_work["Flight_No"].astype("string").str.upper().str.strip()

        if arr_df is None or arr_df.empty:
            for _, row in dep_work.iterrows():
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Dep_Index": int(row["Dep_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Dep_Event_Time": row["Dep_Time"],
                        "Scheduled_Time": row.get("Scheduled_Time", pd.NA),
                        "Dep_Service_Date": row.get("Dep_Service_Date", pd.NA),
                        "Reason": "no_arrival_dataset",
                    }
                )
            continue

        arr_time = event_datetime_series(arr_df)
        if "Scheduled_DateTime" in arr_df.columns:
            arr_service_time = pd.to_datetime(arr_df["Scheduled_DateTime"], errors="coerce")
        elif "Scheduled_Time" in arr_df.columns:
            arr_service_time = pd.to_datetime(arr_df["Scheduled_Time"], errors="coerce")
        else:
            arr_service_time = arr_time
        arr_service_time = arr_service_time.where(arr_service_time.notna(), arr_time)
        arr_mask = arr_df["Flight_No"].notna() & arr_time.notna()
        if "IATA" in arr_df.columns:
            arr_mask = arr_mask & (arr_df["IATA"].astype("string").str.upper().str.strip() == origin_upper)

        arr_work = arr_df.loc[arr_mask, ["Flight_No"]].copy()
        if arr_work.empty:
            for _, row in dep_work.iterrows():
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Dep_Index": int(row["Dep_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Dep_Event_Time": row["Dep_Time"],
                        "Scheduled_Time": row.get("Scheduled_Time", pd.NA),
                        "Dep_Service_Date": row.get("Dep_Service_Date", pd.NA),
                        "Reason": "no_arrival_rows",
                    }
                )
            continue

        arr_work["Arr_Time"] = arr_time.loc[arr_work.index]
        arr_work["Arr_Service_Date"] = arr_service_time.loc[arr_work.index].dt.strftime("%Y-%m-%d")
        arr_work["Flight_Key"] = arr_work["Flight_No"].astype("string").str.upper().str.strip()

        arr_time_lookup: Dict[str, np.ndarray] = {}
        for flight_key, grp in arr_work.groupby("Flight_Key"):
            arr_time_lookup[str(flight_key)] = grp["Arr_Time"].sort_values().to_numpy(dtype="datetime64[ns]")

        for _, row in dep_work.iterrows():
            dep_event_time = row["Dep_Time"]
            if pd.isna(dep_event_time):
                continue
            flight_key = str(row["Flight_Key"])

            time_window_matched = False
            flight_arr_times = arr_time_lookup.get(flight_key)
            if flight_arr_times is not None and flight_arr_times.size > 0:
                lower = np.datetime64(dep_event_time)
                upper = np.datetime64(dep_event_time + pd.Timedelta(hours=max_gap_hours))
                left = np.searchsorted(flight_arr_times, lower, side="left")
                right = np.searchsorted(flight_arr_times, upper, side="right")
                time_window_matched = right > left

            if not time_window_matched:
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Dep_Index": int(row["Dep_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Dep_Event_Time": dep_event_time,
                        "Scheduled_Time": row.get("Scheduled_Time", pd.NA),
                        "Dep_Service_Date": row.get("Dep_Service_Date", pd.NA),
                        "Reason": "no_arrival_match",
                    }
                )
                continue

    return audit_rows


def drop_departures_without_arrival(
    departures: Dict[str, pd.DataFrame],
    audit_rows: List[Dict[str, object]],
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    drop_indices_by_airport: Dict[str, Set[int]] = {airport: set() for airport in departures}

    for row in audit_rows:
        origin = str(row.get("Origin", "")).strip().lower()
        if origin not in drop_indices_by_airport:
            continue
        dep_index = row.get("Dep_Index")
        try:
            dep_index_int = int(dep_index)
        except (TypeError, ValueError):
            continue
        drop_indices_by_airport[origin].add(dep_index_int)
        row["Action"] = "drop_departure"
        row["Drop_Reason"] = "dep_without_arrival"

    stats: Dict[str, int] = {}
    for airport, indices in drop_indices_by_airport.items():
        if not indices:
            stats[f"{airport.upper()}_departures_dropped_without_arrival"] = 0
            continue

        df = departures[airport]
        valid_indices = sorted(idx for idx in indices if idx in df.index)
        departures[airport] = df.drop(index=valid_indices).copy()
        stats[f"{airport.upper()}_departures_dropped_without_arrival"] = len(valid_indices)

    stats["departures_dropped_without_arrival_total"] = sum(stats.values())
    return departures, stats


def audit_arrivals_without_departure(
    arrivals: Dict[str, pd.DataFrame],
    departures: Dict[str, pd.DataFrame],
    routes: List[Tuple[str, str]],
    max_gap_hours: float,
) -> List[Dict[str, object]]:
    audit_rows: List[Dict[str, object]] = []

    for origin, dest in routes:
        origin_upper = origin.upper()
        dest_upper = dest.upper()

        arr_df = arrivals.get(dest)
        if arr_df is None or arr_df.empty:
            continue

        dep_df = departures.get(origin)
        arr_time = event_datetime_series(arr_df)
        if "Scheduled_DateTime" in arr_df.columns:
            arr_service_time = pd.to_datetime(arr_df["Scheduled_DateTime"], errors="coerce")
        elif "Scheduled_Time" in arr_df.columns:
            arr_service_time = pd.to_datetime(arr_df["Scheduled_Time"], errors="coerce")
        else:
            arr_service_time = arr_time
        arr_service_time = arr_service_time.where(arr_service_time.notna(), arr_time)

        arr_mask = arr_df["Flight_No"].notna() & arr_time.notna()
        if "IATA" in arr_df.columns:
            arr_mask = arr_mask & (arr_df["IATA"].astype("string").str.upper().str.strip() == origin_upper)
        if "Category" in arr_df.columns:
            category = arr_df["Category"].astype("string").str.strip()
            category = category.mask(category.str.lower().isin(NA_TOKENS))
            arr_mask = arr_mask & category.str.lower().eq("passenger")

        arr_work = arr_df.loc[arr_mask, ["Flight_No"]].copy()
        if arr_work.empty:
            continue

        arr_work["Arr_Index"] = arr_work.index
        arr_work["Arr_Time"] = arr_time.loc[arr_work.index]
        arr_work["Arr_Service_Date"] = arr_service_time.loc[arr_work.index].dt.strftime("%Y-%m-%d")
        arr_work["Flight_Key"] = arr_work["Flight_No"].astype("string").str.upper().str.strip()

        if dep_df is None or dep_df.empty:
            for _, row in arr_work.iterrows():
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Arr_Index": int(row["Arr_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Arr_Event_Time": row["Arr_Time"],
                        "Arr_Service_Date": row.get("Arr_Service_Date", pd.NA),
                        "Reason": "no_departure_dataset",
                    }
                )
            continue

        dep_time = event_datetime_series(dep_df)
        if "Scheduled_DateTime" in dep_df.columns:
            dep_service_time = pd.to_datetime(dep_df["Scheduled_DateTime"], errors="coerce")
        elif "Scheduled_Time" in dep_df.columns:
            dep_service_time = pd.to_datetime(dep_df["Scheduled_Time"], errors="coerce")
        else:
            dep_service_time = dep_time

        dep_mask = dep_df["Flight_No"].notna() & dep_time.notna()
        if "IATA" in dep_df.columns:
            dep_mask = dep_mask & (dep_df["IATA"].astype("string").str.upper().str.strip() == dest_upper)

        dep_work = dep_df.loc[dep_mask, ["Flight_No"]].copy()
        if dep_work.empty:
            for _, row in arr_work.iterrows():
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Arr_Index": int(row["Arr_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Arr_Event_Time": row["Arr_Time"],
                        "Arr_Service_Date": row.get("Arr_Service_Date", pd.NA),
                        "Reason": "no_departure_rows",
                    }
                )
            continue

        dep_work["Dep_Time"] = dep_time.loc[dep_work.index]
        dep_work["Dep_Service_Date"] = dep_service_time.loc[dep_work.index].dt.strftime("%Y-%m-%d")
        dep_work["Flight_Key"] = dep_work["Flight_No"].astype("string").str.upper().str.strip()

        dep_time_lookup: Dict[str, np.ndarray] = {}
        for flight_key, grp in dep_work.groupby("Flight_Key"):
            dep_time_lookup[str(flight_key)] = grp["Dep_Time"].sort_values().to_numpy(dtype="datetime64[ns]")

        for _, row in arr_work.iterrows():
            arr_event_time = row["Arr_Time"]
            if pd.isna(arr_event_time):
                continue
            flight_key = str(row["Flight_Key"])

            time_window_matched = False
            flight_dep_times = dep_time_lookup.get(flight_key)
            if flight_dep_times is not None and flight_dep_times.size > 0:
                lower = np.datetime64(arr_event_time - pd.Timedelta(hours=max_gap_hours))
                upper = np.datetime64(arr_event_time)
                left = np.searchsorted(flight_dep_times, lower, side="left")
                right = np.searchsorted(flight_dep_times, upper, side="right")
                time_window_matched = right > left

            if not time_window_matched:
                audit_rows.append(
                    {
                        "Route": f"{origin_upper}->{dest_upper}",
                        "Origin": origin_upper,
                        "Destination": dest_upper,
                        "Arr_Index": int(row["Arr_Index"]),
                        "Flight_No": row["Flight_No"],
                        "Arr_Event_Time": arr_event_time,
                        "Arr_Service_Date": row.get("Arr_Service_Date", pd.NA),
                        "Reason": "no_departure_match",
                    }
                )

    return audit_rows


def drop_arrivals_without_departure_for_routes(
    arrivals: Dict[str, pd.DataFrame],
    audit_rows: List[Dict[str, object]],
    routes_to_drop: Set[Tuple[str, str]],
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    drop_indices_by_airport: Dict[str, Set[int]] = {airport: set() for airport in arrivals}

    for row in audit_rows:
        origin = str(row.get("Origin", "")).strip().upper()
        dest = str(row.get("Destination", "")).strip().upper()
        if (origin, dest) not in routes_to_drop:
            row["Action"] = "keep_arrival_pending_review"
            row["Drop_Reason"] = pd.NA
            continue

        dest_key = dest.lower()
        if dest_key not in drop_indices_by_airport:
            row["Action"] = "keep_arrival_pending_review"
            row["Drop_Reason"] = pd.NA
            continue

        arr_index = row.get("Arr_Index")
        try:
            arr_index_int = int(arr_index)
        except (TypeError, ValueError):
            row["Action"] = "keep_arrival_pending_review"
            row["Drop_Reason"] = pd.NA
            continue

        drop_indices_by_airport[dest_key].add(arr_index_int)
        row["Action"] = "drop_arrival"
        row["Drop_Reason"] = "arrival_without_departure"

    stats: Dict[str, int] = {}
    for airport, indices in drop_indices_by_airport.items():
        if not indices:
            stats[f"{airport.upper()}_arrivals_dropped_without_departure"] = 0
            continue

        df = arrivals[airport]
        valid_indices = sorted(idx for idx in indices if idx in df.index)
        arrivals[airport] = df.drop(index=valid_indices).copy()
        stats[f"{airport.upper()}_arrivals_dropped_without_departure"] = len(valid_indices)

    stats["arrivals_dropped_without_departure_total"] = sum(stats.values())
    return arrivals, stats


def initialize_match_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Has_Matched_Departure"] = True
    out["Has_Matched_Arrival"] = True
    out["Match_Status"] = "matched"
    out["Data_Completeness"] = "complete"
    out["Exclude_From_Propagation_Training"] = False
    return out


def mark_departures_without_arrival(
    departures: Dict[str, pd.DataFrame],
    audit_rows: List[Dict[str, object]],
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    marked_indices_by_airport: Dict[str, Set[int]] = {airport: set() for airport in departures}

    for row in audit_rows:
        origin = str(row.get("Origin", "")).strip().lower()
        if origin not in marked_indices_by_airport:
            row["Action"] = "keep_unmatched_departure"
            row["Drop_Reason"] = pd.NA
            continue

        dep_index = row.get("Dep_Index")
        try:
            dep_index_int = int(dep_index)
        except (TypeError, ValueError):
            row["Action"] = "keep_unmatched_departure"
            row["Drop_Reason"] = pd.NA
            continue

        marked_indices_by_airport[origin].add(dep_index_int)
        row["Action"] = "mark_missing_arrival"
        row["Drop_Reason"] = pd.NA

    stats: Dict[str, int] = {}
    for airport, indices in marked_indices_by_airport.items():
        df = departures[airport]
        valid_indices = sorted(idx for idx in indices if idx in df.index)
        if valid_indices:
            df.loc[valid_indices, "Has_Matched_Departure"] = True
            df.loc[valid_indices, "Has_Matched_Arrival"] = False
            df.loc[valid_indices, "Match_Status"] = "dep_without_arrival"
            df.loc[valid_indices, "Data_Completeness"] = "unmatched_departure"
            df.loc[valid_indices, "Exclude_From_Propagation_Training"] = True
        stats[f"{airport.upper()}_departures_marked_without_arrival"] = len(valid_indices)

    stats["departures_marked_without_arrival_total"] = sum(stats.values())
    return departures, stats


def mark_arrivals_without_departure(
    arrivals: Dict[str, pd.DataFrame],
    audit_rows: List[Dict[str, object]],
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    marked_indices_by_airport: Dict[str, Set[int]] = {airport: set() for airport in arrivals}

    for row in audit_rows:
        dest = str(row.get("Destination", "")).strip().lower()
        if dest not in marked_indices_by_airport:
            row["Action"] = "keep_unmatched_arrival"
            row["Drop_Reason"] = pd.NA
            continue

        arr_index = row.get("Arr_Index")
        try:
            arr_index_int = int(arr_index)
        except (TypeError, ValueError):
            row["Action"] = "keep_unmatched_arrival"
            row["Drop_Reason"] = pd.NA
            continue

        marked_indices_by_airport[dest].add(arr_index_int)
        row["Action"] = "mark_missing_departure"
        row["Drop_Reason"] = pd.NA

    stats: Dict[str, int] = {}
    for airport, indices in marked_indices_by_airport.items():
        df = arrivals[airport]
        valid_indices = sorted(idx for idx in indices if idx in df.index)
        if valid_indices:
            df.loc[valid_indices, "Has_Matched_Departure"] = False
            df.loc[valid_indices, "Has_Matched_Arrival"] = True
            df.loc[valid_indices, "Match_Status"] = "arrival_without_departure"
            df.loc[valid_indices, "Data_Completeness"] = "unmatched_arrival"
            df.loc[valid_indices, "Exclude_From_Propagation_Training"] = True
        stats[f"{airport.upper()}_arrivals_marked_without_departure"] = len(valid_indices)

    stats["arrivals_marked_without_departure_total"] = sum(stats.values())
    return arrivals, stats


def finalize_dataframe_for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    time_format = "%Y-%m-%d %H:%M"

    def format_to_minute(series: pd.Series) -> pd.Series:
        return series.dt.strftime(time_format)

    if "Actual_Time" in out.columns and "Actual_DateTime" in out.columns:
        actual_text = format_to_minute(out["Actual_DateTime"])
        out["Actual_Time"] = out["Actual_Time"].astype("string")
        out.loc[out["Actual_DateTime"].notna(), "Actual_Time"] = actual_text

    if "Scheduled_Time" in out.columns and "Scheduled_DateTime" in out.columns:
        scheduled_text = format_to_minute(out["Scheduled_DateTime"])
        out["Scheduled_Time"] = out["Scheduled_Time"].astype("string")
        out.loc[out["Scheduled_DateTime"].notna(), "Scheduled_Time"] = scheduled_text

    redundant_cols = [
        "Arrival_Planned_Landing_Time",
        "Arrival_Actual_Landing_Time",
        "Arrival_Planned_Landing_DateTime",
        "Arrival_Actual_Landing_DateTime",
        "Scheduled_DateTime",
        "Actual_DateTime",
    ]
    helper_cols = ["_Runway_Orientation"]
    drop_cols = [c for c in helper_cols + redundant_cols if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)

    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            out[col] = out[col].fillna("N/A")
        elif pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].astype("string").fillna("N/A")

    return out


def sort_flights_for_export(df: pd.DataFrame, airport: str) -> pd.DataFrame:
    out = df.copy()
    primary_col = "Scheduled_DateTime" if airport.upper() == "DAD" else "Actual_DateTime"

    if primary_col in out.columns:
        primary_time = pd.to_datetime(out[primary_col], errors="coerce")
    else:
        primary_time = event_datetime_series(out)

    if "Crawl_Date" in out.columns:
        crawl_date = pd.to_datetime(out["Crawl_Date"], errors="coerce")
    else:
        crawl_date = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")

    out["_Sort_Crawl_Date"] = crawl_date
    out["_Sort_Event_Time"] = primary_time
    out["_Sort_Original_Order"] = np.arange(len(out))

    sort_cols = ["_Sort_Crawl_Date", "_Sort_Event_Time", "_Sort_Original_Order"]
    out = out.sort_values(sort_cols, kind="mergesort", na_position="last")
    out = out.drop(columns=sort_cols).reset_index(drop=True)
    return out


def normalize_file_common(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    stats: Dict[str, object] = {}

    df = normalize_na_tokens(df)
    df, header_removed = remove_header_like_rows(df)
    stats["header_rows_removed"] = header_removed

    df = ensure_required_columns(df, airport=airport, mode=mode)
    stats["invalid_iata_fixed"] = validate_iata_column(df)
    stats["invalid_runway_fixed"] = sanitize_runway_values(df, mode=mode)

    df, datetime_stats = add_datetime_columns_with_rollover(df, airport=airport, mode=mode)
    stats.update(datetime_stats)
    return df, stats


def write_audit_csv(path: Path, records: List[Dict[str, object]]) -> None:
    if records:
        pd.DataFrame(records).to_csv(path, index=False)
    else:
        pd.DataFrame().to_csv(path, index=False)


def run_pipeline(
    project_root: Path,
    return_threshold_minutes: int,
    silver_layer_name: str = DEFAULT_SILVER_LAYER_NAME,
) -> None:
    if return_threshold_minutes <= 0:
        raise ValueError("return_threshold_minutes must be positive")

    if return_threshold_minutes > RETURN_THRESHOLD_MAX_MINUTES:
        print(
            f"[WARN] Return threshold {return_threshold_minutes} > {RETURN_THRESHOLD_MAX_MINUTES}. "
            f"Keeping provided value, but recommended range is <= {RETURN_THRESHOLD_MAX_MINUTES}."
        )

    input_bronze_dir = project_root / "Data" / "Bronze_layer_cleaned"
    if not input_bronze_dir.exists():
        input_bronze_dir = project_root / "Data" / "Bronze_layer"
    arrival_dir = input_bronze_dir / "Arrival"
    departure_dir = input_bronze_dir / "Departure"

    silver_dir = project_root / "Data" / silver_layer_name
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
    arrival_semantics_audit_rows: List[Dict[str, object]] = []
    time_gap_over_12h_audit_rows: List[Dict[str, object]] = []
    missing_arrival_audit_rows: List[Dict[str, object]] = []
    missing_departure_audit_rows: List[Dict[str, object]] = []

    # 1) Load and clean basic schema.
    for airport in AIRPORTS:
        for mode in ("departure", "arrival"):
            src_dir = arrival_dir if mode == "arrival" else departure_dir
            src_name = f"{airport}_flights_{mode}_bronze_layer.csv"
            src_path = src_dir / src_name
            if not src_path.exists():
                raise FileNotFoundError(f"Missing input file: {src_path}")

            df = pd.read_csv(src_path, dtype=str)
            restored_same_origin_rows = 0
            row_before = len(df)

            df, basic_stats = normalize_file_common(df, airport=airport.upper(), mode=mode)
            row_after_basic = len(df)

            time_gap_over_12h_audit_rows.extend(
                collect_time_gap_over_12h_audit(df, airport=airport.upper(), mode=mode)
            )

            if mode == "arrival":
                arrival_semantics_audit_rows.append(
                    {
                        "airport": airport.upper(),
                        "rows_total_arrival": int(basic_stats.get("rows_total_arrival", len(df))),
                        "rows_actual_landing_parsed": int(basic_stats.get("rows_actual_landing_parsed", 0)),
                        "rows_planned_landing_parsed": int(basic_stats.get("rows_planned_landing_parsed", 0)),
                        "rows_duration_parsed": int(basic_stats.get("rows_duration_parsed", 0)),
                        "rows_duration_parse_failed": int(basic_stats.get("rows_duration_parse_failed", 0)),
                        "rows_actual_landing_missing": int(basic_stats.get("rows_actual_landing_missing", 0)),
                        "mapping_profile_applied": basic_stats.get("mapping_profile_applied", "UNKNOWN"),
                    }
                )

            dad_fix_stats = {
                "dad_cancelled_cleared": 0,
                "dad_bl_to_vn": 0,
                "dad_airline_pacific_to_vietnam": 0,
            }

            arrival_for_departure_dedup = None
            if mode == "departure":
                arrival_ref_path = arrival_dir / f"{airport}_flights_arrival_bronze_layer.csv"
                if arrival_ref_path.exists():
                    arrival_for_departure_dedup = pd.read_csv(arrival_ref_path, dtype=str)
                    arrival_for_departure_dedup, _ = normalize_file_common(
                        arrival_for_departure_dedup,
                        airport=airport.upper(),
                        mode="arrival",
                    )
            dep_for_dedup = departures.get(airport) if mode == "arrival" else None
            deduped, dedup_audit, dedup_stats = deduplicate_flights(
                df,
                airport=airport.upper(),
                mode=mode,
                departure_df=dep_for_dedup,
                arrival_df=arrival_for_departure_dedup,
                return_threshold_minutes=return_threshold_minutes if mode in ("arrival", "departure") else None,
            )
            duplicate_audit_rows.extend(dedup_audit)

            runway_filled, runway_stats = fill_runway_values(deduped, airport=airport.upper(), mode=mode)

            target = arrivals if mode == "arrival" else departures
            target[airport] = runway_filled

            summary_rows.extend(
                [
                    {"Airport": airport.upper(), "Mode": mode, "Metric": "rows_input", "Value": row_before},
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "same_origin_rows_restored_from_prior_audit",
                        "Value": restored_same_origin_rows,
                    },
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
                        "Metric": "same_day_60m_duplicate_removed",
                        "Value": dedup_stats.get("same_day_60m_duplicate_removed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "dual_runway_duplicate_removed",
                        "Value": dedup_stats.get("dual_runway_duplicate_removed", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "dad_cancelled_cleared",
                        "Value": dad_fix_stats.get("dad_cancelled_cleared", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "dad_bl_to_vn",
                        "Value": dad_fix_stats.get("dad_bl_to_vn", 0),
                    },
                    {
                        "Airport": airport.upper(),
                        "Mode": mode,
                        "Metric": "dad_airline_pacific_to_vietnam",
                        "Value": dad_fix_stats.get("dad_airline_pacific_to_vietnam", 0),
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

    # 1b) Cross-correct arrival actual dates against matched departures.
    arrivals, cross_stats = cross_correct_arrival_dates(
        departures,
        arrivals,
        routes=ROUTES,
        max_gap_hours=ROUTE_MATCH_MAX_HOURS,
    )
    summary_rows.append(
        {
            "Airport": "ALL",
            "Mode": "arrival",
            "Metric": "arrivals_cross_corrected",
            "Value": cross_stats.get("arrivals_corrected", 0),
        }
    )

    # 2) Same-origin anomaly handling on arrival, using departure of the same airport.
    carried_same_origin_count = 0
    summary_rows.append(
        {
            "Airport": "ALL",
            "Mode": "arrival",
            "Metric": "same_origin_noncommercial_audit_carried_forward",
            "Value": carried_same_origin_count,
        }
    )

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

    # 3) Final source-specific feature alignment.
    for airport in AIRPORTS:
        for mode, datasets in (("arrival", arrivals), ("departure", departures)):
            df = datasets[airport]

            if airport.upper() == "DAD" and mode == "departure":
                df = add_dad_departure_gate_features(df)

            df = rename_tail_column(df, mode=mode)
            datasets[airport] = df

    # 4) Aircraft swap matching and flagging.
    departures, swap_audit_df, swap_stats = add_aircraft_swap_flags(
        departures,
        arrivals,
        routes=ROUTES,
        max_gap_hours=ROUTE_MATCH_MAX_HOURS,
    )

    override_stats = apply_swap_tail_overrides_for_dad(departures, arrivals, swap_audit_df)
    if override_stats.get("swap_true_rows_used", 0) > 0:
        departures, swap_audit_df, swap_stats = add_aircraft_swap_flags(
            departures,
            arrivals,
            routes=ROUTES,
            max_gap_hours=ROUTE_MATCH_MAX_HOURS,
        )

    for metric, value in swap_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "departure", "Metric": metric, "Value": int(value)})
    for metric, value in override_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "departure", "Metric": metric, "Value": int(value)})

    for airport in AIRPORTS:
        arrivals[airport] = initialize_match_quality_flags(arrivals[airport])
        departures[airport] = initialize_match_quality_flags(departures[airport])

    missing_arrival_audit_rows = audit_departures_without_arrival(
        departures,
        arrivals,
        routes=ROUTES,
        max_gap_hours=MISSING_ROUTE_MATCH_MAX_HOURS,
    )
    missing_departure_audit_rows = audit_arrivals_without_departure(
        arrivals,
        departures,
        routes=ROUTES,
        max_gap_hours=MISSING_ROUTE_MATCH_MAX_HOURS,
    )
    summary_rows.append(
        {
            "Airport": "ALL",
            "Mode": "arrival",
            "Metric": "arrival_without_departure_rows",
            "Value": len(missing_departure_audit_rows),
        }
    )
    arrivals, missing_departure_mark_stats = mark_arrivals_without_departure(
        arrivals,
        missing_departure_audit_rows,
    )
    for metric, value in missing_departure_mark_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "arrival", "Metric": metric, "Value": int(value)})

    if DROP_DEPARTURES_WITHOUT_ARRIVAL:
        departures, missing_arrival_drop_stats = drop_departures_without_arrival(
            departures,
            missing_arrival_audit_rows,
        )
    else:
        for row in missing_arrival_audit_rows:
            row["Action"] = "keep_departure_pending_review"
            row["Drop_Reason"] = pd.NA
        missing_arrival_drop_stats = {
            f"{airport.upper()}_departures_dropped_without_arrival": 0
            for airport in AIRPORTS
        }
        missing_arrival_drop_stats["departures_dropped_without_arrival_total"] = 0

    for metric, value in missing_arrival_drop_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "departure", "Metric": metric, "Value": int(value)})
    departures, missing_arrival_mark_stats = mark_departures_without_arrival(
        departures,
        missing_arrival_audit_rows,
    )
    for metric, value in missing_arrival_mark_stats.items():
        summary_rows.append({"Airport": "ALL", "Mode": "departure", "Metric": metric, "Value": int(value)})

    # 5) Export cleaned files.
    for airport in AIRPORTS:
        arr_ref_col = "Scheduled_DateTime" if airport.upper() == "DAD" else "Actual_DateTime"
        dep_ref_col = "Scheduled_DateTime" if airport.upper() == "DAD" else "Actual_DateTime"
        if arr_ref_col in arrivals[airport].columns:
            set_crawl_date_from_datetime(arrivals[airport], arrivals[airport][arr_ref_col])
        if dep_ref_col in departures[airport].columns:
            set_crawl_date_from_datetime(departures[airport], departures[airport][dep_ref_col])

        arrivals[airport] = sort_flights_for_export(arrivals[airport], airport=airport.upper())
        departures[airport] = sort_flights_for_export(departures[airport], airport=airport.upper())

        arr_clean = finalize_dataframe_for_export(arrivals[airport])
        dep_clean = finalize_dataframe_for_export(departures[airport])
        if airport.upper() in {"SGN", "HAN"} and "Flight_Time" in arr_clean.columns:
            arr_clean = arr_clean.drop(columns=["Flight_Time"])

        arr_out = silver_arrival_dir / f"{airport}_flights_arrival_silver_layer.csv"
        dep_out = silver_departure_dir / f"{airport}_flights_departure_silver_layer.csv"

        arr_clean.to_csv(arr_out, index=False)
        dep_clean.to_csv(dep_out, index=False)

        summary_rows.append({"Airport": airport.upper(), "Mode": "arrival", "Metric": "rows_output", "Value": len(arr_clean)})
        summary_rows.append({"Airport": airport.upper(), "Mode": "departure", "Metric": "rows_output", "Value": len(dep_clean)})

    # 6) Export audits.
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(silver_audit_dir / "audit_summary.csv", index=False)

    write_audit_csv(silver_audit_dir / "audit_arrival_time_semantics.csv", arrival_semantics_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_time_gap_over_12h.csv", time_gap_over_12h_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_deduplicate_decisions.csv", duplicate_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_same_origin_actions.csv", same_origin_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_departure_without_arrival.csv", missing_arrival_audit_rows)
    write_audit_csv(silver_audit_dir / "audit_arrival_without_departure.csv", missing_departure_audit_rows)

    if swap_audit_df.empty:
        pd.DataFrame().to_csv(silver_audit_dir / "audit_aircraft_swap_matches.csv", index=False)
    else:
        swap_audit_df.to_csv(silver_audit_dir / "audit_aircraft_swap_matches.csv", index=False)

    print("=" * 72)
    print("Silver preprocessing completed")
    print(f"Project root: {project_root}")
    print(f"Silver layer name: {silver_layer_name}")
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
    parser.add_argument(
        "--silver-layer-name",
        type=str,
        default=DEFAULT_SILVER_LAYER_NAME,
        help=f"Output silver layer folder name under Data. Default: {DEFAULT_SILVER_LAYER_NAME}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path.cwd().parent.parent.resolve()

    run_pipeline(
        project_root=project_root,
        return_threshold_minutes=int(args.return_threshold_minutes),
        silver_layer_name=args.silver_layer_name,
    )


if __name__ == "__main__":
    main()
