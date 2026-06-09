import os
import subprocess
from pathlib import Path
from dagster import (
    asset,
    Definitions,
    define_asset_job,
    AssetSelection,
    get_dagster_logger
)


# CẤU HÌNH ĐƯỜNG DẪN THƯ MỤC
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DIR_CRAWL = PROJECT_ROOT / "Source code" / "1-Crawl Data"
DIR_PREPROCESS = PROJECT_ROOT / "Source code" / "2-Preprocessing"
DIR_EDA = PROJECT_ROOT / "Source code" / "4-EDA"
DIR_FEATURE_MODEL = PROJECT_ROOT / "Source code" / "3-Feature Engineering & Model"
DIR_BONUS = PROJECT_ROOT / "Source code" / "5-Bonus points"

logger = get_dagster_logger()


# HÀM HỖ TRỢ CHẠY SCRIPT & NOTEBOOK
def run_python_script(script_path: Path, env_vars: dict = None):
    """Chạy file .py bằng subprocess"""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    logger.info(f"Đang thực thi: {script_path.name}")
    result = subprocess.run(["python", str(script_path)], env=env, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Lỗi khi chạy {script_path.name}:\n{result.stderr}")
        raise RuntimeError(f"Script {script_path.name} thất bại.")
    return result.stdout


def run_notebook(notebook_path: Path):
    """Chạy file .ipynb tự động bằng jupyter nbconvert"""
    logger.info(f"Đang thực thi Notebook: {notebook_path.name}")
    result = subprocess.run([
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        "--inplace", str(notebook_path)
    ], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Lỗi khi chạy Notebook {notebook_path.name}:\n{result.stderr}")
        raise RuntimeError(f"Notebook {notebook_path.name} thất bại.")
    return "Notebook executed successfully"


# TẦNG 1: BRONZE LAYER (DATA CRAWLING)
@asset(group_name="bronze_layer")
def crawl_dad_departure():
    run_python_script(DIR_CRAWL / "crawl_dad_departure.py")

@asset(group_name="bronze_layer", deps=[crawl_dad_departure])
def crawl_dad_arrival():
    run_python_script(DIR_CRAWL / "crawl_dad_arrival.py")

@asset(group_name="bronze_layer", deps=[crawl_dad_arrival])
def crawl_dad_departure_aircraft():
    run_python_script(DIR_CRAWL / "crawl_dad_departure_aircraft.py")

@asset(group_name="bronze_layer", deps=[crawl_dad_departure_aircraft])
def crawl_dad_arrival_aircraft():
    run_python_script(DIR_CRAWL / "crawl_dad_arrival_aircraft.py")

@asset(group_name="bronze_layer", deps=[crawl_dad_arrival_aircraft])
def crawl_arrival_history_han():
    run_python_script(DIR_CRAWL / "crawl_arrival_history.py", {"ORIGIN_DATA": "HAN"})

@asset(group_name="bronze_layer", deps=[crawl_arrival_history_han])
def crawl_arrival_history_sgn():
    run_python_script(DIR_CRAWL / "crawl_arrival_history.py", {"ORIGIN_DATA": "SGN"})

@asset(group_name="bronze_layer", deps=[crawl_arrival_history_sgn])
def crawl_departure_history_han():
    run_python_script(DIR_CRAWL / "crawl_departure_history.py", {"ORIGIN_DATA": "HAN"})

@asset(group_name="bronze_layer", deps=[crawl_departure_history_han])
def crawl_departure_history_sgn():
    run_python_script(DIR_CRAWL / "crawl_departure_history.py", {"ORIGIN_DATA": "SGN"})

@asset(group_name="bronze_layer", deps=[crawl_departure_history_sgn])
def crawl_dad_departure_runway():
    run_python_script(DIR_CRAWL / "crawl_dad_runway_category.py", {"ROUTE": "departure"})

@asset(group_name="bronze_layer", deps=[crawl_dad_departure_runway])
def crawl_dad_arrival_runway():
    run_python_script(DIR_CRAWL / "crawl_dad_runway_category.py", {"ROUTE": "arrival"})

@asset(group_name="bronze_layer", deps=[crawl_departure_history_sgn])
def weather_crawling():
    run_python_script(DIR_CRAWL / "weather_crawling.py")

# TẦNG 2: SILVER LAYER & AUDIT (PREPROCESSING)
@asset(group_name="silver_layer", deps=[weather_crawling])
def data_preprocessing():
    run_python_script(DIR_PREPROCESS / "data_preprocessing.py")

@asset(group_name="silver_layer", deps=[data_preprocessing])
def weather_preprocessing():
    run_python_script(DIR_PREPROCESS / "weather_preprocessing.py")

@asset(group_name="audit_checkpoint", deps=[data_preprocessing, weather_preprocessing])
def audit_runway_swap():
    """
    KẾT THÚC JOB 1: Dừng tại đây để kiểm duyệt Audit.
    """
    run_python_script(DIR_PREPROCESS / "audit_runway_swap.ipynb")
    return "Audit Complete. Please review files before triggering Job 2."

# TẦNG 3: EDA & MISSING FLIGHTS
@asset(group_name="missing_data_layer", deps=[audit_runway_swap])
def crawl_missing_departure_flights():
    run_python_script(DIR_CRAWL / "crawl_missing_departure_flights.py")

@asset(group_name="missing_data_layer", deps=[crawl_missing_departure_flights])
def crawl_missing_arrival_flights():
    run_python_script(DIR_CRAWL / "crawl_missing_arrival_flights.py")

@asset(group_name="eda_layer", deps=[crawl_missing_arrival_flights])
def eda_weather_plan():
    run_notebook(DIR_EDA / "eda_weather_plan_notebook.ipynb")

@asset(group_name="eda_layer", deps=[eda_weather_plan])
def flight_eda():
    run_notebook(DIR_EDA / "flight_eda.ipynb")
    """
    KẾT THÚC JOB 2: Dừng tại đây để kiểm duyệt EDA.
    """
    return "EDA Complete. Please review files before triggering Job 2."

# TẦNG 4: GOLD LAYER (FEATURES) & MODEL TRAINING
@asset(group_name="gold_layer", deps=[flight_eda])
def feature_extraction(): run_notebook(DIR_FEATURE_MODEL / "feature_extraction.ipynb")


@asset(group_name="gold_layer", deps=[feature_extraction])
def weather_features(): run_notebook(DIR_FEATURE_MODEL / "weather_features.ipynb")


@asset(group_name="gold_layer", deps=[weather_features])
def llm_annotator(): run_notebook(DIR_BONUS / "llm_annotator.ipynb")


@asset(group_name="model_training", deps=[llm_annotator])
def model_training(): run_notebook(DIR_FEATURE_MODEL / "model_training.ipynb")


@asset(group_name="deployment", deps=[model_training])
def streamlit_app():
    """Lệnh chạy App sẽ không block luồng Dagster"""
    logger.info("Mô hình đã sẵn sàng. Để khởi chạy UI, dùng lệnh: streamlit run app.py")
    return "Ready for Deployment"


# ĐỊNH NGHĨA CÁC CÔNG VIỆC PHẢI TỰ XỬ LÝ
# Phân chia pipeline thành 3 chặng

job_1_crawling_to_audit = define_asset_job(
    name="Job_1_Bronze_to_Audit",
    selection=AssetSelection.groups("bronze_layer", "silver_layer", "audit_checkpoint"),
    description="Chạy Crawl và Tiền xử lý. Dừng lại sau khi xuất Audit Runway Swap."
)

job_2_eda_and_missing_data = define_asset_job(
    name="Job_2_EDA_and_Review",
    selection=AssetSelection.groups("eda_layer", "missing_data_layer"),
    description="Chạy phân tích EDA và cào dữ liệu thiếu. Dừng lại để rà soát."
)

job_3_gold_features_to_model = define_asset_job(
    name="Job_3_Gold_to_Model",
    selection=AssetSelection.groups("gold_layer", "model_training", "deployment"),
    description="Chạy tạo Đặc trưng, gán nhãn LLM và Huấn luyện mô hình."
)

defs = Definitions(
    assets=[
        crawl_dad_departure, crawl_dad_arrival, crawl_dad_arrival_aircraft,
        crawl_dad_departure_aircraft, crawl_dad_departure_runway, crawl_dad_arrival_runway,
        crawl_arrival_history_han, crawl_arrival_history_sgn,
        crawl_departure_history_han, crawl_departure_history_sgn, weather_crawling,
        data_preprocessing, weather_preprocessing, audit_runway_swap,
        crawl_missing_departure_flights, crawl_missing_arrival_flights,
        eda_weather_plan, flight_eda,
        feature_extraction, weather_features, llm_annotator,
        model_training, streamlit_app
    ],
    jobs=[job_1_crawling_to_audit, job_2_eda_and_missing_data, job_3_gold_features_to_model]
)