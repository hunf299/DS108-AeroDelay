"""
Weather preprocessing for DS108-AeroDelay.

Reads Bronze-layer hourly weather data, engineers aviation-relevant
features (crosswind, runway condition, visibility risk, etc.), and
exports a clean Silver-layer weather feature table.

Usage:
    python weather_preprocessing.py --project-root ".."
"""

import argparse
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd


# ------------------------------------------------------------------
# Airport mappings
# ------------------------------------------------------------------
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
RAIN_HEAVY_MM_H = 5.0
WIND_STRONG_KMH = 30.0
WIND_GALE_KMH = 50.0
VIS_LOW_M = 5000.0
VIS_FOG_M = 1000.0
HUMIDITY_FOG_PCT = 90.0
FREEZING_TEMP_C = 5.0
HOT_TEMP_C = 35.0


def load_bronze_weather(project_root: Path) -> pd.DataFrame:
    """Load raw merged weather CSV from Bronze layer."""
    bronze_path = (
        project_root / "Data crawl" / "Bronze_layer" / "airport_weather_hourly_merged.csv"
    )
    if not bronze_path.exists():
        raise FileNotFoundError(f"Missing bronze weather file: {bronze_path}")

    df = pd.read_csv(bronze_path, dtype=str)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    # Map airport names -> IATA codes
    df["Airport"] = df["airport"].astype("string").str.lower().map(AIRPORT_CODE_MAP)

    # Cast numeric columns
    numeric_cols = [
        "temperature",
        "precipitation",
        "cloudcover",
        "wind_speed",
        "wind_direction",
        "pressure",
        "humidity",
        "visibility",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Sort for rolling windows
    df = df.sort_values(["Airport", "time"]).reset_index(drop=True)
    return df


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

    # --- Binary / categorical risk flags ---
    out["Is_Rain"] = out["precipitation"] > 0.0
    out["Is_Heavy_Rain"] = out["precipitation"] >= RAIN_HEAVY_MM_H
    out["Is_Strong_Wind"] = out["wind_speed"] >= WIND_STRONG_KMH
    out["Is_Gale_Wind"] = out["wind_speed"] >= WIND_GALE_KMH
    out["Is_Low_Visibility"] = out["visibility"] < VIS_LOW_M
    out["Is_Fog"] = (out["visibility"] < VIS_FOG_M) & (out["humidity"] > HUMIDITY_FOG_PCT)
    out["Is_Freezing"] = out["temperature"] <= FREEZING_TEMP_C
    out["Is_Extreme_Heat"] = out["temperature"] >= HOT_TEMP_C
    out["Is_Thunderstorm_Risk"] = (out["cloudcover"] > 80) & (out["precipitation"] > 0)

    # --- Runway condition risk ---
    # Wet: rain + temp above freezing
    out["Runway_Wet_Risk"] = 0
    out.loc[out["Is_Rain"] & (out["temperature"] > FREEZING_TEMP_C), "Runway_Wet_Risk"] = 1
    out.loc[out["Is_Heavy_Rain"] & (out["temperature"] > FREEZING_TEMP_C), "Runway_Wet_Risk"] = 2

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
    ).clip(upper=5)

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
    ]

    feature_cols = [
        "Crosswind_Kmh",
        "Headwind_Kmh",
        "Temp_Change_1H_C",
        "Temp_Change_3H_C",
        "Pressure_Change_3H_Hpa",
        "Precip_Cumsum_1H_Mm",
        "Precip_Cumsum_3H_Mm",
        "Precip_Cumsum_6H_Mm",
        "Wind_Gust_Estimate_Kmh",
        "Crosswind_Max_3H_Kmh",
        "Is_Rain",
        "Is_Heavy_Rain",
        "Is_Strong_Wind",
        "Is_Gale_Wind",
        "Is_Low_Visibility",
        "Is_Fog",
        "Is_Freezing",
        "Is_Extreme_Heat",
        "Is_Thunderstorm_Risk",
        "Runway_Wet_Risk",
        "Runway_Ice_Risk",
        "Weather_Delay_Risk_Score",
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


def run_weather_pipeline(project_root: Path) -> None:
    silver_dir = project_root / "Data crawl" / "Silver_layer" / "Features"
    silver_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading bronze weather data...")
    df = load_bronze_weather(project_root)
    print(f"      Loaded {len(df)} rows from bronze weather.")

    print("[2/4] Computing wind components (crosswind / headwind)...")
    df = compute_wind_components(df)

    print("[3/4] Engineering weather features...")
    df = engineer_features(df)

    print("[4/4] Exporting silver weather features...")
    df_export = finalize_for_export(df)
    out_path = silver_dir / "weather_features_hourly.csv"
    df_export.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"      Exported {len(df_export)} rows to {out_path}")

    # Quick summary
    print("\n" + "=" * 60)
    print("Weather preprocessing completed")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]
    project_root = Path(args.project_root).resolve() if args.project_root else default_root
    run_weather_pipeline(project_root)


if __name__ == "__main__":
    main()
