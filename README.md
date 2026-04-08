*Đồ án môn học nhóm 13 DS108 - Tiền xử lý và xây dựng bộ dữ liệu*
# AeroDelay: Thu thập dữ liệu hàng không và tiền xử lý cho bài toán dự đoán trễ chuyến dây chuyền.

---

## Giới thiệu dự án
**AeroDelay** là nền tảng phân tích và dự báo tình trạng trễ chuyến bay dựa trên hiện tượng **lan truyền và thời tiết**. Dự án kết hợp các kỹ thuật Big Data và Machine Learning để giải quyết bài toán tối ưu hóa lịch trình bay tại các sân bay lớn của Việt Nam (SGN, HAN, DAD).

---

## Cấu trúc dự án
```text
├── Data/
│   ├── Bronze_layer/           # Dữ liệu thô thu thập từ các nguồn (SGN, HAN, DAD)
│   │   ├── Arrival/            # Dữ liệu lịch sử hạ cánh (.csv, .json)
│   │   └── Departure/          # Dữ liệu lịch sử cất cánh (.csv, .json)
│   │   └── Weather/            # Dữ liệu thời tiết tại 3 sân bay (.csv)
│   ├── dad_fixed_flights.json  # Dữ liệu lưu trữ JSON tạm thời hỗ trợ không cào lại những thứ đã cào rồi
│   ├── han_fixed_flights.json  # Dữ liệu lưu trữ JSON tạm thời hỗ trợ không cào lại những thứ đã cào rồi
│   ├── sgn_fixed_flights.json  # Dữ liệu lưu trữ JSON tạm thời hỗ trợ không cào lại những thứ đã cào rồi
│   ├── Silver_layer/           # Dữ liệu đã chuẩn hóa và xử lý qua Spark
│   └── Gold_layer/             # Tập dữ liệu đặc trưng sẵn sàng cho huấn luyện ML
│
├── Source code/
│   ├── crawl_arrival_history.py   # Thu thập dữ liệu chuyến đến từ FlightRadar24
│   ├── crawl_departure_history.py # Thu thập dữ liệu chuyến đi từ FlightRadar24
│   ├── crawl_dad_arrival.py       # Thu thập dữ liệu chuyến đến của DAD từ web cảng vụ Đà Nẵng
│   ├── crawl_dad_departure.py     # Thu thập dữ liệu chuyến đi của DAD từ web cảng vụ Đà Nẵng
│   ├── crawl_dad_aỉcraft.py       # Thu thập dữ liệu tàu bay của các chuyến DAD từ FlightRadar24
│   ├── crawl_latest.py            # Thu thập dữ liệu chuyến bay trong 3 ngày gần nhất từ FlightRadar24
│   ├── data_processing_spark.py   # Pipeline xử lý dữ liệu lớn với Apache Spark
│   ├── kafka_stream.py            # Điều phối luồng dữ liệu thời gian thực
│   ├── feature_extraction.py      # Trích xuất đặc trưng từ dữ liệu lớn
│   └── model_training.py          # Huấn luyện mô hình (RF, SVM, Decision Tree)
│
├── requirements.txt
└── README.md
```

---

## Quy trình thực hiện

### Giai đoạn 1: Thu thập dữ liệu quy mô lớn (Data Crawling)

Hệ thống sử dụng đa dạng các module crawler để trích xuất thông tin toàn diện từ nhiều nguồn khác nhau (FlightRadar24, Cổng thông tin Cảng vụ).

* **Bước 1:** Cấu hình tham số sân bay (IATA: **SGN, HAN, DAD**) và thiết lập khoảng thời gian cần thu thập trong các script tương ứng.
* **Bước 2:** Khởi chạy các module thu thập dữ liệu đa luồng tùy thuộc vào luồng dữ liệu mục tiêu:
  * **Lịch sử chuyến bay chung (FlightRadar24):** 
    ```bash
    python "Source code/crawl_arrival_history.py"
    python "Source code/crawl_departure_history.py"
    ```
  * **Dữ liệu chi tiết cụm sân bay Đà Nẵng (DAD):** Kết hợp dữ liệu từ cảng vụ và radar để tăng độ chính xác.
    ```bash
    python "Source code/crawl_dad_arrival.py"
    python "Source code/crawl_dad_departure.py"
    python "Source code/crawl_dad_aircraft.py"
    ```
  * **Cập nhật dữ liệu mới nhất (3 ngày gần đây):** Dùng để thu thập dữ liệu gần thời gian thực.
    ```bash
    python "Source code/crawl_latest.py"
    ```
* **Mục tiêu:** Tổng hợp khoảng **70.000 mẫu** dữ liệu lịch sử bay thực tế đa chiều, bao gồm thông tin cất/hạ cánh, chi tiết tàu bay và dữ liệu cận thời gian thực.
* **Kỹ thuật áp dụng:** 
  * **Multithreading:** Xử lý đa luồng giúp tăng hiệu suất thu thập lên đến 50%.
  * **Anti-Scraping:** Tích hợp Rotating Proxies và giả lập User-Agent linh hoạt để vượt qua các cơ chế phòng vệ của website.
  * **Caching:** Thiết lập cơ chế lưu trữ JSON tạm thời, đảm bảo không thất thoát dữ liệu đang cào dang dở khi gặp sự cố gián đoạn mạng.

---
### Giai đoạn 2: Kỹ thuật hóa dữ liệu (Data Engineering)

* **Xử lý bằng Spark:** Chuẩn hóa dữ liệu từ lớp Bronze, xử lý giá trị khuyết (missing values), đồng bộ số lượng cột và định dạng lại dữ liệu.
* **Pipeline Kafka:** Truyền tải luồng dữ liệu ổn định, giảm thiểu rủi ro nghẽn cổ chai khi xử lý khối lượng lớn.
* **Feature Extraction:** Trích xuất các đặc trưng quan trọng: Độ trễ lan truyền từ chuyến bay trước, loại tàu bay, nhà ga (Terminal) và đường băng (Runway).

### Giai đoạn 3: Huấn luyện & Dự đoán (Machine Learning)

Triển khai các mô hình học máy để dự báo thời gian trễ:
* **Random Forest & Decision Tree:** Phân loại và dự đoán mức độ trễ dựa trên cây quyết định.
* **SVM (Support Vector Machine):** Tối ưu hóa ranh giới phân tách các lớp dữ liệu trễ chuyến.

### Giai đoạn 4: Đánh giá kết quả

* **Đánh giá mô hình:** Sử dụng các chỉ số đo lường hiệu suất như Accuracy, Precision, Recall và F1-Score.
* **Phân tích nghiệp vụ:** Đánh giá các yếu tố ảnh hưởng mạnh nhất đến sự lan truyền trễ chuyến trong mạng lưới bay nội địa Việt Nam.

--- 
## Thư viện sử dụng

| Thư viện | Mục đích |
|---|---|
| `pandas`, `numpy` | Xử lý, làm sạch và phân tích dữ liệu |
| `selenium`, `beautifulsoup4`, `scrapy`, `requests` | Thu thập dữ liệu từ các trang web |
| `webdriver-manager`, `msedge-selenium-tools`, `fake-useragent` | Hỗ trợ quản lý driver trình duyệt và giả lập người dùng để vượt Anti-Scraping |
| `pyspark`, `kafka-python` | Quản lý pipeline dữ liệu lớn và truyền tải luồng dữ liệu |
| `scikit-learn`, `joblib` | Huấn luyện, đánh giá mô hình học máy và lưu trữ/tải mô hình |
| `matplotlib`, `seaborn` | Trực quan hóa dữ liệu và vẽ biểu đồ đánh giá hiệu suất mô hình |
| `python-dotenv` | Quản lý các biến môi trường và thiết lập cấu hình an toàn |
--- 
Dự án đang trong quá trình phát triển và hoàn thiện các giai đoạn tiếp theo.