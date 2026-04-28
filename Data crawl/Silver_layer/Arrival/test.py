import pandas as pd

csv_path = "/Users/nguyenhung/PycharmProjects/DS108-AeroDelay/Data crawl/Silver_layer/Arrival/han_flights_arrival_silver_layer.csv"

df = pd.read_csv(csv_path, encoding="utf-8-sig")
df["Crawl_Date"] = pd.to_datetime(df["Crawl_Date"]).dt.strftime("%Y-%m-%d")

# Đếm tổng số chuyến mỗi ngày
daily_count = (
    df.groupby("Crawl_Date")
      .size()
      .reset_index(name="total_flights")
      .sort_values("Crawl_Date")
)

median_count = daily_count["total_flights"].median()

# Ngày bị xem là ít bất thường nếu thấp hơn 70% median
threshold = median_count * 0.7

abnormal_days = daily_count[daily_count["total_flights"] < threshold]

print("===== Số chuyến mỗi ngày =====")
print(daily_count.to_string(index=False))

print("\n===== Ngày ít chuyến bất thường =====")
print(f"Median số chuyến/ngày: {median_count}")
print(f"Ngưỡng cảnh báo 70% median: {threshold:.1f}")
print(abnormal_days.to_string(index=False))