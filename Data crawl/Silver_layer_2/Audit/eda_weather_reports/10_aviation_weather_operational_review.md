# Aviation Weather Operational EDA Review

## Mục tiêu

Report này tổng hợp lại phần EDA weather theo hướng **khí tượng hàng không trong vận hành bay**, dựa trên notebook `Source code/eda_weather_plan_notebook.ipynb` và các artifact trong `Data crawl/Silver_layer_2/Audit/eda_weather_reports/`. Trọng tâm không phải mô tả thời tiết riêng lẻ, mà là xác định thời tiết nào có thể ảnh hưởng đến tiếp cận, cất/hạ cánh, chọn runway, spacing, và rủi ro delay.

## Phạm vi dữ liệu

Dữ liệu weather Silver layer 2 hiện có `6,624` bản ghi giờ, gồm đủ `2,208` giờ cho mỗi sân bay `DAD`, `HAN`, `SGN` trong giai đoạn `2025-12-15 00:00:00` đến `2026-03-16 23:00:00`. File đầu vào chính là `Data crawl/Silver_layer_2/Features/weather_features_hourly.csv`; file này hiện có `69` cột thực tế. Notebook có thể tạo thêm vài cột helper trong bộ nhớ để xuất audit.

Các cột mới từ lần crawl weather gần đây đã được giữ lại và phân tích: `dew_point_2m`, `weather_code`, `cape`, `lifted_index`, `cloud_cover_low`. Tất cả các field mới và feature tạo từ chúng đều có missing rate `0%`, nên đủ điều kiện dùng cho EDA và feature engineering.

## Visibility, Humidity, Fog Và Dew-Point Spread

Visibility đã tốt hơn bản crawl cũ nhưng vẫn cần đọc theo ngưỡng hàng không, không chỉ đọc correlation tuyến tính. Tỷ lệ visibility bị cap ở mức cao là `38.22%` tại SGN, `18.25%` tại DAD, và chỉ `0.54%` tại HAN. Vì vậy, SGN vẫn có hiện tượng nhiều giờ visibility rất tốt bị gom về ngưỡng cao; các phân tích tuyến tính với visibility tại SGN cần đọc thận trọng.

DAD là sân bay có visibility xấu nhất trong tập này:

- DAD có `408` giờ dưới `5,000 m` (`18.48%`), `393` giờ dưới `3 SM` (`17.80%`), và `180` giờ dưới `1 SM` (`8.15%`).
- HAN có `131` giờ dưới `5,000 m` (`5.93%`) và `124` giờ dưới `3 SM` (`5.62%`).
- SGN có `50` giờ dưới `5,000 m` (`2.26%`) và `47` giờ dưới `3 SM` (`2.13%`).

Correlation giữa humidity và visibility hiện **đúng chiều vật lý**: DAD `-0.652`, HAN `-0.801`, SGN `-0.502`. Nghĩa là độ ẩm càng cao thì visibility thường càng thấp. Tuy nhiên, riêng SGN khi bỏ các giờ visibility bị cap, correlation chỉ còn `-0.149`, cho thấy quan hệ humidity-visibility tại SGN bị ảnh hưởng bởi trần dữ liệu và không nên dùng humidity đơn lẻ để suy luận fog/delay.

Feature quan trọng hơn humidity là `Dew_Point_Spread_C`. Khi dew-point spread `<= 1.5C`, rủi ro fog/low visibility tăng rõ:

- DAD: `611` giờ trong nhóm `<= 1.5C`, risk mean `2.50`, visibility median `5,740 m`, dưới `3 SM` là `43.21%`, dưới `1 SM` là `22.59%`.
- HAN: `580` giờ, risk mean `1.49`, visibility median `7,630 m`, dưới `3 SM` là `17.07%`.
- SGN: `290` giờ, risk mean `0.54`, visibility median `13,980 m`, dưới `3 SM` là `11.03%`.

Kết luận: fog/visibility nên được mô hình hóa bằng `Dew_Point_Spread_C`, `Is_Radiation_Fog_Risk`, các ngưỡng visibility, và visibility deficit. Không nên giải thích fog chỉ bằng humidity raw.

## Low Ceiling Và Cloud Cover Thấp

`cloud_cover_low` và `Is_Low_Ceiling_Risk` là phần bổ sung quan trọng vì visibility tốt không đồng nghĩa với điều kiện tiếp cận tốt. Low ceiling có thể làm tăng rủi ro approach, holding, hoặc yêu cầu khai thác theo điều kiện thấp hơn dù tầm nhìn mặt đất chưa quá xấu.

HAN nổi bật nhất ở low ceiling:

- HAN có `1,144` giờ `Is_Low_Ceiling_Risk` (`51.81%`).
- DAD có `484` giờ (`21.92%`).
- SGN không có giờ nào bị đánh dấu low ceiling theo threshold hiện tại.

Trong ranking feature mới, `cloud_cover_low` có correlation với operational risk `0.583`, còn `Is_Low_Ceiling_Risk` là `0.520`. Đây là hai tín hiệu mạnh hơn humidity raw và sát hơn với vận hành bay. Với HAN, EDA không cho thấy một đợt visibility xấu diện rộng kiểu “nồm” kéo dài trong tháng 3; thay vào đó vấn đề chính là ceiling thấp và mưa nhẹ/rải rác trong một số giai đoạn.

## WMO Weather Code, Rain Và Wet Runway

`weather_code` là feature mới mạnh nhất trong nhóm weather crawl lại: correlation với operational risk `0.678`, AUC cho risk `>= 2` là `0.881`. Điều này hợp lý vì WMO code đã gói thông tin trạng thái thời tiết hiện tượng, đặc biệt mưa và drizzle.

Theo nhóm WMO:

- DAD: `drizzle` chiếm `859` giờ (`38.90%`), risk mean `2.47`; `rain` chỉ `32` giờ (`1.45%`) nhưng risk mean `4.19` và risk `>= 2` đạt `96.88%`.
- HAN: `cloudy` chiếm `65.13%`, `drizzle` `16.49%`, `rain` `0.77%`; nhóm `rain` có risk mean `4.82` và risk `>= 2` đạt `100%`.
- SGN: `drizzle` `9.56%`, `rain` `1.27%`; rain có precipitation mean `3.95 mm/h`, visibility median `4,610 m`, risk mean `3.50`.

Rain cần đọc cùng `Runway_Wet_Risk`, không chỉ đọc precipitation raw. Một số case SGN có mưa lớn nhưng tần suất thấp, ví dụ `2025-12-25 18:00` precipitation `13.9 mm/h`, visibility `4,480 m`, operational risk `6`; `2026-01-06 17:00` precipitation `6.4 mm/h`, visibility `3,560 m`, risk `6`.

## Tổ Hợp Fog, Low Ceiling, Low Visibility Và Rain

Các tổ hợp thời tiết xấu cho thấy risk tăng mạnh khi nhiều cơ chế cùng xảy ra:

- DAD `fog_risk + low_ceiling + low_visibility_3sm + rain`: `28` giờ, risk mean `5.36`, risk `>= 2` là `100%`.
- DAD `low_ceiling + low_visibility_3sm + rain`: `77` giờ, risk mean `5.03`, risk `>= 2` là `100%`.
- HAN `fog_risk + low_ceiling + low_visibility_3sm + rain`: `27` giờ, risk mean `5.37`, risk `>= 2` là `100%`.

Điểm quan trọng là không nên phân tích từng biến độc lập rồi kết luận đơn lẻ. Với vận hành bay, visibility xấu, ceiling thấp, mưa, và runway wet thường tạo risk theo cơ chế cộng hưởng.

## Wind: Crosswind, Tailwind Và Runway Swap Pressure

Đơn vị chính khi bàn vận hành bay nên là knot. Crosswind trong dataset chưa cực đoan, nhưng ngưỡng `10 kt` vẫn đáng theo dõi vì có thể ảnh hưởng runway selection, spacing, hoặc go-around trong một số điều kiện runway/visibility xấu:

- HAN có `71` giờ crosswind `>= 10 kt` (`3.22%`), max `14.41 kt`.
- DAD có `12` giờ (`0.54%`), max `11.22 kt`.
- SGN có `1` giờ (`0.05%`), max `10.15 kt`.
- Không sân bay nào có crosswind `>= 15 kt` hoặc `>= 20 kt`.

Tailwind theo runway mặc định là chỉ báo vận hành, không phải kết luận runway thực tế. `Tailwind_Default_Runway_Kt` có thể âm/khác chiều do chưa biết runway-in-use thật. Tuy vậy, feature `Forced_Runway_Swap_Risk` hữu ích khi tailwind trên runway mặc định đi kèm runway wet:

- DAD có `49` giờ tailwind `5-8 kt`, trong đó forced swap rate `6.12%`.
- SGN có `20` giờ tailwind `5-8 kt`, nhưng không có forced swap vì runway wet không đồng thời xảy ra trong nhóm này.
- HAN gần như không có tailwind đáng kể theo runway mặc định.

Case đáng chú ý tại DAD: `2026-02-27 17:00-18:00`, tailwind khoảng `5.20-5.89 kt`, có precipitation `0.6-0.7 mm/h`, runway wet, `Forced_Runway_Swap_Risk = 2`, operational risk `6`.

## Convection: CAPE, Lifted Index Và Thunderstorm Proxy

`cape` và `lifted_index` giúp phân biệt risk đối lưu tốt hơn cách cũ chỉ dựa vào cloudcover/rain. Tuy vậy, trong giai đoạn dữ liệu này severe convection có tần suất thấp:

- SGN có `28` giờ `Is_Severe_Convection_Risk` (`1.27%`).
- DAD có `20` giờ (`0.91%`).
- HAN không có giờ severe convection theo threshold hiện tại.

Ở SGN, nhóm lifted index `-5 to -3` có `53` giờ, CAPE mean `1,420`, severe convection rate `52.83%`, risk `>= 2` là `39.62%`. Ở DAD, nhóm CAPE `> 2500` có severe convection rate `41.94%` nhưng risk mean chỉ `0.68`, cho thấy convection feature cần kiểm chứng thêm với flight delay target thực tế, không chỉ operational risk score.

Lưu ý thêm: `Is_WMO_Thunderstorm_Code` và `Is_WMO_Fog_Code` đang zero-variance trong tập này, nghĩa là upstream `weather_code` hiện chưa ghi nhận fog/thunderstorm code trực tiếp. Vì vậy fog và convection nên dùng proxy từ dew-point spread, low cloud, CAPE, lifted index, rain, và visibility.

## Seasonal Và Airport-Specific Notes

DAD là sân bay rủi ro thời tiết cao nhất trong dataset: operational risk mean `1.45`, risk `>= 2` là `37.14%`, rain rate `40.35%`, low visibility rate `18.48%`. Các cụm extreme đáng chú ý gồm `2026-01-26 23:00` đến `2026-01-27 13:00` kéo dài `15` giờ, visibility min `320 m`, risk max `7`.

HAN có risk mean `1.00`, risk `>= 2` `16.98%`. Điểm chính không phải visibility cap mà là low ceiling cao và một số cụm mưa/visibility thấp. Ngày `2026-02-08` có `24` giờ risk `>= 2`, risk max `6`; cụm `2026-02-08 00:00` đến `2026-02-09 11:00` kéo dài `36` giờ.

SGN có risk mean thấp nhất `0.25`, risk `>= 2` `7.43%`, nhưng có các event mưa mạnh ngắn hạn. Ngày `2026-02-26` có `22` giờ risk `>= 2`, với cụm kéo dài `22` giờ, precipitation sum `31.1 mm`, visibility min `1,640 m`, risk max `6`.

## Feature Engineering Guidance

Nên giữ và ưu tiên các feature mới sau:

- `weather_code`: tín hiệu tổng hợp mạnh nhất, nhưng cần one-hot hoặc encode theo nhóm hiện tượng để tránh mô hình hiểu sai tính thứ tự.
- `cloud_cover_low`, `Is_Low_Ceiling_Risk`: rất quan trọng cho HAN và approach condition.
- `Dew_Point_Spread_C`, `Is_Radiation_Fog_Risk`: tốt hơn humidity raw khi mô hình hóa fog/low visibility.
- `Visibility_Deficit_5KM_M`, `Visibility_Deficit_3SM_M`, `Is_Below_3SM_Visibility`, `Is_Below_1SM_Visibility`: nên dùng thay vì chỉ dùng visibility raw.
- `Runway_Wet_Risk`, precipitation cumsum/lag: dùng để bắt tác động tích lũy của mưa lên runway surface.
- `Tailwind_Default_Runway_Kt`, `Forced_Runway_Swap_Risk`: giữ như proxy vận hành, nhưng phải ghi chú đây là theo runway mặc định, chưa phải runway-in-use thực tế.
- `cape`, `lifted_index`, `Is_Severe_Convection_Risk`: giữ để bắt event đối lưu, dù tần suất thấp.

Cần review/drop trước khi train nếu vẫn zero hoặc near-zero variance: `Is_Crosswind_15kt`, `Is_Crosswind_20kt`, `Is_Freezing`, `Is_Gale_Wind`, `Is_Strong_Wind`, `Is_WMO_Fog_Code`, `Is_WMO_Thunderstorm_Code`, `Runway_Ice_Risk`, `Is_Heavy_Rain`, `Is_Extreme_Heat`.

## Lưu Ý Khi Diễn Giải Model

Ranking feature trong EDA đang so với `Aviation_Operational_Risk_Score`, mà risk score này cũng được tạo từ weather rule. Vì vậy ranking này chỉ xác nhận feature engineering có logic nội bộ nhất quán; nó chưa chứng minh feature gây delay thực tế. Bước tiếp theo cần join weather với flight delay target theo giờ/sân bay, kiểm tra leakage theo thời gian, rồi đánh giá feature bằng temporal split.

Các kết luận nên tránh:

- Không kết luận “humidity gây delay” nếu chưa kiểm tra qua flight delay target.
- Không dùng visibility correlation raw để phủ nhận tầm quan trọng của visibility; visibility phải đọc qua ngưỡng `5,000 m`, `3 SM`, `1 SM`, và deficit.
- Không kết luận tailwind thực tế khi chưa có runway-in-use; chỉ gọi là tailwind theo runway mặc định.
- Không tập trung toàn bộ vào DAD: DAD nổi bật về fog/visibility/rain, HAN nổi bật về low ceiling và crosswind `>= 10 kt`, SGN nổi bật về mưa mạnh và convection ngắn hạn.

## Kết Luận

EDA weather sau overhaul đã chuyển từ phân tích khí tượng riêng lẻ sang phân tích cơ chế vận hành bay. Kết quả quan trọng nhất là weather delay risk không chỉ đến từ visibility thấp; nó đến từ tổ hợp visibility, fog-risk, low ceiling, rain/wet runway, wind component, và convection. Với dữ liệu hiện tại, DAD là sân bay có rủi ro thời tiết tổng thể cao nhất, HAN cần chú ý ceiling thấp và crosswind nhẹ-vừa, còn SGN có ít giờ xấu hơn nhưng các event mưa/convection có thể rất mạnh trong thời gian ngắn.
