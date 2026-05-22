# Weather Preprocessing Guide

## 1. Tổng quan

Module `weather_preprocessing.py` xử lý dữ liệu thời tiết hàng giờ (hourly) từ Bronze layer thành bảng đặc trưng (feature table) ở Silver layer, phục vụ cho việc phân tích delay và xây dựng mô hình.

**Input**: `Data crawl/Bronze_layer/airport_weather_hourly_merged.csv`  
**Output**: `Data crawl/Silver_layer/Features/weather_features_hourly.csv`

---

## 2. Input (Bronze Weather)

| Cột | Đơn vị | Mô tả |
|------|---------|--------|
| `time` | ISO datetime | Thời điểm quan trắc (UTC+7) |
| `temperature` | °C | Nhiệt độ không khí |
| `precipitation` | mm | Lượng mưa trong giờ |
| `cloudcover` | % | Độ che phủ mây |
| `wind_speed` | km/h | Tốc độ gió 10m |
| `wind_direction` | ° | Hướng gió (0-360) |
| `pressure` | hPa | Áp suất khí quyển mặt đất |
| `humidity` | % | Độ ẩm tương đối |
| `visibility` | m | Tầm nhìn ngang |
| `airport` | string | Tên nội bộ: `tan_son_nhat`, `noi_bai`, `da_nang` |

**Phạm vi dữ liệu**: 2025-12-15 đến 2026-03-16, tần suất 1 giờ / mẫu, 3 sân bay.

---

## 3. Output (Silver Weather Features)

### 3.1 Cột gốc giữ lại

| Cột | Đơn vị |
|------|---------|
| `time` | ISO datetime |
| `Airport` | IATA: `SGN` / `HAN` / `DAD` |
| `temperature` | °C |
| `precipitation` | mm/h |
| `cloudcover` | % |
| `wind_speed` | km/h |
| `wind_direction` | ° |
| `pressure` | hPa |
| `humidity` | % |
| `visibility` | m |

### 3.2 Đặc trưng gió (Wind Engineering)

| Cột | Đơn vị | Mô tả |
|------|---------|--------|
| `Crosswind_Kmh` | km/h | Thành phần gió ngang so với đường băng mặc định |
| `Headwind_Kmh` | km/h | Thành phần gió đối đầu (âm = tailwind) |
| `Crosswind_Max_3H_Kmh` | km/h | Crosswind cực đại trong cửa sổ 3 giờ |
| `Wind_Gust_Estimate_Kmh` | km/h | Tốc độ gió cao nhất trong 3 giờ |

> **Lưu ý**: Crosswind tính theo đường băng mặc định: SGN `25L` (250°), HAN `11L` (110°), DAD `35L` (350°). Nếu sân bay đang dùng đường băng ngược chiều, crosswind thực tế sẽ khác.

### 3.3 Đặc trưng biến động thời gian

| Cột | Đơn vị | Mô tả |
|------|---------|--------|
| `Temp_Change_1H_C` | °C | Chênh lệch nhiệt độ 1 giờ |
| `Temp_Change_3H_C` | °C | Chênh lệch nhiệt độ 3 giờ |
| `Pressure_Change_3H_Hpa` | hPa | Chênh lệch áp suất 3 giờ (dấu hiệu front thời tiết) |
| `Precip_Cumsum_1H_Mm` | mm | Tổng mưa 1 giờ |
| `Precip_Cumsum_3H_Mm` | mm | Tổng mưa 3 giờ |
| `Precip_Cumsum_6H_Mm` | mm | Tổng mưa 6 giờ |

### 3.4 Cờ rủi ro nhị phân (0/1)

| Cột | Ngưỡng kích hoạt | Ý nghĩa |
|------|-------------------|---------|
| `Is_Rain` | `precipitation > 0` | Có mưa |
| `Is_Heavy_Rain` | `precipitation >= 5 mm/h` | Mưa lớn |
| `Is_Strong_Wind` | `wind_speed >= 30 km/h` | Gió mạnh |
| `Is_Gale_Wind` | `wind_speed >= 50 km/h` | Gió bão |
| `Is_Low_Visibility` | `visibility < 5000 m` | Tầm nhìn kém |
| `Is_Fog` | `visibility < 1000 m` và `humidity > 90%` | Sương mù |
| `Is_Freezing` | `temperature <= 5°C` | Nguy cơ đóng băng |
| `Is_Extreme_Heat` | `temperature >= 35°C` | Nhiệt độ cực đoan |
| `Is_Thunderstorm_Risk` | `cloudcover > 80%` và `precipitation > 0` | Nguy cơ dông bão |

### 3.5 Đặc trưng đường băng

| Cột | Giá trị | Mô tả |
|------|----------|--------|
| `Runway_Wet_Risk` | 0 / 1 / 2 | 0=khô, 1=ướt (mưa nhẹ), 2=ướt nặng (mưa to) |
| `Runway_Ice_Risk` | 0 / 1 / 2 | 0=không, 1=có mưa + tại đóng băng, 2=mưa to + đóng băng |

> Điều kiện đóng băng: `temperature <= 5°C` và có mưa.

### 3.6 Điểm rủi ro tổng hợp

| Cột | Giá trị | Công thức |
|------|----------|----------|
| `Weather_Delay_Risk_Score` | 0 – 5 | Tổng cộng các rủi ro: heavy rain + strong wind + gale×2 + low vis + fog×2 + ice risk + thunderstorm. Cắt trần ở 5. |

---

## 4. Cách join Weather với Flight Data

### 4.1 Nguyên tắc

Dữ liệu thời tiết là **hourly**, trong khi sự kiện chuyến bay có thể xảy ra bất kỳ phút nào. Để join, ta làm tròn thời gian chuyến bay xuống **giờ đầy đủ gần nhất** (“floor”) hoặc **làm tròn thường** (“round”), sau đó merge trên `(Airport, time_hour)`.

### 4.2 Ví dụ code (pandas)

```python
import pandas as pd

# --- 1. Đọc dữ liệu ---
weather = pd.read_csv(
    "Data crawl/Silver_layer/Features/weather_features_hourly.csv",
    parse_dates=["time"]
)

flights = pd.read_csv(
    "Data crawl/Silver_layer/Departure/sgn_flights_departure_silver_layer.csv",
    parse_dates=["Actual_DateTime"]
)

# --- 2. Làm tròn thời gian chuyến bay về giờ ---
# Cách A: Floor (về đầu giờ) — phù hợp nếu muốn lấy thời tiết đã diễn ra trước sự kiện
flights["time_hour"] = flights["Actual_DateTime"].dt.floor("H")

# Cách B: Round (về giờ gần nhất) — phù hợp nếu muốn xấp xỉ trung bình
# flights["time_hour"] = flights["Actual_DateTime"].dt.round("H")

# --- 3. Chuẩn bị key ---
weather["time_hour"] = weather["time"]

# --- 4. Merge ---
merged = flights.merge(
    weather,
    left_on=["Airport", "time_hour"],
    right_on=["Airport", "time_hour"],
    how="left"
)

# Kiểm tra missing
missing_ratio = merged["Weather_Delay_Risk_Score"].isna().mean()
print(f"Missing weather data: {missing_ratio:.2%}")
```

### 4.3 Ví dụ code (pd.merge_asof — chính xác hơn)

`merge_asof` tự động tìm mẫu weather gần nhất theo thời gian, không cần làm tròn thủ công:

```python
weather_sorted = weather.sort_values("time")
flights_sorted = flights.sort_values("Actual_DateTime")

merged = pd.merge_asof(
    flights_sorted,
    weather_sorted,
    left_on="Actual_DateTime",
    right_on="time",
    by="Airport",
    direction="backward",   # lấy mẫu weather trước thời điểm bay
    tolerance=pd.Timedelta("1H")
)
```

> `direction="backward"`: lấy thời tiết quan trắc đã có trước khi bay.  
> `direction="forward"`: lấy thời tiết quan trắc sau khi bay (dự báo).  
> `direction="nearest"`: lấy giờ gần nhất.

### 4.4 Join cho cả Departure và Arrival

Mỗi sự kiện (departure hoặc arrival) nên join với weather của sân bay xảy ra sự kiện đó:

```python
# Departure → join weather của sân bay xuất phát tại thời điểm departure
dep_weather = dep_df.merge(weather, left_on=["Airport", "time_hour"], right_on=[...])

# Arrival → join weather của sân bay đến tại thời điểm arrival
arr_weather = arr_df.merge(weather, left_on=["Airport", "time_hour"], right_on=[...])
```

### 4.5 Join với cửa sổ thời gian (window join)

Nếu muốn lấy đặc trưng thời tiết trong **3 giờ trước** sự kiện (ví dụ: mưa tích lũy trước khi bay):

```python
# Tạo cửa sổ 3 giờ trước sự kiện
flights["window_start"] = flights["Actual_DateTime"] - pd.Timedelta(hours=3)

# Dùng merge_asof với cả 2 boundary
# Hoặc đơn giản dùng cột `Precip_Cumsum_3H_Mm` đã tính sẵn trong weather_features
```

> Các cột `Precip_Cumsum_3H_Mm`, `Crosswind_Max_3H_Kmh`, `Wind_Gust_Estimate_Kmh` đã tính sẵn trong cửa sổ 3 giờ, nên bạn không cần tự tính lại.

---

## 5. Lưu ý quan trọng

| Vấn đề | Khuyến nghị |
|--------|-------------|
| **Missing weather** | Nếu `merge_asof` với `tolerance=1H` không tìm thấy mẫu weather, kết quả sẽ là NaN. Kiểm tra kỵ missing rate trước khi huấn luyện. |
| **Múi giờ** | Weather data đã ở GMT+7 (Asia/Bangkok). Flight data cũng nên đảm bảo đồng nhất múi giờ trước khi join. |
| **Crosswind đường băng** | Crosswind tính theo đường băng mặc định. Nếu sân bay đang dùng đường băng ngược chiều (ví dụ: 07L thay vì 25L ở SGN), crosswind thực tế sẽ khác. Có thể tính lại crosswind bằng cách lấy heading từ `Arrival_Runway` / `Departure_Runway` nếu cần chính xác cao. |
| **Tên cột** | Để tránh conflict khi join nhiều bảng, nên đổi tên cột weather sau merge (ví dụ: `temperature` → `Dep_Temperature`). |
| **Scheduled vs Actual** | Nếu phân tích delay, nên join theo **Scheduled_DateTime** (để biết điều kiện thời tiết lúc lên lịch). Nếu phân tích congestion/safety, join theo **Actual_DateTime**. |

---

## 6. Chạy lại pipeline

Nếu bạn crawl thêm dữ liệu thời tiết mới (ví dụ: kéo dài đến tháng 6/2026), chỉ cần:

```bash
python "Source code/weather_preprocessing.py"
```

File `weather_features_hourly.csv` sẽ được regenerate tự động.
