# Aviation Weather Operational EDA Review

## Mục tiêu

Phần EDA weather được chỉnh lại theo hướng **khí tượng hàng không trong vận hành bay**. Các biến visibility, mưa, gió, hướng gió và runway condition phải được diễn giải thành khả năng ảnh hưởng đến takeoff/landing, runway selection, spacing/holding, braking, pilot workload hoặc delay propagation. Không nên chỉ đọc như khí tượng thủy văn riêng lẻ.

## Căn cứ và giới hạn

- Gió/crosswind trong phần hàng không nên dùng knot. `1 kt = 1.852 km/h`.
- Visibility được đọc thêm theo statute mile: `3 SM ~= 4,828 m`, `1 SM ~= 1,609 m`.
- METAR/flight category chuẩn cần ceiling, RVR, gust và weather code. Dataset hiện tại thiếu các trường này, nên chỉ dùng cụm `visibility-only IFR-like`, không khẳng định IFR/MVFR đầy đủ.
- Crosswind đang tính theo runway heading mặc định: SGN `250°`, HAN `110°`, DAD `350°`. Crosswind magnitude không đổi nếu runway đảo chiều, nhưng headwind/tailwind và runway selection thì có đổi. Vì vậy hướng gió phải được phân tích riêng.
- Cleaning đã được sửa để không IQR-clip `visibility`, `precipitation`, `wind_speed`. Các biến cực trị này là tín hiệu vận hành, không phải outlier nên xóa.

## Feature đã bổ sung

- `Wind_Kt`, `Crosswind_Kt`, `Headwind_Kt`.
- `Wind_Sector`, `Wind_Runway_Relative_Angle_Deg`, `Is_Tailwind_Default_Runway_5kt`.
- `Visibility_SM`, `Visibility_Deficit_5KM_M`, `Visibility_Deficit_3SM_M`, `Visibility_Severity_Score`.
- `Is_Crosswind_10kt`, `Is_Crosswind_15kt`, `Is_Crosswind_20kt`.
- `Is_Below_3SM_Visibility`, `Is_Below_1SM_Visibility`.
- `Aviation_Operational_Risk_Score`.

## Visibility: không chỉ nhìn ngưỡng 10 km

| Airport | Hours | Vis < 10 km | Vis < 5 km | Vis < 3 SM | Vis < 1 SM |
|---|---:|---:|---:|---:|---:|
| DAD | 2,208 | 134 (6.07%) | 9 (0.41%) | 8 (0.36%) | 0 |
| HAN | 2,208 | 3 (0.14%) | 0 | 0 | 0 |
| SGN | 2,208 | 19 (0.86%) | 5 (0.23%) | 5 (0.23%) | 0 |

DAD đúng là có nhiều giờ visibility dưới `10 km` nhất, nhưng phần lớn là giảm nhẹ. Khi chuyển sang ngưỡng hàng không `< 3 SM`, chỉ còn 8 giờ. Vì vậy không nên nói DAD bị ảnh hưởng khai thác nặng do tầm nhìn nếu chỉ dựa trên ngưỡng `10 km`.

## Raw visibility tương quan âm với risk có sai không?

Không. Raw `visibility` càng cao thì điều kiện càng tốt, nên correlation với risk có thể âm. Trong output mới:

- `visibility`: corr với operational risk = `-0.439`.
- `Visibility_Severity_Score`: `+0.201`.
- `Is_Low_Visibility`: `+0.201`.
- `Visibility_Deficit_5KM_M`: `+0.188`.
- `Visibility_Deficit_3SM_M`: `+0.179`.

Kết luận: tầm nhìn vẫn quan trọng, nhưng không nên đọc raw visibility như feature cùng chiều với risk. Khi báo cáo, dùng deficit/threshold flags để diễn giải tác động.

## Humidity và visibility có giải thích được sương mù không?

Phần này chỉ nói về quan hệ `humidity` với `visibility`, không phải quan hệ với delay risk. Kết luận hiện tại: không nên kết luận mạnh. Tương quan `visibility` với `humidity` theo sân bay rất yếu:

- DAD: `-0.091` trên toàn bộ data; non-capped subset `-0.129`.
- HAN: `-0.078` trên toàn bộ data; non-capped subset `-0.059`.
- SGN: `-0.068` trên toàn bộ data; non-capped subset `+0.096`.

Visibility cap là lý do quan trọng: SGN cap `96.0%`, HAN `92.8%`, DAD `62.4%`. Nhưng khi bỏ capped values, quan hệ vẫn yếu/không ổn định. Vì vậy nhận xét “độ ẩm cao làm giảm tầm nhìn” không được dataset này thể hiện rõ. Không nên dùng humidity làm proxy trực tiếp cho fog/low visibility. Dataset thiếu dew point, ceiling/cloud base, METAR weather code, RVR và fog observation; nên EDA chỉ nên xem humidity là biến phụ hoặc interaction feature.

## Crosswind và hướng gió

| Airport | Dominant wind sectors | Hours xwind >=10 kt | Hours xwind >=15 kt | Max xwind |
|---|---|---:|---:|---:|
| DAD | NE 24.68%, E 21.33%, N 15.53% | 12 (0.54%) | 0 | 11.22 kt |
| HAN | SE 36.78%, NE 27.45%, S 10.51% | 71 (3.22%) | 0 | 14.41 kt |
| SGN | SE 30.39%, N 16.39%, S 12.50% | 1 (0.05%) | 0 | 10.15 kt |

Insight mới: nếu nói về gió, HAN đáng chú ý hơn DAD. HAN có gió chủ đạo SE/NE và số giờ crosswind `>= 10 kt` cao nhất, nhưng chưa có giờ `>= 15 kt`. Do đó nên viết là “mốc cần theo dõi cho runway selection/pilot workload”, không viết là “gió ngang mạnh gây ảnh hưởng nghiêm trọng”.

## HAN Jan-Mar: không phải visibility, mà là rain/wet runway/crosswind

| Month | Rain hours | Rain rate | Heavy rain hours | Precip sum | Wet runway hours | Operational risk mean |
|---|---:|---:|---:|---:|---:|---:|
| 2026-01 | 117 | 15.73% | 1 | 52.0 mm | 117 | 0.335 |
| 2026-02 | 151 | 22.47% | 0 | 51.6 mm | 151 | 0.446 |
| 2026-03 | 46 | 11.98% | 0 | 15.8 mm | 46 | 0.255 |

Nhận xét “tháng 3 HAN vẫn ổn” phù hợp với data: visibility không xấu, mưa tháng 3 giảm so với Jan-Feb. Điểm đáng viết trong báo cáo là Jan-Feb của HAN có nhiều rain/wet runway hours, đặc biệt tháng 2 có rain rate `22.47%`.

## Case xấu theo từng sân bay

- SGN `2025-12-25 18:00`: visibility `4,400 m` (`2.73 SM`), precipitation `13.9 mm/h`, runway wet risk `2`, crosswind `1.55 kt`. Tác động chính: approach visibility + runway wet/braking, không phải gió ngang.
- HAN `2026-01-01 05:00`: visibility tốt/capped, precipitation `6.6 mm/h`, runway wet risk `2`. Tác động chính: heavy rain + wet runway.
- DAD worst cases trong score mới chủ yếu là light rain + crosswind gần/vượt `10 kt`, không phải visibility nghiêm trọng.

## Kết luận viết lại cho EDA

- DAD: visibility dưới `10 km` xuất hiện nhiều, nhưng severe visibility rất hiếm; không nên overstate.
- HAN: visibility ổn, nhưng rain/wet runway Jan-Feb và crosswind `>= 10 kt` là pattern cần nói.
- SGN: ít giờ xấu hơn DAD theo tỷ lệ, nhưng có case xấu rõ về low visibility + heavy rain + wet runway; do traffic lớn nên cần tính flight exposure.
- Visibility raw âm với risk là đúng logic; dùng visibility deficit/threshold để trình bày tác động.
- Hướng gió phải đi kèm crosswind/headwind, vì crosswind không nói hết runway selection và tailwind risk.
