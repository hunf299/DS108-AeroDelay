# EDA Weather Overhaul Change Log

## Vấn đề từ review và cách đã sửa

| Vấn đề review | Đã kiểm tra | Đã sửa ở file nào | Kết quả |
|---|---|---|---|
| EDA giống khí tượng thủy văn, chưa nói ảnh hưởng vận hành bay | Đổi cách đọc sang visibility threshold, crosswind knot, runway wet, case xấu theo sân bay | `Source code/weather_preprocessing.py`, `Source code/eda_weather_plan_notebook.ipynb`, `10_aviation_weather_operational_review.md` | Thêm `Aviation_Operational_Risk_Score` và diễn giải theo approach visibility, runway wet, runway selection, pilot workload |
| Chưa phân tích hướng gió | Tính wind sector theo 8 hướng và theo airport/month | `weather_preprocessing.py`, notebook, `06_wind_direction_sector_by_airport*.csv` | HAN nổi bật với SE 36.78% và NE 27.45%; DAD chủ đạo NE/E/N; SGN chủ đạo SE |
| Gió trong hàng không nên dùng knot, không chỉ km/h | Quy đổi km/h sang knot | `weather_preprocessing.py`, notebook | Thêm `Wind_Kt`, `Crosswind_Kt`, `Headwind_Kt`, `Wind_Gust_Estimate_Kt`, `Crosswind_Max_3H_Kt` |
| Crosswind 10 kt cần được nhắc đến | Tính xwind `>=10/15/20 kt` theo giờ và flight exposure | `weather_preprocessing.py`, notebook, `06_crosswind_operational_threshold_summary.csv` | HAN có 71 giờ `>=10 kt`, DAD 12, SGN 1; không có `>=15 kt` |
| Quá tập trung DAD | Tính worst cases riêng cho DAD/HAN/SGN | notebook, `06_worst_operational_weather_cases_by_airport.csv`, `10_aviation_weather_operational_review.md` | SGN có case xấu low visibility + heavy rain + wet runway; HAN có rain/wet runway; DAD severe visibility hiếm |
| HAN tháng 1-3 có mưa đặc biệt | Tính monthly precip/rain/wet runway cho từng airport | notebook, `06_monthly_precip_operational_profile.csv`, `06_han_precip_jan_mar_operational_note.csv` | HAN Jan: 117 rain hours; Feb: 151 rain hours; Mar: 46 rain hours. Tháng 3 ổn hơn Jan-Feb |
| Visibility correlation với risk bị âm, trong khi tầm nhìn quan trọng | So sánh raw visibility với deficit/threshold features | `weather_preprocessing.py`, notebook, `06_visibility_correlation_direction_check.csv` | Raw visibility corr âm là đúng vì visibility càng cao càng tốt; `Visibility_Severity_Score` và deficit có corr dương |
| Nhận xét humidity-visibility bị lệch sang delay risk | Tính correlation all vs non-capped theo airport và sửa đúng phạm vi biểu đồ | `Source code/eda_weather_plan_notebook.ipynb`, `03_visibility_humidity_capped_sensitivity.csv`, `10_aviation_weather_operational_review.md` | Kết luận mới: đây là phần humidity vs visibility; capped là một lý do lớn, nhưng non-capped corr vẫn yếu; humidity không đủ làm proxy trực tiếp cho fog/visibility |
| Low visibility DAD bị mất trong output mới | Kiểm tra Bronze/Silver/Silver_layer_2 và audit cleaning | `Source code/weather_preprocessing.py`, `Data crawl/Silver_layer_2/Audit/audit_weather_cleaning_actions.csv` | Phát hiện IQR clipping đã đẩy low visibility DAD lên 14,780 m; đã tắt IQR clip cho `visibility`, `precipitation`, `wind_speed` |
| Notebook EDA weather chưa được cập nhật | Sửa notebook trực tiếp, clear output cũ, chạy lại notebook | `Source code/eda_weather_plan_notebook.ipynb` | Notebook ưu tiên `Silver_layer_2`, thêm section 6.2, compile và chạy không lỗi |

## File đã thay đổi

- `Source code/weather_preprocessing.py`: thêm aviation features, wind sector, visibility deficit, operational score.
- `Source code/weather_preprocessing.py`: sửa cleaning để không IQR-clip event variables `visibility`, `precipitation`, `wind_speed`.
- `Source code/eda_weather_plan_notebook.ipynb`: thêm aviation-oriented overview, ưu tiên schema mới, thêm section 6.2, thêm output CSV mới.
- `weather_preprocessing.md`: thêm ghi chú aviation EDA update.
- `Data crawl/Silver_layer/Audit/eda_weather_reports/10_aviation_weather_operational_review.md`: viết lại report insight theo hướng hàng không.
- `Data crawl/Silver_layer/Audit/eda_weather_reports/11_eda_weather_overhaul_changes.md`: file tổng quan này.

## File report mới được sinh

- `03_visibility_humidity_capped_sensitivity.csv`
- `06_wind_direction_sector_by_airport.csv`
- `06_wind_direction_sector_by_airport_month.csv`
- `06_monthly_precip_operational_profile.csv`
- `06_han_precip_jan_mar_operational_note.csv`
- `06_visibility_correlation_direction_check.csv`
- `06_worst_operational_weather_cases_by_airport.csv`

## Validation đã chạy

- Chạy lại `python "Source code/weather_preprocessing.py" --project-root "."` thành công.
- Kiểm tra output mới có các cột `Wind_Sector`, `Crosswind_Kt`, `Visibility_Deficit_5KM_M`, `Visibility_Severity_Score`, `Aviation_Operational_Risk_Score`.
- Kiểm tra audit cleaning mới: `IQR_Clipped = 0` cho `visibility`, `precipitation`, `wind_speed`; DAD phục hồi `134` giờ visibility `< 10 km`.
- Compile tất cả code cells trong `eda_weather_plan_notebook.ipynb`: `syntax_errors = 0`.
- Chạy lại notebook bằng runner nội bộ: 31 code cells, không lỗi.
