import requests
import pandas as pd

# Khai báo các thông số chung
airports = {
    "tan_son_nhat": (10.8188, 106.6519),
    "da_nang": (16.0439, 108.1995),
    "noi_bai": (21.2212, 105.8072)
}

start_date = "2025-12-15"
end_date = "2026-03-16"
timezone = "Asia/Bangkok"

# 1. Tách riêng các features cho từng API
features_archive = [
    "temperature_2m", "precipitation", "cloudcover",
    "windspeed_10m", "winddirection_10m", 
    "surface_pressure", "relative_humidity_2m",
    "dew_point_2m", "weather_code", "cape",
    "lifted_index", "cloud_cover_low"
]

features_forecast = [
    "visibility" # Chỉ lấy visibility từ bộ forecast để tiết kiệm băng thông
]

url_archive = "https://archive-api.open-meteo.com/v1/archive"
url_forecast = "https://historical-forecast-api.open-meteo.com/v1/forecast"

all_data = []

for airport, (lat, lon) in airports.items():
    print(f"Đang tải dữ liệu cho {airport}...")

    # --- BƯỚC 1: Gọi API Archive ---
    params_archive = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(features_archive),
        "timezone": timezone
    }
    res_archive = requests.get(url_archive, params=params_archive).json()

    # --- BƯỚC 2: Gọi API Historical Forecast ---
    params_forecast = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(features_forecast),
        "timezone": timezone,
        "models": "best_match" 
    }
    res_forecast = requests.get(url_forecast, params=params_forecast).json()

    # --- BƯỚC 3: Xử lý và Ghép Data ---
    if "hourly" in res_archive and "hourly" in res_forecast:
        
        # Chuyển đổi thành DataFrame
        df_arc = pd.DataFrame(res_archive["hourly"])
        df_arc["time"] = pd.to_datetime(df_arc["time"])
        
        df_fcst = pd.DataFrame(res_forecast["hourly"])
        df_fcst["time"] = pd.to_datetime(df_fcst["time"])
        
        # Ghép 2 bảng lại với nhau dựa trên cột 'time' (khớp thời gian tuyệt đối)
        df_merged = pd.merge(df_arc, df_fcst, on="time", how="inner")
        
        # Gán tên sân bay và đưa vào list tổng
        df_merged["airport"] = airport
        all_data.append(df_merged)
        
    else:
        print(f"Lỗi API ở {airport}. Kiểm tra lại params.")

# Gộp tất cả sân bay lại thành 1 Dataset duy nhất
dataset = pd.concat(all_data, ignore_index=True)

# Đổi tên cột cho gọn gàng (tuỳ chọn)
dataset.rename(columns={
    "temperature_2m": "temperature",
    "windspeed_10m": "wind_speed",
    "winddirection_10m": "wind_direction",
    "surface_pressure": "pressure",
    "relative_humidity_2m": "humidity"
}, inplace=True)

# Lưu file
dataset.to_csv("airport_weather_hourly_merged.csv", index=False)

print("\nĐã lưu file thành công!")
print(dataset.head())
