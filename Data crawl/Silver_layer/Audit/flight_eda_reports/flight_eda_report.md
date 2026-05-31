# Flight EDA Report

## Phạm vi

Notebook `Source code/flight_eda.ipynb` dùng để kiểm tra phần flight preprocessing và feature engineering sau khi dữ liệu được đưa vào `Data crawl/Silver_layer_2`. Notebook giữ nguyên output Gold tại `Data crawl/Gold_layer` và lưu toàn bộ bảng/biểu đồ EDA vào `Data crawl/Silver_layer_2/Audit/flight_eda_reports/`.

Phần visual mới đã được thêm ở mục `6.1. Visual diagnostics for flight preprocessing and feature engineering`. Các hình nằm trong `flight_eda_reports/figures/`.

## Data Lineage

Silver_layer_2 hiện có đủ 6 file airport-mode:

- Arrival: SGN `36,699`, HAN `24,899`, DAD `12,573`.
- Departure: SGN `36,735`, HAN `28,502`, DAD `12,521`.
- Tổng Silver flight rows: `151,929`.

Gold per-airport giữ nguyên số dòng 1:1 với Silver_layer_2, `silver_to_gold_delta = 0` cho cả 6 file. `master_aero_features_gold.csv` có `148,520` dòng, thấp hơn tổng Silver vì master chỉ giữ các dòng đủ điều kiện tính tail-rotation và propagation features.

Biểu đồ `21_row_lineage_by_airport_mode.png` cho thấy không có mất dòng từ Silver sang Gold per-airport. Biểu đồ `21_bronze_to_silver_delta.png` cho thấy các dòng bị loại chủ yếu xảy ra từ Bronze sang Silver, lớn nhất là SGN departure `-54`, sau đó SGN arrival `-22`, HAN arrival `-21`, DAD departure `-8`, DAD arrival `-2`, HAN departure `-1`.

## Preprocessing Audit Insights

Arrival time semantics đã parse được `100%` actual landing datetime cho SGN, HAN, DAD. Source profile đúng theo schema: SGN/HAN dùng `FR_SOURCE`, DAD dùng `DAD_SOURCE`.

Các vấn đề audit chính theo `21_visual_issue_summary.csv`:

- `master_excluded_departure`: `2,972` dòng.
- `departure_without_arrival`: `619` dòng.
- `arrival_without_departure`: `476` dòng.
- `master_excluded_arrival`: `329` dòng.
- `same_origin_actions`: `84` dòng.
- `dedup_rows_dropped`: `70` dòng.

Nhận xét quan trọng: vấn đề lớn nhất không nằm ở dedup mà nằm ở feature eligibility và liên kết arrival/departure. Dòng bị drop do dedup chỉ `70`, trong khi dòng không đủ điều kiện vào master là `3,301`. Vì vậy khi giải thích vì sao master ít dòng hơn Silver, cần trỏ vào `feature_eligibility_audit.csv`, không chỉ nói do preprocessing drop.

Dedup audit hiện có `70` dòng, chủ yếu SGN departure `54` dòng, tất cả theo rule `same_day_150m_window`. Missing-link audit gồm `619` departure without arrival và `476` arrival without departure. Same-origin audit có `84` dòng, xuất hiện ở SGN/HAN; DAD không có same-origin anomaly trong audit hiện tại.

Aircraft swap matching có `24,118` matched pairs nhưng swap rate là `0%`. Đây là tín hiệu cần review vì với dữ liệu vận hành thật, aircraft swap thường không hoàn toàn bằng 0. Có thể rule matching/tail normalization đang quá bảo thủ hoặc swap flag chưa được kích hoạt đúng.

## Traffic Pattern Visual Insights

`22_daily_flight_volume_lines.png` và `22_hourly_traffic_profile.png` cho thấy traffic không phân bố đều theo giờ. Peak-hour summary:

- SGN departure peak: 11h `2,270` chuyến, 9h `2,175`, 7h `1,959`.
- SGN arrival peak: 16h `1,983`, 10h `1,965`, 17h `1,947`.
- HAN arrival peak: 17h `1,471`, 21h `1,439`, 11h `1,406`.
- DAD departure peak: 12h `972`, 18h `949`, 15h `929`.
- DAD arrival peak: 12h `932`, 13h `911`, 11h `835`.

Một vấn đề cần audit: `HAN departure` có nhóm `hour = NaN` với `1,992` dòng trong bảng peak summary. Điều này cho thấy một phần departure thiếu hoặc không parse được `Scheduled_Time/Event_Time`. Nhóm này có thể làm sai feature theo giờ như peak-hour, airport load, rolling count, và temporal split nếu không được xử lý rõ.

## Route, Runway, Và Category

Route concentration cho thấy mạng bay không cân bằng:

- DAD: top 3 route chiếm `62.51%` trong top 15 route.
- HAN: top 3 route chiếm `54.92%`.
- SGN: top 3 route chiếm `48.96%`.

Điều này quan trọng cho modeling vì các route trục chính có thể dominate signal delay/traffic load. Không nên đánh giá model chỉ bằng global average; cần xem theo airport-route hoặc ít nhất theo origin airport.

Runway distribution rất lệch theo runway mặc định:

- DAD departure `35R`: `99.11%`.
- SGN arrival `25R`: `98.40%`.
- SGN departure `25L`: `98.29%`.
- HAN departure `11R`: `97.55%`.
- HAN arrival `11L`: `95.79%`.
- DAD arrival `35L`: `95.59%`.

Biểu đồ `23_runway_dominance.png` cho thấy runway feature hiện gần như là airport-mode default hơn là runway-in-use linh hoạt. Vì vậy runway feature vẫn hữu ích để mô tả vận hành mặc định, nhưng chưa đủ để kết luận runway swap/đổi chiều nếu không join thêm weather wind/tailwind hoặc ATC runway-in-use thực tế.

Category mix cho thấy passenger vẫn là nhóm chính, nhưng non-passenger không nên drop sớm:

- SGN: passenger khoảng `96.32%` arrival và `96.55%` departure.
- HAN: passenger khoảng `90.87%` arrival và `90.74%` departure.
- DAD: passenger khoảng `91.45%` arrival và `93.75%` departure.

Nhóm cargo/general aviation/military/non-categorized tuy nhỏ nhưng vẫn chiếm runway/airspace capacity, nên nên giữ khi tính airport load, rolling traffic, congestion, hoặc peak-hour exposure.

## Gold Feature Engineering Insights

Gold feature notebook đã đọc `Silver_layer_2` nhưng vẫn xuất Gold vào `Data crawl/Gold_layer`. `feature_eligibility_audit.csv` giải thích chênh lệch master:

- Arrival: `329` dòng thiếu `Actual_Time` hoặc `Tail_Number`.
- Departure: `2,972` dòng thiếu `Scheduled_Time/Event_Time` hoặc `Tail_Number`.
- Tổng excluded khỏi master: `3,301`.

Gold audit hiện ghi:

- Temporal leakage check: `0` violation.
- Imputed link rate trong master: `1.03%`.
- Congested rate: `12.43%`.
- Congested rate theo record type gần cân bằng: Arrival `12.38%`, Departure `12.49%`.

Điều này cho thấy feature engineering không có leakage rõ ràng ở check hiện tại, nhưng chất lượng master đang phụ thuộc nhiều vào completeness của time và tail number.

## Delay, Turnaround, Load Và Outlier

Biểu đồ `25_gold_feature_distributions_clipped.png` và bảng `25_delay_load_outlier_flags.csv` cho thấy nhiều feature có đuôi rất dài:

- `Departure_Delay`: `74,723` dòng valid, `1,882` dòng âm, median `23`, p95 `112`, p99 `210`, max `692`; min trong summary cũ là `-27,256`, bất thường nghiêm trọng.
- `Arrival_Delay`: `148,520` dòng valid, `8,903` dòng âm, median `0`, p95 `15`, p99 `65`, max `625`; min `-685`.
- `Turnaround_Buffer`: `74,301` dòng valid, median `80`, p95 `1,176`, p99 `10,445`, max `121,045`.
- `Airport_Load_Factor`: median `32`, p95 `48`, max `62`.
- `Number_of_Flights_in_Last_Hour`: median `30`, p95 `45`, max `55`.

Nhận xét: `Departure_Delay` âm cực lớn và `Turnaround_Buffer` cực lớn là hai rủi ro chất lượng dữ liệu lớn nhất trước khi training. Cần audit các dòng lệch ngày, timezone, hoặc link arrival-departure sai. Với modeling, nên cân nhắc winsorize/cap delay, tạo outlier flag, hoặc loại các record vượt ngưỡng nghiệp vụ trước khi dùng làm label.

## Các Hình Trực Quan Đã Thêm

- `21_row_lineage_by_airport_mode.png`: so sánh row count Bronze/Silver/Gold theo airport-mode.
- `21_bronze_to_silver_delta.png`: lượng dòng bị loại từ Bronze sang Silver.
- `21_issue_size_dashboard.png`: quy mô các vấn đề audit và eligibility.
- `22_daily_flight_volume_lines.png`: traffic theo ngày.
- `22_hourly_traffic_profile.png`: traffic theo giờ.
- `23_runway_dominance.png`: mức lệch runway mặc định.
- `23_top_departure_routes.png`: top departure routes.
- `24_category_mix_stacked.png`: passenger vs non-passenger/missing.
- `25_gold_feature_distributions_clipped.png`: phân phối delay/load/turnaround sau khi clip p01-p99 để nhìn shape.
- `25_congestion_rate_by_record_type.png`: congested rate theo arrival/departure.

## Kết Luận

Flight EDA hiện cho thấy pipeline giữ được lineage Silver-to-Gold per-airport, nhưng master feature table bị giảm dòng do eligibility của time/tail. Các vấn đề cần ưu tiên trước modeling là: departure thiếu/parse lỗi time, missing arrival-departure link, swap rate bằng 0 bất thường, runway feature quá dominated bởi default runway, và outlier rất lớn trong `Departure_Delay`/`Turnaround_Buffer`. Phần trực quan mới giúp các vấn đề này rõ hơn và có artifact PNG/CSV để đưa vào báo cáo hoặc review notebook.
