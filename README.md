*Đồ án môn học nhóm 18 DS108 - Tiền xử lý và xây dựng bộ dữ liệu*
# AeroDelay: Thu thập dữ liệu hàng không và tiền xử lý cho bài toán dự đoán trễ chuyến dây chuyền.

## Giới thiệu dự án
**AeroDelay** là nền tảng thu thập – xử lý – trích xuất đặc trưng dữ liệu hàng không và dữ liệu thời tiết nhằm phục vụ bài toán **dự đoán trễ chuyến**.

Dự án áp dụng quy trình dữ liệu theo các lớp **Bronze → Silver → Gold** và triển khai các bước Feature Engineering / Model Training bằng Python (kết hợp notebook).

---

## Cấu trúc dự án
```text
├── 18_24520617_24520636_Data/
│   ├── Bronze_layer/                 # Dữ liệu thô (flights, weather...)
│   │   ├── Arrival/
│   │   └── Departure/
│   │   └── airport_weather_hourly_merged.csv 
│   ├── Silver_layer/                 # Dữ liệu đã làm sạch/chuẩn hóa (có audit & patch files)
│   │   ├── Arrival/
│   │   ├── Departure/
│   │   └── Audit/
│   │   └── Features/
│   └── Gold_layer/                   # Dữ liệu đặc trưng sẵn sàng cho ML (master feature files)
│   │ 	├── Arrival/
│   │   ├── Departure/
│   │   └── Audit/	
│   |   └── Features/
│   ├── final_merged_patched_flights.csv     
│   ├── valid_patched_flights.csv    
│   ├── CODEBOOK_AERODELAY_GOLD.xlsx   
│
├── 18_24520617_24520636_References/  # Tài liệu tham khảo / ghi chú / tài liệu liên quan
│
├── 18_24520617_24520636_Source code/
│   ├── 1-Crawl data/                 # Scripts thu thập dữ liệu (Bronze)
│   ├── 2-Preprocessing/              # Tiền xử lý flights & weather
│   │   ├── data_preprocessing.py
│   │   ├── weather_preprocessing.py
│   │   └── audit_runway_swap.ipynb
│   ├── 3-Feature Engineering & Model/ # Trích xuất đặc trưng & huấn luyện mô hình
│   │   ├── feature_extraction.ipynb
│   │   ├── weather_features.ipynb
│   │   ├── model_training.ipynb
│   │   └── models/                    # Model artifacts
│   ├── 4-EDA/                         # Phân tích khám phá dữ liệu
│   └── 5-Bonus Points/                # Phần mở rộng / bonus (Streamlit dashboard + Dagster)
│       ├── app.py
│       └── dagster_pipeline.py
│       └── cross_validation_llm.ipynb
│       └── llm_annotator.ipynb
│
├── 18_24520617_24520636_Demo/
│
├── 18_24520617_24520636_Report.pdf
├── 18_24520617_24520636_Slide.pdf
├── requirements.txt
└── README.md
```

---

## Quy trình thực hiện

### 1) Thu thập dữ liệu (Crawling)
- Thu thập dữ liệu chuyến bay và dữ liệu thời tiết theo các nguồn nhóm sử dụng.
- Mục tiêu: xây dựng dữ liệu thô (Bronze) đủ lớn để phân tích và xử lý.

### 2) Tiền xử lý (Preprocessing)
- Làm sạch, chuẩn hóa schema, xử lý thiếu dữ liệu, chuẩn hóa thời gian, đồng bộ cột giữa các nguồn.
- Các script chính nằm tại:
  - `Source code/2-Preprocessing/data_preprocessing.py`
  - `Source code/2-Preprocessing/weather_preprocessing.py`

### 3) Feature Engineering & Model
- Trích xuất đặc trưng (bao gồm các yếu tố liên quan lan truyền trễ & thời tiết).
- Huấn luyện / đánh giá mô hình trong notebooks:
  - `Source code/3-Feature Engineering & Model/feature_extraction.ipynb`
  - `Source code/3-Feature Engineering & Model/weather_features.ipynb`
  - `Source code/3-Feature Engineering & Model/model_training.ipynb`

### 4) EDA
- Thực hiện phân tích khám phá, trực quan hóa và báo cáo trong `Source code/4-EDA/`.

---

## Cài đặt & môi trường

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Thư viện chính sử dụng

| Thư viện | Mục đích |
|---|---|
| `pandas`, `numpy` | Xử lý, làm sạch và phân tích dữ liệu |
| `selenium`, `beautifulsoup4`, `requests`, `undetected-chromedriver` | Thu thập dữ liệu từ web |
| `webdriver-manager` | Hỗ trợ driver |
| `scikit-learn`, `joblib`, `lightgbm` | Huấn luyện, đánh giá mô hình và lưu model |
| `matplotlib`, `seaborn`, `plotly` | Trực quan hóa |
| `streamlit` | Dashboard / trực quan tương tác |
| `dagster` | Orchestration pipeline |
| `ollama` | Tích hợp/triển khai LLM cục bộ |
| `python-dotenv` | Quản lý biến môi trường (tùy dùng) |
| `statsmodels`, `tqdm` | Phân tích bổ trợ, tiến trình vòng lặp |
| `jupyter`, `notebook`, `ipython`, `nbconvert` | Hỗ trợ chạy và xuất notebook |

---
