import requests
import pandas as pd

url = "https://archive-api.open-meteo.com/v1/archive"

# tọa độ sân bay
airports = {
    "tan_son_nhat": (10.8188, 106.6519),
    "da_nang": (16.0439, 108.1995),
    "noi_bai": (21.2212, 105.8072)
}

start_date = "2025-12-15"
end_date = "2026-03-16"

# feature weather
features = [
    "temperature_2m",
    "precipitation",
    "cloudcover",
    "visibility",
    "windspeed_10m",
    "winddirection_10m",
    "surface_pressure",
    "relativehumidity_2m"
]

all_data = []

for airport, (lat, lon) in airports.items():

    print(f"Downloading weather for {airport}...")

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(features),
        "timezone": "Asia/Bangkok"
    }

    response = requests.get(url, params=params)
    data = response.json()

    if "hourly" not in data:
        print("API error:", data)
        continue

    hourly = data["hourly"]

    df = pd.DataFrame({
        "time": pd.to_datetime(hourly["time"]),
        "temperature": hourly["temperature_2m"],
        "precipitation": hourly["precipitation"],
        "cloudcover": hourly["cloudcover"],
        "visibility": hourly["visibility"],
        "wind_speed": hourly["windspeed_10m"],
        "wind_direction": hourly["winddirection_10m"],
        "pressure": hourly["surface_pressure"],
        "humidity": hourly["relativehumidity_2m"]
    })

    df["airport"] = airport

    all_data.append(df)

# gộp dữ liệu
dataset = pd.concat(all_data, ignore_index=True)

# lưu file
dataset.to_csv("airport_weather_hourly.csv", index=False)

print("Done!")
print(dataset.head())