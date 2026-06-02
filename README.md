*Đồ án môn học nhóm 13 DS108 - Tiền xử lý và xây dựng bộ dữ liệu*
# AeroDelay: Thu thập dữ liệu hàng không và tiền xử lý cho bài toán dự đoán trễ chuyến dây chuyền.

---

## Giới thiệu dự án
**AeroDelay** là nền tảng thu thập – xử lý – trích xuất đặc trưng dữ liệu hàng không và dữ liệu thời tiết nhằm phục vụ bài toán **dự đoán trễ chuyến** (tập trung vào hiện tượng **lan truyền trễ** và yếu tố **thời tiết**).  
Dự án áp dụng quy trình dữ liệu theo các lớp **Bronze → Silver → Gold** và triển khai các bước Feature Engineering / Model Training bằng Python (kết hợp notebook).

---

## Cấu trúc dự án (cập nhật)
```text
├── Data/
│   ├── Bronze_layer/                 # Dữ liệu thô (flights, weather...)
│   ├── Silver_layer/                 # Dữ liệu đã làm sạch/chuẩn hóa
│   └── Gold_layer/                   # Dữ liệu đặc trưng sẵn sàng cho ML
│
├── References/                       # Tài liệu tham khảo / ghi chú / tài liệu liên quan
│
├── Source code/
│   ├── 1-Crawl data/                 # Scripts thu thập dữ liệu
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
│
├── requirements.txt
└── README.md
```

---

## Quy trình thực hiện (tổng quan)

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

## Thư viện sử dụng

| Thư viện | Mục đích |
|---|---|
| `pandas`, `numpy` | Xử lý, làm sạch và phân tích dữ liệu |
| `selenium`, `beautifulsoup4`, `scrapy`, `requests` | Thu thập dữ liệu từ web |
| `webdriver-manager`, `msedge-selenium-tools`, `fake-useragent` | Hỗ trợ driver và giả lập User-Agent để hạn chế anti-scraping |
| `pyspark`, `kafka-python` | Xử lý dữ liệu lớn / streaming (nếu dùng) |
| `scikit-learn`, `joblib` | Huấn luyện, đánh giá mô hình và lưu model |
| `matplotlib`, `seaborn` | Trực quan hóa |
| `python-dotenv` | Quản lý biến môi trường |
