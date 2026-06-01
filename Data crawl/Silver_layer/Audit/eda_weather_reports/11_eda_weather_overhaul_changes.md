# EDA Weather Overhaul Change Log

## Vấn Đề Đã Resolve

| Vấn đề | File chỉnh | Kết quả |
|---|---|---|
| Bronze weather crawl lại có cột mới nhưng Silver không giữ | `Source code/weather_preprocessing.py` | Silver weather tăng lên 69 cột, giữ `dew_point_2m`, `weather_code`, `cape`, `lifted_index`, `cloud_cover_low` |
| Weather EDA vẫn lưu report vào `Silver_layer` | `Source code/eda_weather_plan_notebook.ipynb` | EDA artifacts hiện lưu vào `Data crawl/Silver_layer_2/Audit/eda_weather_reports/` |
| Fog/visibility không thể chỉ giải thích bằng humidity | `weather_preprocessing.py`, notebook | Thêm `Dew_Point_Spread_C`, `Is_Radiation_Fog_Risk`; fog-risk được tách khỏi humidity đơn lẻ |
| Dataset thiếu ceiling proxy | `weather_preprocessing.py`, notebook | Thêm `Is_Low_Ceiling_Risk` từ `cloud_cover_low` |
| Thunderstorm risk cũ quá thô | `weather_preprocessing.py`, notebook | Thêm `Is_Severe_Convection_Risk` từ `cape` + `lifted_index` |
| Runway operation chưa nối với tailwind/wet runway | `weather_preprocessing.py`, notebook | Thêm `Tailwind_Default_Runway_Kt` và `Forced_Runway_Swap_Risk` |
| Report weather bị lỗi tiếng Việt/mojibake | `10_aviation_weather_operational_review.md`, file này | Viết lại bằng tiếng Việt có dấu |

## Output Mới

- `06_new_weather_field_coverage.csv`: xác nhận tất cả cột weather mới có missing rate `0%`.
- `06_new_weather_feature_rates_by_airport.csv`: tỷ lệ fog/ceiling/convection/runway-swap risk theo sân bay.
- `06_new_weather_feature_corr_with_risk.csv`: tương quan của feature mới với `Aviation_Operational_Risk_Score`.
- `06_new_weather_fog_risk_cases.csv`: các case fog-risk tiêu biểu.
- `06_new_weather_ceiling_convection_cases.csv`: các case low ceiling / convection tiêu biểu.
- `figures/06_new_weather_feature_rates.png`: biểu đồ tỷ lệ trigger feature mới.

## Validation Đã Chạy

- `python "Source code/weather_preprocessing.py" --project-root "." --silver-layer-name "Silver_layer_2"` chạy thành công.
- Weather EDA notebook chạy thành công `32` code cells, không lỗi.
- Silver weather có `6,624` dòng, `69` cột trước khi notebook tạo helper columns.
- Final EDA summary: `Risk > 0 = 42.84%`, `Risk >= 2 = 20.52%`, best precipitation lag overall `0h` với corr `0.404`.
