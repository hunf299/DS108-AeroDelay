from pathlib import Path
from dagster import asset, Definitions

CWD = Path.cwd().resolve()
PROJECT_ROOT = CWD if (CWD / "Data").exists() else CWD.parent
if not (PROJECT_ROOT / "Data").exists():
    raise FileNotFoundError("Cannot find project root containing 'Data'.")

# Định nghĩa các thư mục tầng chính
BRONZE_DIR = PROJECT_ROOT / "Data" / "Bronze_layer"
SILVER_DIR = PROJECT_ROOT / "Data" / "Silver_layer"
GOLD_DIR = PROJECT_ROOT / "Data" / "Gold_layer"
MODEL_DIR = PROJECT_ROOT / "Source code" / "models"

# --- ARRIVAL ---
@asset
def bronze_sgn_arrival():
    if not (BRONZE_DIR / "Arrival" / "sgn_flights_arrival_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_sgn_arrival")
    return "Verified"


@asset
def bronze_han_arrival():
    if not (BRONZE_DIR / "Arrival" / "han_flights_arrival_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_han_arrival")
    return "Verified"


@asset
def bronze_dad_arrival():
    if not (BRONZE_DIR / "Arrival" / "dad_flights_arrival_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_dad_arrival")
    return "Verified"


# --- DEPARTURE ---
@asset
def bronze_sgn_departure():
    if not (BRONZE_DIR / "Departure" / "sgn_flights_departure_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_sgn_departure")
    return "Verified"


@asset
def bronze_han_departure():
    if not (BRONZE_DIR / "Departure" / "han_flights_departure_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_han_departure")
    return "Verified"


@asset
def bronze_dad_departure():
    if not (BRONZE_DIR / "Departure" / "dad_flights_departure_bronze_layer.csv").exists():
        raise FileNotFoundError("Thiếu file bronze_dad_departure")
    return "Verified"

# --- ARRIVAL ---
@asset(deps=[bronze_sgn_arrival])
def silver_sgn_arrival_cleaned():
    return "Silver SGN Arrival Ready"


@asset(deps=[bronze_han_arrival])
def silver_han_arrival_cleaned():
    return "Silver HAN Arrival Ready"


@asset(deps=[bronze_dad_arrival])
def silver_dad_arrival_cleaned():
    return "Silver DAD Arrival Ready"


# --- DEPARTURE ---
@asset(deps=[bronze_sgn_departure])
def silver_sgn_departure_cleaned():
    return "Silver SGN Departure Ready"


@asset(deps=[bronze_han_departure])
def silver_han_departure_cleaned():
    return "Silver HAN Departure Ready"


@asset(deps=[bronze_dad_departure])
def silver_dad_departure_cleaned():
    return "Silver DAD Departure Ready"


# --- FEATURES ---
@asset
def silver_weather_features():
    target_file = SILVER_DIR / "Features" / "weather_features_hourly.csv"
    if not target_file.exists():
        raise FileNotFoundError(f"Không tìm thấy đặc trưng khí tượng tại: {target_file}")
    return "Weather Features Verified"

# --- HỘI TỤ VÀO MASTER FEATURES ---
@asset(deps=[
    silver_sgn_arrival_cleaned, silver_han_arrival_cleaned, silver_dad_arrival_cleaned,
    silver_sgn_departure_cleaned, silver_han_departure_cleaned, silver_dad_departure_cleaned,
    silver_weather_features
])
def master_gold_features():
    """Hội tụ tất cả các luồng dữ liệu vào thư mục Features của Gold Layer"""
    target_file = GOLD_DIR / "Features" / "master_departure_features_gold.csv"  # Hoặc master_aero_features_gold.csv
    if not target_file.exists():
        raise FileNotFoundError(f"Không tìm thấy tệp Master Gold tại: {target_file}")
    return "Master Centralized Gold Verified"


# --- PHÂN RÃ NGƯỢC RA ARRIVAL & DEPARTURE (GOLD) ---
# ARRIVAL GOLD
@asset(deps=[master_gold_features])
def gold_sgn_arrival():
    if not (GOLD_DIR / "Arrival" / "sgn_flights_arrival_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Arrival SGN")
    return "Verified"


@asset(deps=[master_gold_features])
def gold_han_arrival():
    if not (GOLD_DIR / "Arrival" / "han_flights_arrival_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Arrival HAN")
    return "Verified"


@asset(deps=[master_gold_features])
def gold_dad_arrival():
    if not (GOLD_DIR / "Arrival" / "dad_flights_arrival_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Arrival DAD")
    return "Verified"


# DEPARTURE GOLD
@asset(deps=[master_gold_features])
def gold_sgn_departure():
    if not (GOLD_DIR / "Departure" / "sgn_flights_departure_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Departure SGN")
    return "Verified"


@asset(deps=[master_gold_features])
def gold_han_departure():
    if not (GOLD_DIR / "Departure" / "han_flights_departure_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Departure HAN")
    return "Verified"


@asset(deps=[master_gold_features])
def gold_dad_departure():
    if not (GOLD_DIR / "Departure" / "dad_flights_departure_gold_layer.csv").exists():
        raise FileNotFoundError("Thiếu file Gold Departure DAD")
    return "Verified"


@asset(deps=[gold_sgn_departure, gold_han_departure, gold_dad_departure])
def model_training_artifacts():
    model_file = MODEL_DIR / "best_aerodelay_model.pkl"
    feature_file = MODEL_DIR / "best_model_features.pkl"

    if not model_file.exists() or not feature_file.exists():
        raise FileNotFoundError("Thiếu các file .pkl phục vụ mô hình tại thư mục models/")
    return "All Production Artifacts Successfully Validated"

defs = Definitions(
    assets=[
        # Khối Bronze
        bronze_sgn_arrival, bronze_han_arrival, bronze_dad_arrival,
        bronze_sgn_departure, bronze_han_departure, bronze_dad_departure,

        # Khối Silver
        silver_sgn_arrival_cleaned, silver_han_arrival_cleaned, silver_dad_arrival_cleaned,
        silver_sgn_departure_cleaned, silver_han_departure_cleaned, silver_dad_departure_cleaned,
        silver_weather_features,

        # Khối Gold Hội Tụ
        master_gold_features,

        # Khối Gold Phân rã
        gold_sgn_arrival, gold_han_arrival, gold_dad_arrival,
        gold_sgn_departure, gold_han_departure, gold_dad_departure,

        # Khối Đích
        model_training_artifacts
    ]
)