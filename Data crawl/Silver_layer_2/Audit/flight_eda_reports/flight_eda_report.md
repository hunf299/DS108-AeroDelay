# Flight EDA Report

## Phạm vi

Notebook `Source code/flight_eda.ipynb` kiểm tra flight preprocessing, feature engineering và Gold-layer flight features cho bài toán dự đoán trễ khởi hành dây chuyền. Báo cáo dùng dữ liệu `Data crawl/Silver_layer_2` và Gold output tại `Data crawl/Gold_layer`.

Các bảng/biểu đồ EDA được lưu tại `Data crawl/Silver_layer_2/Audit/flight_eda_reports/`.

## Lineage và row count

Silver Layer 2 có đủ 6 file airport-mode:

- Arrival: SGN `36,699`, HAN `24,899`, DAD `12,573`.
- Departure: SGN `36,735`, HAN `28,502`, DAD `12,521`.
- Tổng Silver flight rows: `151,929`.

Gold per-airport giữ 1:1 số dòng với Silver Layer 2, `silver_to_gold_delta = 0`. Master Gold có `148,519` dòng vì loại các dòng không đủ điều kiện feature propagation/tail rotation.

## Gold Flight Feature Coverage

Notebook đã bổ sung mục `6.2. Gold Layer Flight Feature EDA` để rà soát các feature flight trong Gold, bao gồm:

- Delay/target: `Departure_Delay`, `Departure_Delay_Reg_Target`, `Arrival_Delay`, `Accumulated_Delay`.
- Turnaround: `Turnaround_Buffer`, `Turnaround_Buffer_Model`, `Tail_Stagnation_Duration`, `Tail_Stagnation_Duration_Model`, `Turnaround_Deficit_Min`, `Turnaround_Slack_Min`.
- Lag dây chuyền: `Prev_Departure_Delay_Tail_1/2`, `Rolling_Departure_Delay_Tail_3`, `Prev_Turnaround_Buffer_Tail_1/2`, `Rolling_Turnaround_Buffer_Tail_3`, airport delay lag.
- Airport/load: `Airport_Load_Factor`, `Number_of_Flights_in_Last_Hour`, `Is_Airport_Congested`, `Taxi_Out_Congestion`, `Ground_Handling_Pressure`.
- Categorical/binary: `Airport`, `IATA`, `Airline_Type`, `Aircraft_Type`, `Category`, `Time_of_Day`, `Is_First_Flight`, `Is_Wide_Body`, `Peak_Hour_Indicator`, `Is_Long_Ground_Turnaround`.

Bảng `26a_gold_flight_feature_coverage.csv` phân loại từng cột Gold thành: đã EDA, weather feature, identity/timestamp, hoặc cần review. Điều này giúp tránh bỏ sót feature khi chuyển sang modeling.

## Regression Target

Target regression hiện là:

```text
Departure_Delay_Reg_Target = clip(max(Departure_Delay, 0), 0, 240)
```

Trong departure Gold, target này có median khoảng `23` phút, p95 khoảng `113` phút, max `240` phút sau clip. `Departure_Delay` raw vẫn giữ để audit nhưng không nên dùng làm predictor vì đó là nguồn tạo label.

Kiểm tra consistency cho thấy `0/74,722` dòng departure Gold có sai lệch quá 1 phút giữa `Departure_Delay` lưu sẵn và delay tính lại từ `Scheduled_Time`/`Actual_Time`.

## Correlation và tín hiệu dự đoán

Tương quan Spearman mạnh nhất với `Departure_Delay_Reg_Target` đến từ nhóm airport load và delay propagation:

- `Number_of_Flights_in_Last_Hour`: `0.447`
- `Airport_Load_Factor`: `0.364`
- `Rolling_Departure_Delay_Tail_3`: `0.338`
- `Prev_Departure_Delay_Tail_1`: `0.323`
- `Ground_Handling_Pressure`: `0.319`
- `Is_Airport_Congested`: `0.308`
- `Standard_Turnaround`: `0.293`
- `Taxi_Out_Congestion`: `0.280`

Nhận xét: delay dây chuyền trong dataset có tín hiệu rõ từ traffic/load và lịch sử delay gần nhất theo tail. Weather nên được đưa vào ablation riêng thay vì kỳ vọng luôn đứng đầu global correlation, vì event thời tiết xấu có tính hiếm và phụ thuộc sân bay/thời điểm.

## Long-Ground Turnaround

Feature engineering đã đánh dấu `1,235` departure rows bằng `Is_Long_Ground_Turnaround`. Với nhóm này, không dùng raw turnaround cho model chính:

- `Turnaround_Buffer_Model = NaN`
- `Tail_Stagnation_Duration_Model = NaN`
- Giữ `Is_Long_Ground_Turnaround` như cờ phân biệt chuyến không thường xuyên/long-ground.

Raw `Turnaround_Buffer` trong Gold đã được cap ở `4320` phút, nên EDA dùng cờ `Is_Long_Ground_Turnaround` thay vì tìm trực tiếp `Turnaround_Buffer >= 5760`.

## Leakage Review

Các cột linkage/leakage-risk đã bị loại khỏi Gold training export: `Runway_Swap_Event`, `Matched_Actual_Tail`, `Swap_Match_Gap_Minutes`.

Các feature được giữ sau khi rà soát:

- `A_CDM_TOBT_Deficit`: dùng previous actual arrival + standard turnaround so với current scheduled departure; giữ được nếu previous arrival đã biết trước thời điểm dự đoán.
- `Ground_Handling_Pressure`: đếm arrival trước scheduled departure theo airline/airport; là trạng thái vận hành đã quan sát.
- `Taxi_Out_Congestion`: đã chỉnh sang scheduled departures trước STD, tránh dùng `Actual_Time` của chính chuyến bay.
- Delay lag: chỉ giữ delay của chuyến trước khi chuyến trước đã có `Actual_Time <= Scheduled_Time` của chuyến hiện tại; nếu chưa biết thì để `NaN`.

## Modeling Readiness

Dataset hiện đã đủ để benchmark regression nếu dùng đúng filter:

- Chỉ train `Record_Type == "Departure"`.
- Không dùng arrival rows cho target departure delay.
- Không random split; dùng split theo thời gian, ví dụ train Dec-Jan-Feb và test Mar.
- Không đưa `Departure_Delay`, `Actual_Time`, identity columns hoặc linkage/leakage columns vào predictor.
- Dùng ablation: baseline schedule/load, thêm turnaround, thêm lag, sau đó thêm weather Gold.

Rủi ro còn lại cần nêu trong đồ án: airport lag có missing cao do chỉ giữ lag đã biết tại thời điểm dự đoán; long-ground cần xử lý riêng; một số delay âm/rất lớn vẫn nên giữ trong audit outlier thay vì xóa âm thầm.
