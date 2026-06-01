# Model Planning

## 1. Mục tiêu benchmark

Dự án DS108 tập trung vào thu thập, tiền xử lý và kiểm định dữ liệu cho bài toán dự đoán trễ chuyến bay dây chuyền tại SGN, HAN, DAD. Model chỉ nên đóng vai trò benchmark/ablation study để chứng minh dữ liệu Gold sau xử lý có tín hiệu dự đoán, không cần dùng mô hình sequence hoặc deep learning phức tạp.

Benchmark chính nên chuyển sang **regression dự đoán số phút trễ khởi hành** cho các dòng `Record_Type == "Departure"`.

Target đề xuất:

```text
Departure_Delay_Reg_Target = clip(max(Departure_Delay, 0), 0, 240)
```

Lý do: delay âm là bay sớm và không phải trễ cần dự đoán; delay cực lớn dễ là outlier vận hành hoặc lỗi parse/link nên cap 240 phút để benchmark ổn định hơn. Vẫn giữ `Departure_Delay` raw để audit, nhưng không đưa vào predictor.

## 2. Dữ liệu sử dụng

Nguồn chính:

- `Data crawl/Gold_layer/Features/master_aero_features_gold.csv`
- `Data crawl/Gold_layer/Departure/*_flights_departure_gold_layer.csv`
- Audit Gold: `Data crawl/Gold_layer/Audit/*.csv`
- EDA flight: `Data crawl/Silver_layer_2/Audit/flight_eda_reports/`

Chỉ train trên departure rows. Không dùng arrival rows nếu mục tiêu là dự đoán departure delay dây chuyền, vì arrival rows không có cùng target và có nhiều feature turnaround/lag được set `NaN`.

Nên filter:

- `Record_Type == "Departure"`
- `Departure_Delay_Reg_Target.notna()`
- `Exclude_From_Propagation_Training != True`
- Ưu tiên benchmark chính trên `Category == "passenger"`; chạy thêm sensitivity all categories nếu cần.

## 3. Feature dùng cho regression

Nhóm flight predictor nên giữ:

- Rotation: `Tail_Sequence_Day`, `Is_First_Flight`, `Standard_Turnaround`
- Turnaround an toàn: `Turnaround_Buffer_Model`, `Tail_Stagnation_Duration_Model`, `Turnaround_Deficit_Min`, `Is_Long_Ground_Turnaround`
- Lag dây chuyền: `Prev_Departure_Delay_Tail_1`, `Prev_Departure_Delay_Tail_2`, `Rolling_Departure_Delay_Tail_3`, `Prev_Turnaround_Buffer_Tail_1`, `Prev_Turnaround_Buffer_Tail_2`, `Rolling_Turnaround_Buffer_Tail_3`
- Airport load: `Airport_Load_Factor`, `Number_of_Flights_in_Last_Hour`, `Is_Airport_Congested`, `Is_Parallel_Usage`, `Taxi_Out_Congestion`
- A-CDM/network: `A_CDM_TOBT_Deficit`, `Ground_Handling_Pressure`, `Destination_Congestion_Risk`, `Previous_Station_Disruption`
- Operation/categorical: `Airport`, `IATA`, `Airline_Type`, `Aircraft_Type`, `Category`, `Time_of_Day`, `Peak_Hour_Indicator`, `Is_Special_Days`, `Is_Wide_Body`
- Weather Gold: dùng nhóm weather đã xử lý như risk score, visibility, wind/crosswind, rain, ceiling, convection.

Không dùng làm predictor:

- Target/raw label: `Departure_Delay`, `Departure_Delay_Reg_Target`
- Timestamp/identity: `Actual_Time`, `Flight_No`, `Airline`, `Scheduled_Tail`, `Matched_Actual_Tail`
- Linkage/leakage-risk: `Runway_Swap_Event`, `Swap_Match_Gap_Minutes`
- Arrival-only rows hoặc feature tạo từ actual outcome của chính chuyến bay.

`Runway_Swap_Event` đã bị loại khỏi Gold export vì trước đó có dùng delay proxy và tương quan cao bất thường với delay.

## 4. Kiểm soát leakage

Các feature đã rà soát:

- `A_CDM_TOBT_Deficit`: dùng previous actual arrival + standard turnaround so với current scheduled departure. Có thể giữ nếu previous arrival đã biết trước giờ dự đoán.
- `Ground_Handling_Pressure`: đếm arrival trước scheduled departure theo airline/airport. Có thể giữ như trạng thái vận hành đã quan sát.
- `Taxi_Out_Congestion`: đã chỉnh sang scheduled departures trước STD, không dùng `Actual_Time` của chính chuyến bay.
- Lag departure delay: chỉ giữ delay lag khi chuyến trước đã có `Actual_Time <= Scheduled_Time` của chuyến hiện tại; nếu chưa biết thì để `NaN`.

Train/test tuyệt đối không random split toàn bộ. Dùng split theo thời gian, ví dụ:

- Train: Dec 2025, Jan 2026, Feb 2026
- Test: Mar 2026

Nếu cần validation: train Dec-Jan, validation Feb, test Mar.

## 5. Xử lý long-ground turnaround

Với `Turnaround_Buffer >= 5760` phút (4 ngày), xem là long-ground/non-regular rotation. Không dùng raw `Turnaround_Buffer` cho model chính.

Quy tắc:

- `Turnaround_Buffer_Model = NaN` cho long-ground
- `Tail_Stagnation_Duration_Model = NaN` cho long-ground
- Giữ `Is_Long_Ground_Turnaround` để model biết đây là nhóm đặc biệt
- Raw `Turnaround_Buffer` và `Tail_Stagnation_Duration` chỉ dùng audit/EDA

## 6. Model benchmark đề xuất

Chạy theo thứ tự từ đơn giản đến mạnh hơn:

1. `DummyRegressor(strategy="median")`: baseline bắt buộc.
2. `Ridge` hoặc `ElasticNet`: kiểm tra tín hiệu tuyến tính sau one-hot categorical.
3. `RandomForestRegressor` hoặc `ExtraTreesRegressor`: bắt nonlinear đơn giản, ít tuning.
4. `HistGradientBoostingRegressor`: benchmark chính nếu muốn mô hình tabular mạnh nhưng vẫn gọn.

Metrics:

- `MAE`: metric chính, dễ giải thích theo phút.
- `MedianAE`: giảm ảnh hưởng outlier.
- `RMSE`: nhạy với delay lớn.
- `R2`: phụ trợ, không nên là tiêu chí chính.
- Có thể thêm `MAE_by_airport` và `MAE_by_month`.

## 7. Ablation study tối thiểu

Chạy 4 cấu hình:

- F0: schedule + airport + categorical cơ bản
- F1: F0 + turnaround model-safe
- F2: F1 + lag delay/turnaround
- F3: F2 + weather Gold

Kỳ vọng: F2 phải cải thiện rõ so với F0/F1 nếu delay dây chuyền thật sự có tín hiệu. F3 có thể cải thiện ở các ngày mưa, visibility thấp, crosswind/tailwind hoặc convection, nhưng không nhất thiết tăng mạnh toàn cục vì weather event hiếm.

## 8. Kết luận sẵn sàng dữ liệu

Dữ liệu Gold hiện đã đủ để benchmark regression nếu tuân thủ feature list và time split ở trên. Chưa nên coi là production-ready vì còn cần sensitivity cho outlier delay âm/rất lớn, nhóm long-ground, và missing lag theo airport. Với phạm vi DS108, đây là mức phù hợp để chứng minh pipeline preprocessing và feature engineering có giá trị.
