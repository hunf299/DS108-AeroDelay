import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


# Airport mappings
AIRPORT_CODE_MAP: Dict[str, str] = {
    "tan_son_nhat": "SGN",
    "noi_bai": "HAN",
    "da_nang": "DAD",
}

# Default runway heading (magnetic, degrees) for crosswind calc.
# Runway number x 10 = heading. e.g., 25L -> 250 degrees
DEFAULT_RUNWAY_HEADING: Dict[str, float] = {
    "SGN": 250.0,  # default 25L/25R
    "HAN": 110.0,  # default 11L/11R
    "DAD": 350.0,  # default 35L/35R
}

# Thresholds (aviation-oriented)
KMH_PER_KT = 1.852
RAIN_HEAVY_MM_H = 5.0
WIND_STRONG_KMH = 30.0
WIND_GALE_KMH = 50.0
VIS_LOW_M = 5000.0
VIS_FOG_M = 1000.0
VIS_3SM_M = 3 * 1609.344
VIS_1SM_M = 1609.344
CROSSWIND_CAUTION_KT = 10.0
CROSSWIND_MODERATE_KT = 15.0
CROSSWIND_HIGH_KT = 20.0
HUMIDITY_FOG_PCT = 90.0
FREEZING_TEMP_C = 5.0
HOT_TEMP_C = 35.0
DEFAULT_SILVER_LAYER_NAME = "Silver_layer"

NUMERIC_WEATHER_COLS = [
    "temperature",
    "precipitation",
    "cloudcover",
    "wind_speed",
    "wind_direction",
    "pressure",
    "humidity",
    "visibility",
    "dew_point_2m",
    "weather_code",
    "cape",
    "lifted_index",
    "cloud_cover_low",
]

NO_IQR_CLIP_COLS = {
    "precipitation",
    "wind_speed",
    "visibility",
    "weather_code",
    "cape",
    "lifted_index",
}

CATEGORICAL_NUMERIC_COLS = {"weather_code"}

PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "temperature": (-10.0, 50.0),
    "precipitation": (0.0, 300.0),
    "cloudcover": (0.0, 100.0),
    "wind_speed": (0.0, 180.0),
    "wind_direction": (0.0, 360.0),
    "pressure": (850.0, 1100.0),
    "humidity": (0.0, 100.0),
    "visibility": (0.0, 50000.0),
    "dew_point_2m": (-20.0, 40.0),
    "weather_code": (0.0, 99.0),
    "cape": (0.0, 8000.0),
    "lifted_index": (-20.0, 20.0),
    "cloud_cover_low": (0.0, 100.0),
}


def load_bronze_weather(project_root: Path) -> pd.DataFrame:
    """Load raw merged weather CSV from Bronze layer."""
    bronze_path = (
        project_root / "Data" / "Bronze_layer" / "airport_weather_hourly_merged.csv"
    )
    if not bronze_path.exists():
        raise FileNotFoundError(f"Missing bronze weather file: {bronze_path}")

    df = pd.read_csv(bronze_path, dtype=str)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    # Map airport names -> IATA codes
    df["Airport"] = df["airport"].astype("string").str.lower().map(AIRPORT_CODE_MAP)

    # Cast numeric columns
    for col in NUMERIC_WEATHER_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Sort for rolling windows
    df = df.sort_values(["Airport", "time"]).reset_index(drop=True)
    return df


def audit_weather_quality(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Create missing and outlier EDA audit tables before cleaning."""
    missing_rows: List[Dict[str, object]] = []
    outlier_rows: List[Dict[str, object]] = []

    group_cols = ["Airport"] if "Airport" in df.columns else []
    for airport, grp in df.groupby(group_cols, dropna=False) if group_cols else [("ALL", df)]:
        airport_label = airport[0] if isinstance(airport, tuple) else airport
        for col in ["time", "Airport", *NUMERIC_WEATHER_COLS]:
            if col not in grp.columns:
                continue
            missing_rows.append(
                {
                    "Airport": airport_label,
                    "Column": col,
                    "Rows": len(grp),
                    "Missing_Count": int(grp[col].isna().sum()),
                    "Missing_Rate": round(float(grp[col].isna().mean()), 6),
                }
            )

        for col in NUMERIC_WEATHER_COLS:
            if col not in grp.columns:
                continue
            values = grp[col]
            lower, upper = PHYSICAL_BOUNDS[col]
            physical_mask = values.notna() & ((values < lower) | (values > upper))

            valid_values = values.dropna()
            iqr_mask = pd.Series(False, index=grp.index)
            iqr_lower = np.nan
            iqr_upper = np.nan
            if len(valid_values) >= 8:
                q1 = valid_values.quantile(0.25)
                q3 = valid_values.quantile(0.75)
                iqr = q3 - q1
                if pd.notna(iqr) and iqr > 0:
                    iqr_lower = q1 - 3.0 * iqr
                    iqr_upper = q3 + 3.0 * iqr
                    iqr_mask = values.notna() & ((values < iqr_lower) | (values > iqr_upper))

            combined_mask = physical_mask | iqr_mask
            for idx in grp.loc[combined_mask].index:
                outlier_rows.append(
                    {
                        "Airport": airport_label,
                        "Row_Index": int(idx),
                        "Time": df.at[idx, "time"] if "time" in df.columns else pd.NaT,
                        "Column": col,
                        "Value": df.at[idx, col],
                        "Physical_Lower": lower,
                        "Physical_Upper": upper,
                        "IQR_Lower": iqr_lower,
                        "IQR_Upper": iqr_upper,
                        "Is_Physical_Outlier": bool(physical_mask.at[idx]),
                        "Is_IQR_Outlier": bool(iqr_mask.at[idx]),
                    }
                )

    return pd.DataFrame(missing_rows), pd.DataFrame(outlier_rows)


def clean_weather_values(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Clip physically invalid values and impute missing hourly weather by airport.

    Event variables such as precipitation, wind speed, and visibility are not
    IQR-clipped because rare extremes are operational signals for aviation EDA.
    """
    out = df.copy()
    action_rows: List[Dict[str, object]] = []

    out = out.dropna(subset=["time", "Airport"]).copy()
    out = out.sort_values(["Airport", "time"]).reset_index(drop=True)

    for col in NUMERIC_WEATHER_COLS:
        if col not in out.columns:
            continue

        before_missing = int(out[col].isna().sum())
        lower, upper = PHYSICAL_BOUNDS[col]
        physical_low = out[col].notna() & (out[col] < lower)
        physical_high = out[col].notna() & (out[col] > upper)
        out.loc[physical_low, col] = lower
        out.loc[physical_high, col] = upper

        iqr_clipped = 0
        if col not in NO_IQR_CLIP_COLS and col not in CATEGORICAL_NUMERIC_COLS:
            for airport, idx in out.groupby("Airport").groups.items():
                values = out.loc[idx, col]
                valid_values = values.dropna()
                if len(valid_values) < 8:
                    continue
                q1 = valid_values.quantile(0.25)
                q3 = valid_values.quantile(0.75)
                iqr = q3 - q1
                if pd.isna(iqr) or iqr <= 0:
                    continue
                iqr_lower = max(q1 - 3.0 * iqr, lower)
                iqr_upper = min(q3 + 3.0 * iqr, upper)
                clipped = values.clip(lower=iqr_lower, upper=iqr_upper)
                iqr_clipped += int((values.notna() & (values != clipped)).sum())
                out.loc[idx, col] = clipped

        if col in CATEGORICAL_NUMERIC_COLS:
            out[col] = out.groupby("Airport", group_keys=False)[col].apply(lambda s: s.ffill().bfill())
            mode = out[col].mode(dropna=True)
            fill_value = mode.iloc[0] if not mode.empty else 0
            out[col] = out[col].fillna(fill_value).round()
        else:
            out[col] = (
                out.groupby("Airport", group_keys=False)[col]
                .apply(lambda s: s.interpolate(method="linear", limit_direction="both"))
            )
            out[col] = out.groupby("Airport")[col].transform(lambda s: s.fillna(s.median()))
            out[col] = out[col].fillna(out[col].median())

        after_missing = int(out[col].isna().sum())
        action_rows.append(
            {
                "Column": col,
                "Missing_Before": before_missing,
                "Missing_After": after_missing,
                "Physical_Low_Clipped": int(physical_low.sum()),
                "Physical_High_Clipped": int(physical_high.sum()),
                "IQR_Clipped": iqr_clipped,
            }
        )

    return out, pd.DataFrame(action_rows)


def compute_wind_components(df: pd.DataFrame) -> pd.DataFrame:
    """Add crosswind and headwind components relative to default runway heading."""
    out = df.copy()
    wind_dir = out["wind_direction"].mod(360.0)

    for airport, heading in DEFAULT_RUNWAY_HEADING.items():
        mask = out["Airport"] == airport
        if not mask.any():
            continue
        angle_diff = np.radians(wind_dir.loc[mask] - heading)
        ws = out.loc[mask, "wind_speed"]
        out.loc[mask, "Crosswind_Kmh"] = np.abs(ws * np.sin(angle_diff))
        out.loc[mask, "Headwind_Kmh"] = ws * np.cos(angle_diff)
        relative_angle = np.degrees(np.arccos(np.clip(np.cos(angle_diff), -1.0, 1.0)))
        out.loc[mask, "Wind_Runway_Relative_Angle_Deg"] = relative_angle

    out["Wind_Kt"] = out["wind_speed"] / KMH_PER_KT
    out["Crosswind_Kt"] = out["Crosswind_Kmh"] / KMH_PER_KT
    out["Headwind_Kt"] = out["Headwind_Kmh"] / KMH_PER_KT
    out["Tailwind_Default_Runway_Kmh"] = (-out["Headwind_Kmh"]).clip(lower=0.0)
    out["Tailwind_Default_Runway_Kt"] = out["Tailwind_Default_Runway_Kmh"] / KMH_PER_KT
    out["Wind_Sector"] = pd.cut(
        wind_dir,
        bins=[0, 22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5, 360],
        labels=["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"],
        include_lowest=True,
        ordered=False,
    ).astype("string")
    out["Is_Tailwind_Default_Runway_5kt"] = out["Tailwind_Default_Runway_Kt"] >= 5.0

    return out


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create aviation-relevant weather features."""
    out = df.copy()
    out = out.sort_values(["Airport", "time"]).reset_index(drop=True)

    def rolling_by_airport(col: str, periods: int, agg: str) -> pd.Series:
        return (
            out.groupby("Airport")[col]
            .transform(lambda s: s.rolling(periods, min_periods=1).agg(agg))
        )

    # --- Temporal aggregates ---
    out["Temp_Change_1H_C"] = out.groupby("Airport")["temperature"].diff(periods=1)
    out["Temp_Change_3H_C"] = out.groupby("Airport")["temperature"].diff(periods=3)
    out["Pressure_Change_3H_Hpa"] = out.groupby("Airport")["pressure"].diff(periods=3)

    out["Precip_Cumsum_1H_Mm"] = rolling_by_airport("precipitation", 1, "sum")
    out["Precip_Cumsum_3H_Mm"] = rolling_by_airport("precipitation", 3, "sum")
    out["Precip_Cumsum_6H_Mm"] = rolling_by_airport("precipitation", 6, "sum")

    out["Wind_Gust_Estimate_Kmh"] = rolling_by_airport("wind_speed", 3, "max")
    out["Crosswind_Max_3H_Kmh"] = rolling_by_airport("Crosswind_Kmh", 3, "max")
    out["Wind_Gust_Estimate_Kt"] = out["Wind_Gust_Estimate_Kmh"] / KMH_PER_KT
    out["Crosswind_Max_3H_Kt"] = out["Crosswind_Max_3H_Kmh"] / KMH_PER_KT
    out["Gust_Variation_Kmh"] = (out["Wind_Gust_Estimate_Kmh"] - out["wind_speed"]).clip(lower=0.0)
    out["Gust_Variation_Kt"] = out["Gust_Variation_Kmh"] / KMH_PER_KT
    out["Visibility_SM"] = out["visibility"] / 1609.344
    out["Visibility_Deficit_5KM_M"] = (VIS_LOW_M - out["visibility"]).clip(lower=0.0)
    out["Visibility_Deficit_3SM_M"] = (VIS_3SM_M - out["visibility"]).clip(lower=0.0)
    if "dew_point_2m" in out.columns:
        out["Dew_Point_Spread_C"] = out["temperature"] - out["dew_point_2m"]

    # --- Binary / categorical risk flags ---
    out["Is_Rain"] = out["precipitation"] > 0.0
    out["Is_Heavy_Rain"] = out["precipitation"] >= RAIN_HEAVY_MM_H
    out["Is_Strong_Wind"] = out["wind_speed"] >= WIND_STRONG_KMH
    out["Is_Gale_Wind"] = out["wind_speed"] >= WIND_GALE_KMH
    out["Is_Low_Visibility"] = out["visibility"] < VIS_LOW_M
    if "Dew_Point_Spread_C" in out.columns:
        early_hour = out["time"].dt.hour.between(0, 8)
        out["Is_Dewpoint_Spread_Le_1_5C"] = out["Dew_Point_Spread_C"] <= 1.5
        out["Is_Radiation_Fog_Risk"] = (
            out["Is_Dewpoint_Spread_Le_1_5C"]
            & (out["humidity"] >= HUMIDITY_FOG_PCT)
            & (out["wind_speed"] < 10.0)
            & early_hour
        )
    else:
        out["Is_Dewpoint_Spread_Le_1_5C"] = False
        out["Is_Radiation_Fog_Risk"] = False

    if "weather_code" in out.columns:
        code = out["weather_code"].round().astype("Int64")
        out["Is_WMO_Fog_Code"] = code.isin([45, 48])
        out["Is_WMO_Rain_Code"] = code.isin([51, 53, 55, 61, 63, 65, 80, 81, 82])
        out["Is_WMO_Thunderstorm_Code"] = code.isin([95, 96, 99])
    else:
        out["Is_WMO_Fog_Code"] = False
        out["Is_WMO_Rain_Code"] = False
        out["Is_WMO_Thunderstorm_Code"] = False

    out["Is_Fog"] = (
        ((out["visibility"] < VIS_FOG_M) & (out["humidity"] > HUMIDITY_FOG_PCT))
        | out["Is_Radiation_Fog_Risk"]
        | out["Is_WMO_Fog_Code"]
    )
    out["Is_Below_3SM_Visibility"] = out["visibility"] < VIS_3SM_M
    out["Is_Below_1SM_Visibility"] = out["visibility"] < VIS_1SM_M
    out["Visibility_Severity_Score"] = (
        out["Is_Low_Visibility"].astype(int)
        + out["Is_Below_3SM_Visibility"].astype(int)
        + out["Is_Below_1SM_Visibility"].astype(int) * 2
    )
    out["Is_Crosswind_10kt"] = out["Crosswind_Kt"] >= CROSSWIND_CAUTION_KT
    out["Is_Crosswind_15kt"] = out["Crosswind_Kt"] >= CROSSWIND_MODERATE_KT
    out["Is_Crosswind_20kt"] = out["Crosswind_Kt"] >= CROSSWIND_HIGH_KT
    out["Is_Freezing"] = out["temperature"] <= FREEZING_TEMP_C
    out["Is_Extreme_Heat"] = out["temperature"] >= HOT_TEMP_C
    if "cloud_cover_low" in out.columns:
        out["Is_Low_Ceiling_Risk"] = out["cloud_cover_low"] >= 80.0
    else:
        out["Is_Low_Ceiling_Risk"] = False
    if "cape" in out.columns and "lifted_index" in out.columns:
        out["Is_Severe_Convection_Risk"] = (out["cape"] >= 1500.0) & (out["lifted_index"] <= -3.0)
        out["Convective_Severity_Score"] = (
            (out["cape"] >= 1000.0).astype(int)
            + (out["cape"] >= 1500.0).astype(int)
            + (out["lifted_index"] <= -3.0).astype(int)
            + (out["lifted_index"] <= -5.0).astype(int)
        )
    else:
        out["Is_Severe_Convection_Risk"] = False
        out["Convective_Severity_Score"] = 0
    out["Is_Thunderstorm_Risk"] = (
        ((out["cloudcover"] > 80) & (out["precipitation"] > 0))
        | out["Is_Severe_Convection_Risk"]
        | out["Is_WMO_Thunderstorm_Code"]
    )

    # --- Runway condition risk ---
    # Wet: rain + temp above freezing
    out["Runway_Wet_Risk"] = 0
    out.loc[out["Is_Rain"] & (out["temperature"] > FREEZING_TEMP_C), "Runway_Wet_Risk"] = 1
    out.loc[out["Is_Heavy_Rain"] & (out["temperature"] > FREEZING_TEMP_C), "Runway_Wet_Risk"] = 2

    out["Forced_Runway_Swap_Risk"] = 0
    dry_tailwind = (out["Tailwind_Default_Runway_Kt"] >= 5.0) & (out["Runway_Wet_Risk"] == 0)
    wet_tailwind = (out["Tailwind_Default_Runway_Kt"] >= 5.0) & (out["Runway_Wet_Risk"] >= 1)
    out.loc[dry_tailwind, "Forced_Runway_Swap_Risk"] = 1
    out.loc[wet_tailwind, "Forced_Runway_Swap_Risk"] = 2

    # Ice: rain/drizzle + temp at or below freezing
    out["Runway_Ice_Risk"] = 0
    out.loc[out["Is_Rain"] & (out["temperature"] <= FREEZING_TEMP_C), "Runway_Ice_Risk"] = 1
    out.loc[out["Is_Heavy_Rain"] & (out["temperature"] <= FREEZING_TEMP_C), "Runway_Ice_Risk"] = 2

    # Composite delay risk score (simple heuristic 0-5)
    out["Weather_Delay_Risk_Score"] = (
        out["Is_Heavy_Rain"].astype(int)
        + out["Is_Strong_Wind"].astype(int)
        + out["Is_Gale_Wind"].astype(int) * 2
        + out["Is_Low_Visibility"].astype(int)
        + out["Is_Fog"].astype(int) * 2
        + out["Runway_Ice_Risk"].clip(upper=2)
        + out["Is_Thunderstorm_Risk"].astype(int)
        + out["Is_Low_Ceiling_Risk"].astype(int)
    ).clip(upper=5)

    # Aviation-oriented score: impact on airport operation, not just weather severity.
    out["Aviation_Operational_Risk_Score"] = (
        out["Visibility_Severity_Score"]
        + out["Is_Crosswind_10kt"].astype(int)
        + out["Is_Crosswind_15kt"].astype(int)
        + out["Is_Crosswind_20kt"].astype(int)
        + out["Is_Heavy_Rain"].astype(int)
        + out["Runway_Wet_Risk"].clip(upper=2)
        + out["Forced_Runway_Swap_Risk"]
        + out["Is_Thunderstorm_Risk"].astype(int)
        + out["Is_Low_Ceiling_Risk"].astype(int)
    ).clip(upper=8)

    return out


def finalize_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """Select and order final columns; rename for clarity."""
    core_cols = [
        "time",
        "Airport",
        "temperature",
        "precipitation",
        "cloudcover",
        "wind_speed",
        "wind_direction",
        "pressure",
        "humidity",
        "visibility",
        "dew_point_2m",
        "weather_code",
        "cape",
        "lifted_index",
        "cloud_cover_low",
        "Visibility_SM",
        "Visibility_Deficit_5KM_M",
        "Visibility_Deficit_3SM_M",
        "Visibility_Severity_Score",
        "Dew_Point_Spread_C",
    ]

    feature_cols = [
        "Wind_Sector",
        "Wind_Runway_Relative_Angle_Deg",
        "Crosswind_Kmh",
        "Headwind_Kmh",
        "Tailwind_Default_Runway_Kmh",
        "Wind_Kt",
        "Crosswind_Kt",
        "Headwind_Kt",
        "Tailwind_Default_Runway_Kt",
        "Temp_Change_1H_C",
        "Temp_Change_3H_C",
        "Pressure_Change_3H_Hpa",
        "Precip_Cumsum_1H_Mm",
        "Precip_Cumsum_3H_Mm",
        "Precip_Cumsum_6H_Mm",
        "Wind_Gust_Estimate_Kmh",
        "Crosswind_Max_3H_Kmh",
        "Wind_Gust_Estimate_Kt",
        "Crosswind_Max_3H_Kt",
        "Gust_Variation_Kmh",
        "Gust_Variation_Kt",
        "Is_Rain",
        "Is_Heavy_Rain",
        "Is_Strong_Wind",
        "Is_Gale_Wind",
        "Is_Low_Visibility",
        "Is_Fog",
        "Is_Dewpoint_Spread_Le_1_5C",
        "Is_Radiation_Fog_Risk",
        "Is_WMO_Fog_Code",
        "Is_WMO_Rain_Code",
        "Is_WMO_Thunderstorm_Code",
        "Is_Below_3SM_Visibility",
        "Is_Below_1SM_Visibility",
        "Is_Crosswind_10kt",
        "Is_Crosswind_15kt",
        "Is_Crosswind_20kt",
        "Is_Tailwind_Default_Runway_5kt",
        "Is_Low_Ceiling_Risk",
        "Is_Severe_Convection_Risk",
        "Is_Freezing",
        "Is_Extreme_Heat",
        "Is_Thunderstorm_Risk",
        "Convective_Severity_Score",
        "Runway_Wet_Risk",
        "Forced_Runway_Swap_Risk",
        "Runway_Ice_Risk",
        "Weather_Delay_Risk_Score",
        "Aviation_Operational_Risk_Score",
    ]

    keep = [c for c in core_cols + feature_cols if c in df.columns]
    out = df[keep].copy()

    # Round floats for readability
    float_cols = out.select_dtypes(include=[np.floating]).columns
    out[float_cols] = out[float_cols].round(2)

    # Fill NaT / NaN in object columns
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            out[col] = out[col].fillna("N/A")
        elif pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].fillna(False).astype(int)  # 0/1 for CSV
        elif pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].astype("string").fillna("N/A")
        else:
            out[col] = out[col].fillna("N/A")

    return out


def run_weather_pipeline(
    project_root: Path,
    silver_layer_name: str = DEFAULT_SILVER_LAYER_NAME,
) -> None:
    silver_root = project_root / "Data" / silver_layer_name
    silver_dir = silver_root / "Features"
    audit_dir = silver_root / "Audit"
    silver_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    print("[1/6] Loading bronze weather data...")
    df = load_bronze_weather(project_root)
    print(f"      Loaded {len(df)} rows from bronze weather.")

    print("[2/6] Auditing weather missing values and outliers...")
    missing_audit, outlier_audit = audit_weather_quality(df)
    missing_audit.to_csv(audit_dir / "audit_weather_missing_summary.csv", index=False, encoding="utf-8-sig")
    outlier_audit.to_csv(audit_dir / "audit_weather_outliers.csv", index=False, encoding="utf-8-sig")

    print("[3/6] Cleaning weather missing values and outliers...")
    df, cleaning_audit = clean_weather_values(df)
    cleaning_audit.to_csv(audit_dir / "audit_weather_cleaning_actions.csv", index=False, encoding="utf-8-sig")

    print("[4/6] Computing wind components (crosswind / headwind)...")
    df = compute_wind_components(df)

    print("[5/6] Engineering weather features...")
    df = engineer_features(df)

    print("[6/6] Exporting silver weather features...")
    df_export = finalize_for_export(df)
    out_path = silver_dir / "weather_features_hourly.csv"
    df_export.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"      Exported {len(df_export)} rows to {out_path}")
    print(f"      Weather audit dir: {audit_dir}")

    # Quick summary
    print("\n" + "=" * 60)
    print("Weather preprocessing completed")
    print(f"Silver layer name: {silver_layer_name}")
    print(f"Output: {out_path}")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weather preprocessing for DS108-AeroDelay")
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root path. Default: parent folder of this script.",
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
    run_weather_pipeline(project_root, silver_layer_name=args.silver_layer_name)


if __name__ == "__main__":
    main()
