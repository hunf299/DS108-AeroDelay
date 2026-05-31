import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd


NA_TOKENS = {"", "nan", "none", "na", "n/a", "null"}

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

DOMESTIC_IATA_CODES: Set[str] = {
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


def route_column(mode: str) -> str:
    return "Origin" if mode == "arrival" else "Destination"


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

    df.loc[vn_mask, "Airline"] = prefix.map(VIETNAMESE_CARRIER_BY_PREFIX)
    df.loc[df["Airline"].astype("string").str.upper().eq("KOREAN AIRLINES"), "Airline"] = "Korean Air"

    after = df["Airline"].astype("string")
    return int((before.fillna("") != after.fillna("")).sum())


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
    if key_cols:
        missing_score = pd.Series(0, index=df.index, dtype="int64")
        for col in key_cols:
            missing_score = missing_score + df[col].isna().astype("int64")

        non_passenger = df["Category"].isin(TERMINAL_NON_PASSENGER_CATEGORIES)
        assign_unknown = (missing_score >= 3) & ~non_passenger
        df.loc[assign_unknown, "Category"] = "unknown"

    return apply_category_overrides(df)


def apply_category_overrides(df: pd.DataFrame) -> int:
    if "Category" not in df.columns:
        return 0

    before = df["Category"].astype("string").copy()
    category = df["Category"].astype("string").str.strip().str.lower()

    identity_cols = [
        c
        for c in [
            "Flight_No",
            "Airline",
            "Tail_Number",
            "Aircraft_Type",
            "Arrival_Runway",
            "Departure_Runway",
        ]
        if c in df.columns
    ]
    has_identity = pd.Series(False, index=df.index)
    for col in identity_cols:
        values = df[col].astype("string").str.strip()
        has_identity = has_identity | (values.notna() & ~values.str.lower().isin(NA_TOKENS))

    mask = category.eq("unknown") & has_identity

    if "Airline" in df.columns:
        airline = df["Airline"].astype("string").str.strip().str.upper()
        mask = mask | airline.eq("AVION EXPRESS")

    if "Flight_No" in df.columns:
        flight_no = df["Flight_No"].astype("string").str.strip().str.upper()
        mask = mask | flight_no.str.contains("X", na=False)
        mask = mask | flight_no.str.match(r"^HVV[0-9A-Z]*$", na=False)

    df.loc[mask, "Category"] = "general aviation"

    if "Airline" in df.columns:
        airline = df["Airline"].astype("string").str.strip().str.upper()
        df.loc[airline.eq("AVION EXPRESS"), "Category"] = "business jet"

    return int((before.fillna("") != df["Category"].astype("string").fillna("")).sum())


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

    terminal = terminal.mask(route_missing | same_origin_arrival, pd.NA)

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
    return int((before.fillna("") != df["Terminal"].astype("string").fillna("")).sum())


def apply_route_name_fixes(df: pd.DataFrame, mode: str) -> int:
    route_col = route_column(mode)
    if "IATA" not in df.columns or route_col not in df.columns:
        return 0

    iata = df["IATA"].astype("string").str.upper().str.strip()
    mask = iata.eq("THD")
    changed = int((mask & df[route_col].astype("string").ne("Thanh Hoa")).sum())
    if mask.any():
        df.loc[mask, route_col] = "Thanh Hoa"
    return changed


def apply_dad_arrival_belt_category_rule(df: pd.DataFrame, airport: str, mode: str) -> int:
    if airport != "DAD" or mode != "arrival" or "Belt" not in df.columns or "Category" not in df.columns:
        return 0

    belt = df["Belt"].astype("string").str.strip()
    belt_missing = df["Belt"].isna() | belt.str.lower().isin(NA_TOKENS)
    changed = int((belt_missing & df["Category"].astype("string").str.lower().ne("general aviation")).sum())
    if belt_missing.any():
        df.loc[belt_missing, "Category"] = "general aviation"
    return changed


def parse_duration_minutes_series(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(NA_TOKENS))
    parts = text.str.extract(r"^(?P<hours>\d{1,2}):(?P<minutes>\d{2})$")
    hours = pd.to_numeric(parts["hours"], errors="coerce")
    minutes = pd.to_numeric(parts["minutes"], errors="coerce")
    return hours * 60 + minutes


def drop_han_sgn_arrival_flight_time(df: pd.DataFrame, airport: str, mode: str) -> Tuple[pd.DataFrame, int]:
    if mode != "arrival" or airport not in {"HAN", "SGN"} or "Flight_Time" not in df.columns:
        return df, 0

    out = df.copy()
    duration = parse_duration_minutes_series(out["Flight_Time"])
    if "Arrival_Flight_Duration_Minutes" not in out.columns:
        out["Arrival_Flight_Duration_Minutes"] = duration
    else:
        existing = pd.to_numeric(out["Arrival_Flight_Duration_Minutes"], errors="coerce")
        out["Arrival_Flight_Duration_Minutes"] = existing.where(existing.notna(), duration)
    out = out.drop(columns=["Flight_Time"])
    return out, 1


def apply_dad_specific_value_fixes(df: pd.DataFrame, airport: str) -> Dict[str, int]:
    stats = {
        "dad_cancelled_cleared": 0,
        "dad_bl_to_vn": 0,
        "dad_airline_pacific_to_vietnam": 0,
    }
    if airport != "DAD":
        return stats

    if "Status" in df.columns:
        status = df["Status"].astype("string").str.strip()
        cancelled_mask = status.str.lower().eq("cancelled")
        if cancelled_mask.any():
            df.loc[cancelled_mask, "Status"] = pd.NA
            stats["dad_cancelled_cleared"] = int(cancelled_mask.sum())

    if "Flight_No" in df.columns:
        flight_no = df["Flight_No"].astype("string").str.upper().str.strip()
        bl_mask = flight_no.str.match(r"^BL(\d+)$", na=False)
        if bl_mask.any():
            df.loc[bl_mask, "Flight_No"] = flight_no.loc[bl_mask].str.replace(r"^BL", "VN", regex=True)
            stats["dad_bl_to_vn"] = int(bl_mask.sum())

    if "Airline" in df.columns:
        airline = df["Airline"].astype("string").str.strip()
        pac_mask = airline.str.lower().eq("pacific airlines")
        if pac_mask.any():
            df.loc[pac_mask, "Airline"] = "Vietnam Airlines"
            stats["dad_airline_pacific_to_vietnam"] = int(pac_mask.sum())

    return stats


def normalize_spq_flight_number(
    df: pd.DataFrame,
    airport: str,
    mode: str,
) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    audit_rows: List[Dict[str, object]] = []
    stats = {
        "spq_to_9g_converted": 0,
        "spq_to_9g_airline_match": 0,
        "spq_to_9g_pattern_match": 0,
    }

    if "Flight_No" not in df.columns:
        return audit_rows, stats

    flight_no = df["Flight_No"].astype("string")
    flight_norm = flight_no.str.upper().str.strip()
    spq_mask = flight_norm.str.match(r"^SPQ(\d+)$", na=False)

    if "Airline" in df.columns:
        airline = df["Airline"].astype("string").str.upper().str.strip()
    else:
        airline = pd.Series(pd.NA, index=df.index, dtype="string")

    airline_missing = airline.isna() | airline.str.lower().isin(NA_TOKENS)
    airline_match = airline.str.match(r"^SUN\s*PHU\s*QUOC\s*AIRWAYS$", na=False)

    convert_airline = spq_mask & airline_match
    convert_pattern = spq_mask & airline_missing
    convert_mask = convert_airline | convert_pattern

    if convert_mask.any():
        before_airline = df["Airline"].copy() if "Airline" in df.columns else pd.Series(pd.NA, index=df.index)
        before_flight_no = df["Flight_No"].copy()
        df.loc[convert_mask, "Flight_No"] = flight_norm.loc[convert_mask].str.replace(r"^SPQ", "9G", regex=True)

        for idx in df.loc[convert_mask].index:
            rule = "airline_match" if bool(convert_airline.at[idx]) else "pattern_match"
            audit_rows.append(
                {
                    "airport": airport,
                    "mode": mode,
                    "row_index": int(idx),
                    "airline_before": before_airline.at[idx],
                    "flight_no_before": before_flight_no.at[idx],
                    "flight_no_after": df.at[idx, "Flight_No"],
                    "converted_by_rule": rule,
                }
            )

    stats["spq_to_9g_converted"] = int(convert_mask.sum())
    stats["spq_to_9g_airline_match"] = int(convert_airline.sum())
    stats["spq_to_9g_pattern_match"] = int(convert_pattern.sum())
    return audit_rows, stats


def clean_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return df[col].astype("string").str.strip()


def missing_mask(df: pd.DataFrame, col: str) -> pd.Series:
    values = clean_series(df, col)
    return values.isna() | values.str.lower().isin(NA_TOKENS)


def eq_mask(df: pd.DataFrame, col: str, value: str) -> pd.Series:
    return clean_series(df, col).eq(value)


def eq_upper_mask(df: pd.DataFrame, col: str, value: str) -> pd.Series:
    return clean_series(df, col).str.upper().eq(value.upper())


def record_manual_rows(
    df: pd.DataFrame,
    mask: pd.Series,
    airport: str,
    mode: str,
    action: str,
    rule: str,
    audit_rows: List[Dict[str, object]],
) -> int:
    count = int(mask.sum())
    if count == 0:
        return 0

    for idx, row in df.loc[mask].iterrows():
        audit_rows.append(
            {
                "airport": airport,
                "mode": mode,
                "row_index": int(idx) if isinstance(idx, (int, float)) else idx,
                "action": action,
                "rule": rule,
                "crawl_date": row.get("Crawl_Date", pd.NA),
                "scheduled_time": row.get("Scheduled_Time", pd.NA),
                "actual_time": row.get("Actual_Time", pd.NA),
                "flight_no": row.get("Flight_No", pd.NA),
                "iata": row.get("IATA", pd.NA),
                "airline": row.get("Airline", pd.NA),
                "tail_number": row.get("Tail_Number", pd.NA),
                "aircraft_type": row.get("Aircraft_Type", pd.NA),
                "category": row.get("Category", pd.NA),
            }
        )
    return count


def update_values(
    df: pd.DataFrame,
    mask: pd.Series,
    values: Dict[str, object],
    airport: str,
    mode: str,
    rule: str,
    audit_rows: List[Dict[str, object]],
    stats: Dict[str, int],
) -> int:
    existing_values = {col: val for col, val in values.items() if col in df.columns}
    if not existing_values:
        return 0

    changed = pd.Series(False, index=df.index)
    for col, value in existing_values.items():
        current = df[col].astype("string")
        target = pd.Series(value, index=df.index, dtype="string")
        changed = changed | (current.fillna("") != target.fillna(""))

    target_mask = mask & changed
    count = record_manual_rows(df, target_mask, airport, mode, "update", rule, audit_rows)
    if count:
        for col, value in existing_values.items():
            df.loc[target_mask, col] = value
        stats[rule] = stats.get(rule, 0) + count
    return count


def drop_rows(
    df: pd.DataFrame,
    mask: pd.Series,
    airport: str,
    mode: str,
    rule: str,
    audit_rows: List[Dict[str, object]],
    stats: Dict[str, int],
) -> Tuple[pd.DataFrame, int]:
    count = record_manual_rows(df, mask, airport, mode, "drop", rule, audit_rows)
    if count:
        stats[rule] = stats.get(rule, 0) + count
        return df.drop(index=df.loc[mask].index), count
    return df, 0


def blank_route_identity_mask(df: pd.DataFrame, mode: str) -> pd.Series:
    route_col = route_column(mode)
    return (
        missing_mask(df, route_col)
        & missing_mask(df, "IATA")
        & missing_mask(df, "Airline")
        & missing_mask(df, "Flight_No")
    )


def blank_aircraft_identity_mask(df: pd.DataFrame) -> pd.Series:
    return missing_mask(df, "Tail_Number") & missing_mask(df, "Aircraft_Type")


def manual_fix_stats_template() -> Dict[str, int]:
    return {
        "manual_rows_inserted": 0,
        "manual_rows_dropped": 0,
        "manual_rows_updated": 0,
    }


def apply_targeted_manual_fixes(
    df: pd.DataFrame,
    airport: str,
    mode: str,
) -> Tuple[pd.DataFrame, Dict[str, int], List[Dict[str, object]]]:
    out = df.copy()
    stats = manual_fix_stats_template()
    audit_rows: List[Dict[str, object]] = []

    def update(mask: pd.Series, values: Dict[str, object], rule: str) -> None:
        count = update_values(out, mask, values, airport, mode, rule, audit_rows, stats)
        stats["manual_rows_updated"] += count

    def drop(mask: pd.Series, rule: str) -> None:
        nonlocal out
        out, count = drop_rows(out, mask, airport, mode, rule, audit_rows, stats)
        stats["manual_rows_dropped"] += count

    if airport == "HAN" and mode == "arrival":
        update(
            eq_upper_mask(out, "Flight_No", "VJ641"),
            {"Flight_No": "VJ164"},
            "manual_han_arr_vj641_to_vj164",
        )

        insert_exists = (
            eq_mask(out, "Crawl_Date", "2026-03-05")
            & eq_mask(out, "Actual_Time", "09:12")
            & eq_mask(out, "Flight_Time", "01:47")
            & eq_upper_mask(out, "Flight_No", "VU774")
            & eq_upper_mask(out, "Tail_Number", "9H-MLW")
        ).any()
        if not insert_exists:
            new_row = {col: pd.NA for col in out.columns}
            new_row.update(
                {
                    "Crawl_Date": "2026-03-05",
                    "Actual_Time": "09:12",
                    "Flight_Time": "01:47",
                    "Origin": "Ho Chi Minh City",
                    "IATA": "SGN",
                    "Airline": "Vietravel Airlines",
                    "Flight_No": "VU774",
                    "Terminal": "1",
                    "Arrival_Runway": "11L",
                    "Status": "Landed",
                    "Tail_Number": "9H-MLW",
                    "Aircraft_Type": "A320",
                    "Category": "passenger",
                }
            )
            insert_pos = min(21727, len(out))
            out = pd.concat(
                [out.iloc[:insert_pos], pd.DataFrame([new_row]), out.iloc[insert_pos:]],
                ignore_index=True,
            )
            stats["manual_rows_inserted"] += 1
            stats["manual_han_arr_vu774_inserted"] = 1
            audit_rows.append(
                {
                    "airport": airport,
                    "mode": mode,
                    "row_index": insert_pos,
                    "action": "insert",
                    "rule": "manual_han_arr_vu774_inserted",
                    "crawl_date": new_row.get("Crawl_Date", pd.NA),
                    "scheduled_time": new_row.get("Scheduled_Time", pd.NA),
                    "actual_time": new_row.get("Actual_Time", pd.NA),
                    "flight_no": new_row.get("Flight_No", pd.NA),
                    "iata": new_row.get("IATA", pd.NA),
                    "airline": new_row.get("Airline", pd.NA),
                    "tail_number": new_row.get("Tail_Number", pd.NA),
                    "aircraft_type": new_row.get("Aircraft_Type", pd.NA),
                    "category": new_row.get("Category", pd.NA),
                }
            )

        update(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Arrival_Runway", "11L")
            & eq_upper_mask(out, "Status", "Landed")
            & eq_upper_mask(out, "Tail_Number", "VN-B469")
            & eq_upper_mask(out, "Aircraft_Type", "C208")
            & eq_mask(out, "Category", "passenger"),
            {"Category": "unknown"},
            "manual_han_arr_vnb469_c208_passenger_to_unknown",
        )

        drop(
            eq_mask(out, "Crawl_Date", "2026-01-23")
            & eq_mask(out, "Actual_Time", "07:44")
            & missing_mask(out, "Flight_Time")
            & blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Arrival_Runway", "11L")
            & eq_upper_mask(out, "Status", "Landed")
            & blank_aircraft_identity_mask(out)
            & eq_mask(out, "Category", "unknown"),
            "manual_han_arr_drop_20260123_0744_empty_unknown",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_upper_mask(out, "Status", "Landed")
            & eq_mask(out, "Category", "unknown")
            & missing_mask(out, "Arrival_Runway")
            & blank_aircraft_identity_mask(out)
            & clean_series(out, "Terminal").isin(["1", "2"]),
            "manual_han_arr_drop_blank_landed_unknown",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-01-23")
            & eq_mask(out, "Actual_Time", "08:18")
            & missing_mask(out, "Flight_Time")
            & missing_mask(out, "Origin")
            & missing_mask(out, "IATA")
            & eq_upper_mask(out, "Airline", "VIETJET AIR")
            & missing_mask(out, "Flight_No")
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Arrival_Runway", "11L")
            & eq_upper_mask(out, "Status", "Landed")
            & missing_mask(out, "Tail_Number")
            & eq_upper_mask(out, "Aircraft_Type", "A321"),
            "manual_han_arr_drop_20260123_0818_vietjet_no_flight",
        )

    if airport == "SGN" and mode == "arrival":
        for flight_no, crawl_date, actual_time, new_tail in [
            ("VJ161", "2026-02-27", "02:12", "VN-A632"),
            ("VJ129", "2026-03-02", "13:51", "VN-A632"),
            ("VJ171", "2026-03-15", "01:21", "VN-A532"),
        ]:
            update(
                eq_mask(out, "Crawl_Date", crawl_date)
                & eq_mask(out, "Actual_Time", actual_time)
                & eq_upper_mask(out, "Flight_No", flight_no)
                & eq_upper_mask(out, "IATA", "HAN"),
                {"Tail_Number": new_tail},
                "manual_sgn_arr_han_sgn_swap_tail_override",
            )

        drop(
            eq_mask(out, "Crawl_Date", "2026-03-15")
            & eq_mask(out, "Actual_Time", "01:21")
            & eq_upper_mask(out, "Flight_No", "VJ171")
            & eq_upper_mask(out, "IATA", "HAN")
            & eq_upper_mask(out, "Tail_Number", "VN-A532"),
            "manual_sgn_arr_drop_remaining_swap_true_vj171",
        )

        drop(
            eq_mask(out, "Crawl_Date", "2026-01-24")
            & eq_mask(out, "Actual_Time", "17:48")
            & eq_mask(out, "Flight_Time", "01:49")
            & eq_upper_mask(out, "Flight_No", "VJ191")
            & eq_upper_mask(out, "Tail_Number", "VN-A672"),
            "manual_sgn_arr_drop_vj191_20260124",
        )
        update(
            eq_mask(out, "Crawl_Date", "2026-03-15")
            & eq_mask(out, "Actual_Time", "21:09")
            & eq_mask(out, "Flight_Time", "01:58")
            & eq_mask(out, "Category", "unknown"),
            {"Category": "general aviation"},
            "manual_sgn_arr_20260315_unknown_to_general_aviation",
        )
        special_20260315 = (
            eq_mask(out, "Crawl_Date", "2026-03-15")
            & eq_mask(out, "Actual_Time", "21:09")
            & eq_mask(out, "Flight_Time", "01:58")
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_upper_mask(out, "Status", "Landed")
            & eq_mask(out, "Category", "unknown")
            & missing_mask(out, "Arrival_Runway")
            & blank_aircraft_identity_mask(out)
            & clean_series(out, "Terminal").isin(["2", "3"])
            & ~special_20260315,
            "manual_sgn_arr_drop_blank_landed_unknown",
        )

    if airport == "DAD" and mode == "arrival":
        dad_replacements = [
            (
                {
                    "Crawl_Date": "2026-01-22",
                    "Scheduled_Time": "23:35",
                    "Actual_Time": "23:50",
                    "Flight_No": "TW13",
                },
                {
                    "Actual_Time": "23:55",
                    "Belt": "3.0",
                    "Status": "Arrived",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-09",
                    "Scheduled_Time": "00:20",
                    "Actual_Time": "23:50",
                    "Flight_No": "ZE593",
                },
                {
                    "Actual_Time": "00:32",
                    "Belt": "2.0",
                    "Status": "Arrived",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-12",
                    "Scheduled_Time": "22:45",
                    "Actual_Time": "23:50",
                    "Flight_No": "VJ640",
                },
                {"Actual_Time": "00:59"},
            ),
            (
                {
                    "Crawl_Date": "2026-02-13",
                    "Scheduled_Time": "22:00",
                    "Actual_Time": "00:28",
                    "Flight_No": "VJ646",
                },
                {
                    "Actual_Time": "00:23",
                    "Status": "Bags Delivered",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-13",
                    "Scheduled_Time": "22:40",
                    "Actual_Time": "23:10",
                    "Flight_No": "VN7122",
                },
                {
                    "Actual_Time": "00:29",
                    "Belt": "3.0",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-13",
                    "Scheduled_Time": "22:45",
                    "Actual_Time": "00:24",
                    "Flight_No": "VJ640",
                },
                {"Tail_Number": "VN-A649"},
            ),
            (
                {
                    "Crawl_Date": "2026-02-15",
                    "Scheduled_Time": "00:20",
                    "Actual_Time": "23:55",
                    "Flight_No": "ZE593",
                },
                {
                    "Actual_Time": "00:14",
                    "Belt": "4.0",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-24",
                    "Scheduled_Time": "23:40",
                    "Actual_Time": "00:00",
                    "Flight_No": "LJ183",
                },
                {
                    "Belt": "1.0",
                    "Status": "Arrived",
                },
            ),
            (
                {
                    "Crawl_Date": "2026-02-25",
                    "Scheduled_Time": "22:00",
                    "Actual_Time": "00:00",
                    "Flight_No": "VJ646",
                },
                {
                    "Scheduled_Time": "20:00",
                    "Actual_Time": "23:59",
                    "Status": "Bags Delivered",
                },
            ),
        ]
        for match_values, replacement_values in dad_replacements:
            mask = pd.Series(True, index=out.index)
            for col, value in match_values.items():
                mask = mask & eq_upper_mask(out, col, value) if col == "Flight_No" else mask & eq_mask(out, col, value)
            update(mask, replacement_values, "manual_dad_arr_targeted_time_status_fixes")

    if airport == "HAN" and mode == "departure":
        update(
            eq_upper_mask(out, "Aircraft_Type", "C208"),
            {"Category": "business jet"},
            "manual_han_dep_c208_to_business_jet",
        )

        conflicting_second_legs = [
            ("2026-02-18", "VN220", "20:41", "SGN"),
            ("2026-02-27", "VJ190", "21:16", "SGN"),
            ("2026-02-27", "9G868", "18:53", "SGN"),
            ("2026-03-08", "VU770", "14:03", "SGN"),
            ("2026-03-11", "VN270", "23:49", "SGN"),
            ("2026-03-11", "VJ188", "13:19", "SGN"),
            ("2026-03-11", "VJ146", "15:10", "DAD"),
        ]
        conflict_mask = pd.Series(False, index=out.index)
        for crawl_date, flight_no, actual_time, iata in conflicting_second_legs:
            conflict_mask = conflict_mask | (
                eq_mask(out, "Crawl_Date", crawl_date)
                & eq_upper_mask(out, "Flight_No", flight_no)
                & eq_mask(out, "Actual_Time", actual_time)
                & eq_upper_mask(out, "IATA", iata)
            )
        drop(conflict_mask, "manual_han_dep_drop_conflicting_second_leg")

        drop(
            eq_mask(out, "Crawl_Date", "2026-03-14")
            & eq_mask(out, "Actual_Time", "23:40")
            & eq_upper_mask(out, "Flight_No", "VJ171")
            & eq_upper_mask(out, "IATA", "SGN")
            & eq_upper_mask(out, "Tail_Number", "VN-A632"),
            "manual_han_dep_drop_remaining_swap_true_vj171",
        )

        update(
            eq_mask(out, "Crawl_Date", "2025-12-16")
            & eq_upper_mask(out, "Flight_No", "CZ8084")
            & eq_mask(out, "Actual_Time", "22:18"),
            {"Scheduled_Time": "22:00"},
            "manual_han_dep_20251216_schedule_fixes",
        )
        update(
            eq_mask(out, "Crawl_Date", "2025-12-16")
            & eq_upper_mask(out, "Flight_No", "9G895")
            & eq_mask(out, "Actual_Time", "22:15"),
            {"Scheduled_Time": "22:25"},
            "manual_han_dep_20251216_schedule_fixes",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-01-24")
            & eq_mask(out, "Scheduled_Time", "15:55")
            & eq_mask(out, "Actual_Time", "15:59")
            & eq_upper_mask(out, "Flight_No", "VJ191")
            & eq_upper_mask(out, "Tail_Number", "VN-A672"),
            "manual_han_dep_drop_vj191_20260124",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-03-16")
            & eq_mask(out, "Scheduled_Time", "23:25")
            & eq_mask(out, "Actual_Time", "23:31")
            & eq_upper_mask(out, "Flight_No", "VJ171")
            & eq_upper_mask(out, "Tail_Number", "VN-A536"),
            "manual_han_dep_drop_vj171_20260316",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-03-12")
            & eq_upper_mask(out, "Flight_No", "OK8903"),
            "manual_han_dep_drop_ok8903_20260312",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "11R")
            & eq_upper_mask(out, "Status", "Departed")
            & eq_upper_mask(out, "Tail_Number", "VN-B469")
            & eq_upper_mask(out, "Aircraft_Type", "C208"),
            "manual_han_dep_drop_blank_vnb469_c208",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "0")
            & missing_mask(out, "Departure_Runway")
            & eq_upper_mask(out, "Status", "Departed")
            & blank_aircraft_identity_mask(out)
            & eq_mask(out, "Is_Fixed_Flight", "0")
            & eq_mask(out, "Category", "military or government"),
            "manual_han_dep_drop_blank_military",
        )
        drop(
            eq_upper_mask(out, "Flight_No", "OK8903")
            & eq_mask(out, "Terminal", "0")
            & missing_mask(out, "Departure_Runway")
            & eq_upper_mask(out, "Status", "Departed")
            & blank_aircraft_identity_mask(out)
            & eq_mask(out, "Is_Fixed_Flight", "0")
            & eq_mask(out, "Category", "military or government"),
            "manual_han_dep_drop_ok8903_blank_military",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "11R")
            & eq_upper_mask(out, "Status", "Departed")
            & eq_upper_mask(out, "Tail_Number", "VN-A363")
            & eq_upper_mask(out, "Aircraft_Type", "A321"),
            "manual_han_dep_drop_blank_vna363_a321",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-01-27")
            & eq_mask(out, "Actual_Time", "06:45")
            & eq_upper_mask(out, "Flight_No", "OK8902")
            & eq_mask(out, "Category", "military or government"),
            "manual_han_dep_drop_ok8902_20260127",
        )
        vnb469_dates = {
            "2026-02-01",
            "2026-02-03",
            "2026-02-06",
            "2026-02-07",
            "2026-02-08",
            "2026-02-09",
            "2026-02-12",
            "2026-02-20",
            "2026-02-25",
            "2026-02-26",
            "2026-02-28",
            "2026-03-04",
            "2026-03-10",
            "2026-03-11",
            "2026-03-12",
            "2026-03-14",
        }
        drop(
            clean_series(out, "Crawl_Date").isin(vnb469_dates)
            & eq_upper_mask(out, "Tail_Number", "VN-B469")
            & eq_upper_mask(out, "Aircraft_Type", "C208"),
            "manual_han_dep_drop_vnb469_c208_target_dates",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-02-12")
            & eq_mask(out, "Actual_Time", "15:06")
            & blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "29L")
            & eq_upper_mask(out, "Status", "Departed")
            & blank_aircraft_identity_mask(out)
            & eq_mask(out, "Category", "unknown"),
            "manual_han_dep_drop_20260212_1506_unknown",
        )

    if airport == "SGN" and mode == "departure":
        update(
            eq_mask(out, "Crawl_Date", "2026-02-23")
            & eq_mask(out, "Actual_Time", "20:38")
            & eq_upper_mask(out, "Flight_No", "VJ196")
            & eq_upper_mask(out, "IATA", "HAN"),
            {"Tail_Number": "VN-A816"},
            "manual_sgn_dep_han_arr_swap_tail_override",
        )
        update(
            eq_mask(out, "Crawl_Date", "2026-02-25")
            & eq_mask(out, "Actual_Time", "01:32")
            & eq_upper_mask(out, "Flight_No", "VJ174")
            & eq_upper_mask(out, "IATA", "HAN")
            & eq_upper_mask(out, "Tail_Number", "VN-A545"),
            {"Tail_Number": "VN-A687", "Aircraft_Type": "A321"},
            "manual_sgn_dep_han_arr_swap_tail_override",
        )

        update(
            eq_mask(out, "Crawl_Date", "2026-03-03")
            & eq_upper_mask(out, "Flight_No", "VU774")
            & eq_mask(out, "Actual_Time", "07:51"),
            {"Departure_Runway": "25L"},
            "manual_sgn_dep_vu774_runway_25l",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "25L")
            & eq_upper_mask(out, "Status", "Departed")
            & eq_upper_mask(out, "Tail_Number", "VN-A359")
            & eq_upper_mask(out, "Aircraft_Type", "A321")
            & eq_mask(out, "Category", "passenger"),
            "manual_sgn_dep_drop_blank_vna359_a321",
        )
        drop(
            blank_route_identity_mask(out, mode)
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "25L")
            & eq_upper_mask(out, "Status", "Departed")
            & eq_upper_mask(out, "Tail_Number", "VN-A354")
            & eq_upper_mask(out, "Aircraft_Type", "A321")
            & eq_mask(out, "Category", "passenger"),
            "manual_sgn_dep_drop_blank_vna354_a321",
        )
        drop(
            missing_mask(out, "Destination")
            & missing_mask(out, "IATA")
            & eq_upper_mask(out, "Airline", "SUN PHUQUOC AIRWAYS")
            & missing_mask(out, "Flight_No")
            & eq_mask(out, "Terminal", "2")
            & eq_upper_mask(out, "Departure_Runway", "25L")
            & eq_upper_mask(out, "Status", "Departed"),
            "manual_sgn_dep_drop_blank_sun_phuquoc",
        )
        drop(
            eq_mask(out, "Crawl_Date", "2026-01-23")
            & eq_mask(out, "Actual_Time", "06:50")
            & missing_mask(out, "Destination")
            & missing_mask(out, "IATA")
            & eq_upper_mask(out, "Airline", "VASCO")
            & missing_mask(out, "Flight_No")
            & eq_upper_mask(out, "Aircraft_Type", "AT75")
            & eq_mask(out, "Category", "unknown"),
            "manual_sgn_dep_drop_20260123_vasco_unknown",
        )

    return out.reset_index(drop=True), stats, audit_rows


def flight_key_value(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def clock_key_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    match = pd.Series([text]).str.extract(r"(\d{1,2}:\d{2})", expand=False).iloc[0]
    if pd.isna(match):
        return ""
    hour, minute = str(match).split(":")
    return f"{int(hour):02d}:{minute}"


def fill_missing_is_fixed_flight(df: pd.DataFrame) -> Dict[str, int]:
    if "Is_Fixed_Flight" not in df.columns or "Scheduled_Time" not in df.columns:
        return {
            "is_fixed_flight_normalized_existing": 0,
            "is_fixed_flight_missing_before": 0,
            "is_fixed_flight_filled_one": 0,
            "is_fixed_flight_filled_zero": 0,
            "is_fixed_flight_missing_after": 0,
        }

    raw_fixed = df["Is_Fixed_Flight"].astype("string").str.strip()
    missing_before = raw_fixed.isna() | raw_fixed.str.lower().isin(NA_TOKENS)
    normalized_existing = raw_fixed.str.lower().replace({"0.0": "0", "1.0": "1"})
    normalize_existing_mask = (
        ~missing_before
        & normalized_existing.isin(["0", "1"])
        & raw_fixed.ne(normalized_existing)
    )
    df.loc[normalize_existing_mask, "Is_Fixed_Flight"] = normalized_existing.loc[normalize_existing_mask]

    if not missing_before.any():
        return {
            "is_fixed_flight_normalized_existing": int(normalize_existing_mask.sum()),
            "is_fixed_flight_missing_before": 0,
            "is_fixed_flight_filled_one": 0,
            "is_fixed_flight_filled_zero": 0,
            "is_fixed_flight_missing_after": 0,
        }

    flight_key = (
        df["Flight_No"].map(flight_key_value)
        if "Flight_No" in df.columns
        else pd.Series("", index=df.index, dtype="string")
    )
    route_key = (
        df["IATA"].map(flight_key_value)
        if "IATA" in df.columns
        else pd.Series("", index=df.index, dtype="string")
    )
    scheduled_clock = df["Scheduled_Time"].map(clock_key_value)
    service_date = (
        df["Crawl_Date"].astype("string").str.strip().str[:10]
        if "Crawl_Date" in df.columns
        else pd.Series("", index=df.index, dtype="string")
    )

    key_df = pd.DataFrame(
        {
            "flight_key": flight_key,
            "route_key": route_key,
            "scheduled_clock": scheduled_clock,
            "service_date": service_date,
        },
        index=df.index,
    )
    valid_key = (
        key_df["flight_key"].ne("")
        & key_df["route_key"].ne("")
        & key_df["scheduled_clock"].ne("")
        & key_df["service_date"].ne("")
    )

    fixed_groups = (
        key_df.loc[valid_key]
        .groupby(["flight_key", "route_key", "scheduled_clock"], dropna=False)["service_date"]
        .nunique()
    )
    fixed_keys = set(fixed_groups[fixed_groups >= 2].index)

    row_keys = list(
        zip(
            key_df["flight_key"],
            key_df["route_key"],
            key_df["scheduled_clock"],
        )
    )
    is_fixed = pd.Series([key in fixed_keys for key in row_keys], index=df.index)
    fill_one = missing_before & valid_key & is_fixed
    fill_zero = missing_before & ~fill_one

    df.loc[fill_one, "Is_Fixed_Flight"] = "1"
    df.loc[fill_zero, "Is_Fixed_Flight"] = "0"

    raw_after = df["Is_Fixed_Flight"].astype("string").str.strip()
    missing_after = raw_after.isna() | raw_after.str.lower().isin(NA_TOKENS)
    return {
        "is_fixed_flight_normalized_existing": int(normalize_existing_mask.sum()),
        "is_fixed_flight_missing_before": int(missing_before.sum()),
        "is_fixed_flight_filled_one": int(fill_one.sum()),
        "is_fixed_flight_filled_zero": int(fill_zero.sum()),
        "is_fixed_flight_missing_after": int(missing_after.sum()),
    }


def merge_patched_arrivals(project_root: Path, output_dir: Path) -> Tuple[List[Dict[str, object]], Dict[Tuple[str, str], Dict[str, int]]]:
    patch_path = project_root / "Data crawl" / "final_merged_patched_flights.csv"
    audit_rows: List[Dict[str, object]] = []
    stats: Dict[Tuple[str, str], Dict[str, int]] = {}
    airports = {"SGN", "HAN", "DAD"}

    if not patch_path.exists():
        return audit_rows, stats

    patch_df = pd.read_csv(patch_path, dtype=str)
    if patch_df.empty:
        return audit_rows, stats

    dep_lookup: Dict[Tuple[str, str, str], Set[str]] = {}
    for origin in airports:
        dep_path = output_dir / "Departure" / f"{origin.lower()}_flights_departure_bronze_layer.csv"
        if not dep_path.exists():
            continue
        dep_df = pd.read_csv(dep_path, dtype=str)
        for _, row in dep_df.iterrows():
            crawl_date = str(row.get("Crawl_Date", "")).strip()[:10]
            flight_no = flight_key_value(row.get("Flight_No"))
            dest = flight_key_value(row.get("IATA"))
            if not crawl_date or not flight_no or dest not in airports:
                continue
            dep_lookup.setdefault((origin, crawl_date, flight_no), set()).add(dest)

    arrival_frames: Dict[str, pd.DataFrame] = {}
    existing_keys: Dict[str, Set[Tuple[str, str, str, str]]] = {}
    for airport in airports:
        arr_path = output_dir / "Arrival" / f"{airport.lower()}_flights_arrival_bronze_layer.csv"
        if not arr_path.exists():
            continue
        arr_df = pd.read_csv(arr_path, dtype=str)
        arrival_frames[airport] = arr_df
        keys: Set[Tuple[str, str, str, str]] = set()
        for _, row in arr_df.iterrows():
            keys.add(
                (
                    str(row.get("Crawl_Date", "")).strip()[:10],
                    flight_key_value(row.get("Flight_No")),
                    flight_key_value(row.get("IATA")),
                    clock_key_value(row.get("Actual_Time")),
                )
            )
        existing_keys[airport] = keys

    for patch_idx, row in patch_df.iterrows():
        origin = flight_key_value(row.get("IATA"))
        crawl_date = str(row.get("Crawl_Date", "")).strip()[:10]
        flight_no = flight_key_value(row.get("Flight_No"))
        lookup_key = (origin, crawl_date, flight_no)
        dests = dep_lookup.get(lookup_key, set())

        audit_base = {
            "patch_row_index": int(patch_idx),
            "origin_airport": origin,
            "crawl_date": crawl_date,
            "flight_no": flight_no,
            "actual_time": row.get("Actual_Time", pd.NA),
            "scheduled_time": row.get("Scheduled_Time", pd.NA),
        }

        if origin not in airports:
            audit_rows.append({**audit_base, "target_airport": pd.NA, "status": "skipped_unknown_origin"})
            continue
        if len(dests) == 0:
            audit_rows.append({**audit_base, "target_airport": pd.NA, "status": "skipped_no_departure_match"})
            continue
        if len(dests) > 1:
            audit_rows.append({**audit_base, "target_airport": ",".join(sorted(dests)), "status": "skipped_ambiguous_destination"})
            continue

        target_airport = next(iter(dests))
        arr_df = arrival_frames.get(target_airport)
        if arr_df is None:
            audit_rows.append({**audit_base, "target_airport": target_airport, "status": "skipped_missing_target_file"})
            continue

        row_key = (
            crawl_date,
            flight_no,
            origin,
            clock_key_value(row.get("Actual_Time")),
        )
        if row_key in existing_keys[target_airport]:
            audit_rows.append({**audit_base, "target_airport": target_airport, "status": "skipped_duplicate"})
            continue

        new_row = {col: pd.NA for col in arr_df.columns}
        for col in ["Crawl_Date", "Actual_Time", "Origin", "IATA", "Airline", "Flight_No", "Terminal", "Arrival_Runway", "Status", "Aircraft_Type", "Category"]:
            if col in new_row:
                new_row[col] = row.get(col, pd.NA)
        if "Scheduled_Time" in new_row:
            new_row["Scheduled_Time"] = row.get("Scheduled_Time", pd.NA)
        if "Tail_Number" in new_row:
            new_row["Tail_Number"] = row.get("Actual_Tail", pd.NA)
        if "Actual_Tail" in new_row:
            new_row["Actual_Tail"] = row.get("Actual_Tail", pd.NA)
        if "Belt" in new_row:
            new_row["Belt"] = pd.NA

        arr_df.loc[len(arr_df)] = new_row
        existing_keys[target_airport].add(row_key)
        stats.setdefault((target_airport, "arrival"), {"patched_arrivals_inserted": 0, "patched_arrivals_skipped": 0})
        stats[(target_airport, "arrival")]["patched_arrivals_inserted"] += 1
        audit_rows.append({**audit_base, "target_airport": target_airport, "status": "inserted"})

    for airport, arr_df in arrival_frames.items():
        arr_path = output_dir / "Arrival" / f"{airport.lower()}_flights_arrival_bronze_layer.csv"
        arr_df.to_csv(arr_path, index=False)

    for audit in audit_rows:
        target = audit.get("target_airport")
        if target in airports:
            stats.setdefault((str(target), "arrival"), {"patched_arrivals_inserted": 0, "patched_arrivals_skipped": 0})
            if audit.get("status") != "inserted":
                stats[(str(target), "arrival")]["patched_arrivals_skipped"] += 1

    return audit_rows, stats


def merge_patched_departures(project_root: Path, output_dir: Path) -> Tuple[List[Dict[str, object]], Dict[Tuple[str, str], Dict[str, int]]]:
    patch_path = project_root / "Data crawl" / "valid_patched_flights.csv"
    audit_rows: List[Dict[str, object]] = []
    stats: Dict[Tuple[str, str], Dict[str, int]] = {}
    airports = {"SGN", "HAN", "DAD"}

    if not patch_path.exists():
        return audit_rows, stats

    patch_df = pd.read_csv(patch_path, dtype=str)
    if patch_df.empty:
        return audit_rows, stats

    departure_frames: Dict[str, pd.DataFrame] = {}
    existing_keys: Dict[str, Set[Tuple[str, str, str, str, str]]] = {}
    for airport in airports:
        dep_path = output_dir / "Departure" / f"{airport.lower()}_flights_departure_bronze_layer.csv"
        if not dep_path.exists():
            continue
        dep_df = pd.read_csv(dep_path, dtype=str)
        departure_frames[airport] = dep_df
        keys: Set[Tuple[str, str, str, str, str]] = set()
        for _, row in dep_df.iterrows():
            keys.add(
                (
                    str(row.get("Crawl_Date", "")).strip()[:10],
                    flight_key_value(row.get("Flight_No")),
                    flight_key_value(row.get("IATA")),
                    clock_key_value(row.get("Scheduled_Time")),
                    clock_key_value(row.get("Actual_Time")),
                )
            )
        existing_keys[airport] = keys

    def infer_departure_airport(dest_airport: str) -> str:
        # The current patched departure file covers the SGN<->HAN missing-departure cases.
        if dest_airport == "HAN":
            return "SGN"
        if dest_airport == "SGN":
            return "HAN"
        return ""

    for patch_idx, row in patch_df.iterrows():
        dest_airport = flight_key_value(row.get("IATA"))
        origin_airport = infer_departure_airport(dest_airport)
        crawl_date = str(row.get("Crawl_Date", "")).strip()[:10]
        flight_no = flight_key_value(row.get("Flight_No"))

        audit_base = {
            "patch_row_index": int(patch_idx),
            "origin_airport": origin_airport or pd.NA,
            "destination_airport": dest_airport,
            "crawl_date": crawl_date,
            "flight_no": flight_no,
            "scheduled_time": row.get("Scheduled_Time", pd.NA),
            "actual_time": row.get("Actual_Time", pd.NA),
        }

        if dest_airport not in airports or not origin_airport:
            audit_rows.append({**audit_base, "status": "skipped_unknown_route"})
            continue

        dep_df = departure_frames.get(origin_airport)
        if dep_df is None:
            audit_rows.append({**audit_base, "status": "skipped_missing_origin_file"})
            continue

        row_key = (
            crawl_date,
            flight_no,
            dest_airport,
            clock_key_value(row.get("Scheduled_Time")),
            clock_key_value(row.get("Actual_Time")),
        )
        if row_key in existing_keys[origin_airport]:
            audit_rows.append({**audit_base, "status": "skipped_duplicate"})
            continue

        new_row = {col: pd.NA for col in dep_df.columns}
        for col in [
            "Crawl_Date",
            "Scheduled_Time",
            "Actual_Time",
            "Destination",
            "IATA",
            "Airline",
            "Flight_No",
            "Terminal",
            "Departure_Runway",
            "Status",
            "Tail_Number",
            "Aircraft_Type",
            "Is_Fixed_Flight",
            "Category",
        ]:
            if col in new_row:
                new_row[col] = row.get(col, pd.NA)

        dep_df.loc[len(dep_df)] = new_row
        existing_keys[origin_airport].add(row_key)
        stats.setdefault((origin_airport, "departure"), {"patched_departures_inserted": 0, "patched_departures_skipped": 0})
        stats[(origin_airport, "departure")]["patched_departures_inserted"] += 1
        audit_rows.append({**audit_base, "status": "inserted"})

    for airport, dep_df in departure_frames.items():
        dep_path = output_dir / "Departure" / f"{airport.lower()}_flights_departure_bronze_layer.csv"
        dep_df.to_csv(dep_path, index=False)

    for audit in audit_rows:
        origin = audit.get("origin_airport")
        if origin in airports:
            stats.setdefault((str(origin), "departure"), {"patched_departures_inserted": 0, "patched_departures_skipped": 0})
            if audit.get("status") != "inserted":
                stats[(str(origin), "departure")]["patched_departures_skipped"] += 1

    return audit_rows, stats


def normalize_na_tokens(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    for col in cleaned.columns:
        if pd.api.types.is_object_dtype(cleaned[col]) or pd.api.types.is_string_dtype(cleaned[col]):
            series = cleaned[col].astype("string").str.strip()
            series = series.mask(series.str.lower().isin(NA_TOKENS))
            cleaned[col] = series
    return cleaned


def clean_dataframe(
    df: pd.DataFrame,
    airport: str,
    mode: str,
) -> Tuple[pd.DataFrame, Dict[str, int], List[Dict[str, object]], List[Dict[str, object]]]:
    out = normalize_na_tokens(df)
    dad_stats = apply_dad_specific_value_fixes(out, airport=airport)
    spq_audit_rows, spq_stats = normalize_spq_flight_number(out, airport=airport, mode=mode)
    out, manual_stats, manual_audit_rows = apply_targeted_manual_fixes(out, airport=airport, mode=mode)
    stats = {
        **dad_stats,
        **spq_stats,
        **manual_stats,
        "airline_values_changed": normalize_airline_values(out),
        "category_values_changed": normalize_category_unknown(out),
        "terminal_values_changed": normalize_terminal_values(out, airport=airport, mode=mode),
        "thd_route_name_changed": apply_route_name_fixes(out, mode=mode),
        "dad_belt_general_aviation_changed": apply_dad_arrival_belt_category_rule(
            out,
            airport=airport,
            mode=mode,
        ),
        **fill_missing_is_fixed_flight(out),
    }
    return out, stats, spq_audit_rows, manual_audit_rows


def clean_layer(project_root: Path, input_layer: str, output_layer: str) -> pd.DataFrame:
    input_dir = project_root / "Data crawl" / input_layer
    output_dir = project_root / "Data crawl" / output_layer
    summary_rows = []
    spq_audit_rows: List[Dict[str, object]] = []
    manual_audit_rows: List[Dict[str, object]] = []

    for mode in ("arrival", "departure"):
        src_subdir = input_dir / mode.capitalize()
        dst_subdir = output_dir / mode.capitalize()
        dst_subdir.mkdir(parents=True, exist_ok=True)

        for airport in ("sgn", "han", "dad"):
            src_name = f"{airport}_flights_{mode}_{input_layer.lower()}.csv"
            src_path = src_subdir / src_name
            if not src_path.exists() and input_layer == "Bronze_layer":
                src_name = f"{airport}_flights_{mode}_bronze_layer.csv"
                src_path = src_subdir / src_name
            if not src_path.exists():
                raise FileNotFoundError(f"Missing input file: {src_path}")

            df = pd.read_csv(src_path, dtype=str)
            cleaned, stats, file_spq_audit_rows, file_manual_audit_rows = clean_dataframe(
                df,
                airport=airport.upper(),
                mode=mode,
            )
            cleaned, flight_time_dropped = drop_han_sgn_arrival_flight_time(
                cleaned,
                airport=airport.upper(),
                mode=mode,
            )
            stats["arrival_flight_time_raw_dropped"] = flight_time_dropped
            spq_audit_rows.extend(file_spq_audit_rows)
            manual_audit_rows.extend(file_manual_audit_rows)

            dst_name = f"{airport}_flights_{mode}_bronze_layer.csv"
            dst_path = dst_subdir / dst_name
            cleaned.to_csv(dst_path, index=False)

            summary_rows.append(
                {
                    "Airport": airport.upper(),
                    "Mode": mode,
                    "rows_input": len(df),
                    "rows_output": len(cleaned),
                    **stats,
                }
            )

    patched_arrival_audit_rows, patched_arrival_stats = merge_patched_arrivals(project_root, output_dir)
    patched_departure_audit_rows, patched_departure_stats = merge_patched_departures(project_root, output_dir)
    for row in summary_rows:
        key = (str(row["Airport"]), str(row["Mode"]))
        if key in patched_arrival_stats:
            row.update(patched_arrival_stats[key])
        if key in patched_departure_stats:
            row.update(patched_departure_stats[key])
        output_file = (
            output_dir
            / str(row["Mode"]).capitalize()
            / f"{str(row['Airport']).lower()}_flights_{str(row['Mode'])}_bronze_layer.csv"
        )
        if output_file.exists():
            row["rows_output"] = len(pd.read_csv(output_file, dtype=str))

    summary_df = pd.DataFrame(summary_rows)
    audit_dir = output_dir / "Audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(audit_dir / "clean_summary.csv", index=False)
    pd.DataFrame(spq_audit_rows).to_csv(audit_dir / "audit_flight_no_spq_to_9g.csv", index=False)
    pd.DataFrame(manual_audit_rows).to_csv(audit_dir / "audit_manual_value_fixes.csv", index=False)
    pd.DataFrame(patched_arrival_audit_rows).to_csv(audit_dir / "audit_patched_arrival_merge.csv", index=False)
    pd.DataFrame(patched_departure_audit_rows).to_csv(audit_dir / "audit_patched_departure_merge.csv", index=False)
    return summary_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean direct value fixes for a data layer.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing Data crawl/.",
    )
    parser.add_argument("--input-layer", default="Bronze_layer")
    parser.add_argument("--output-layer", default="Bronze_layer_cleaned")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = clean_layer(args.project_root, args.input_layer, args.output_layer)
    print("=" * 72)
    print("Layer cleaning completed")
    print(f"Project root: {args.project_root}")
    print(f"Input layer: {args.input_layer}")
    print(f"Output layer: {args.output_layer}")
    print(summary.to_string(index=False))
    print("=" * 72)


if __name__ == "__main__":
    main()
