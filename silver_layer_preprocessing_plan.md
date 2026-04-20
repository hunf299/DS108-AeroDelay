# Kế hoạch triển khai Silver layer preprocessing (cập nhật theo khác biệt nguồn DAD vs SGN/HAN)

## 1) Quyết định đã chốt
1. Return/Emergency threshold: mặc định <= 90 phút (tối đa cấu hình 120), không dùng 600 phút.
2. DAD runway: giữ Unknown/N/A, tuyệt đối không ép default.
3. Military/Helicopter: không dùng làm dòng huấn luyện thương mại, tách thành nguồn feature ngoại sinh.
4. Logic tail mismatch: không ghi đè dữ liệu gốc.
   - Departure: Tail_Number -> Scheduled_Tail.
   - Arrival: Tail_Number -> Actual_Tail.
   - Thêm Is_Aircraft_Swapped.
5. Cập nhật quan trọng về semantics thời gian arrival theo nguồn:
   - DAD (nguồn riêng): Actual_Time = planned landing time, Flight_Time = actual landing time.
   - SGN/HAN (nguồn FR): Actual_Time = actual landing time, Flight_Time = flight duration (thời lượng bay), KHÔNG phải scheduled landing time.
6. Deduplicate áp dụng theo nguyên tắc bảo toàn nghiệp vụ:
  - Chỉ xóa bản ghi trùng gần nhau theo actual time (chênh vài phút) HOẶC bản ghi cùng chuyến có 2 runway với dữ liệu định danh giống nhau.
  - Tuyệt đối không xóa các chuyến có actual time cách xa (ví dụ chênh hàng chục giờ) dù cùng Flight_No trong cùng ngày crawl.
7. Chuẩn hóa mã chuyến Sun PhuQuoc Airways cho toàn bộ arrival/departure:
  - Nếu Flight_No có dạng SPQxxx (xxx là số) thì đổi thành 9Gxxx, giữ nguyên phần số.
  - Áp dụng cho tất cả file bay (3 arrival + 3 departure).

## 2) Xác nhận dữ liệu đầu vào hiện tại
Kiểm tra trực tiếp 3 file arrival Bronze cho thấy đều có cấu trúc cột:
- Crawl_Date, Actual_Time, Flight_Time, ...

Diễn giải theo nguồn:
- DAD arrival:
  - Actual_Time -> giờ hạ cánh kế hoạch.
  - Flight_Time -> giờ hạ cánh thực tế.
- SGN/HAN arrival:
  - Actual_Time -> giờ hạ cánh thực tế.
  - Flight_Time -> thời lượng bay (duration).

Kết luận: không thể dùng một mapping chung cho 3 sân bay ở bước parse thời gian arrival.

## 3) Mô hình chuẩn hóa thời gian (canonical model)
Sau bước ingest, chuẩn hóa về cùng bộ cột logic sau:
- Arrival_Planned_Landing_Time (HH:MM hoặc N/A)
- Arrival_Actual_Landing_Time (HH:MM)
- Arrival_Flight_Duration_Minutes (số phút hoặc N/A)
- Arrival_Planned_Landing_DateTime
- Arrival_Actual_Landing_DateTime

Mapping chi tiết:
- DAD arrival:
  - Arrival_Planned_Landing_Time = Actual_Time
  - Arrival_Actual_Landing_Time = Flight_Time
  - Arrival_Flight_Duration_Minutes = N/A
- SGN/HAN arrival:
  - Arrival_Actual_Landing_Time = Actual_Time
  - Arrival_Flight_Duration_Minutes = parse(Flight_Time)
  - Arrival_Planned_Landing_Time = N/A (không suy diễn giả định)

## 4) Điều chỉnh các bước preprocessing bị ảnh hưởng

### 4.1 Ingest và schema hygiene
- Giữ nguyên cột raw Actual_Time, Flight_Time ở layer trung gian để trace nguồn.
- Bổ sung hàm canonicalize_arrival_time_by_source(airport, df_arrival).
- Tách rõ lỗi parse:
  - duration parse fail cho SGN/HAN Flight_Time.
  - landing time parse fail cho DAD Flight_Time.

### 4.2 Datetime chuẩn hóa
- DAD:
  - Planned datetime từ Crawl_Date + Arrival_Planned_Landing_Time.
  - Actual datetime từ Crawl_Date + Arrival_Actual_Landing_Time.
- SGN/HAN:
  - Actual datetime từ Crawl_Date + Arrival_Actual_Landing_Time.
  - Planned datetime giữ N/A nếu không có nguồn schedule chuẩn.
- Xử lý rollover qua ngày áp dụng trên actual landing datetime (ưu tiên theo nghiệp vụ).

### 4.3 Deduplicate (recheck theo rule mới)
Áp dụng cho cả arrival và departure, chia 2 nhóm hợp lệ để xóa:
1. Near-time duplicates:
  - Cùng key định danh cốt lõi và actual datetime chênh rất nhỏ (mặc định <= 10 phút).
  - Key định danh cốt lõi tối thiểu gồm: Flight_No, scheduled time, aircraft type, tail number.
2. Dual-runway duplicates:
  - Cùng chuyến, cùng scheduled time, cùng aircraft type, cùng tail number.
  - Chỉ khác runway (2 runway được ghi nhận cho cùng 1 event).

Quy tắc bảo toàn (không xóa):
- Nếu actual datetime cách xa nhau rõ rệt thì giữ cả hai bản ghi.
- Không xóa nhầm chuyến delay lệch ngày (scheduled 23:50, actual 01:00 hôm sau).
- Case kiểm thử bắt buộc: SPQ895 ngày 19/12/2025 có 00:05 và 23:57 phải giữ cả hai vì cách xa lớn.

Ranking giữ dòng trong cụm được phép xóa:
- Ưu tiên dòng có runway hợp lệ.
- Sau đó ưu tiên dòng có status hoàn tất (Arrived/Departed/Landed).
- Nếu vẫn hòa, ưu tiên dòng đủ định danh hơn.

### 4.4 Anomaly same-origin
- Match same-origin arrival với departure theo Flight_No và Arrival_Actual_Landing_DateTime.
- Threshold return/emergency: <= 90 phút (option 120).
- Không dùng duration của SGN/HAN như mốc schedule để match anomaly.

### 4.5 Runway normalization
- Orientation window (+-30 phút) cho arrival dùng Arrival_Actual_Landing_DateTime.
- DAD runway vẫn giữ Unknown nếu thiếu nguồn runway.

### 4.6 Aircraft swap matching
- Ghép route departure -> arrival dùng mốc arrival actual landing datetime.
- Không dùng planned landing của SGN/HAN do không khả dụng chuẩn.
- Vẫn giữ thiết kế Scheduled_Tail / Actual_Tail / Is_Aircraft_Swapped.

### 4.7 Military feature engineering
- Event time cho arrival dùng Arrival_Actual_Landing_DateTime.
- Aggregation Military_Count_1h, Military_Count_3h không đổi về logic.

### 4.8 Chuẩn hóa mã chuyến Sun PhuQuoc Airways (SPQ -> 9G)
- Rule chuyển mã:
  - Pattern: SPQ(\d+)
  - Kết quả: 9G\1
- Phạm vi áp dụng: toàn bộ 6 file flights (arrival + departure).
- Điều kiện áp dụng:
  - Ưu tiên áp dụng khi Airline là Sun PhuQuoc Airways.
  - Nếu Airline trống nhưng Flight_No khớp pattern SPQ\d+ thì vẫn chuyển và ghi audit để review.
- Mục tiêu: đồng nhất prefix theo IATA code 9G, tránh mismatch khi join/anomaly/feature extraction.

### 4.9 Các rule còn lại
- Airline normalization, terminal normalization, category unknown giữ nguyên như kế hoạch trước.

## 5) Bổ sung kiểm thử và audit bắt buộc
Tạo thêm audit_arrival_time_semantics.csv với các chỉ số:
- airport
- rows_total_arrival
- rows_actual_landing_parsed
- rows_planned_landing_parsed
- rows_duration_parsed
- rows_duration_parse_failed
- rows_actual_landing_missing
- mapping_profile_applied (DAD_SOURCE hoặc FR_SOURCE)

Tạo thêm audit_deduplicate_decisions.csv với các chỉ số tối thiểu:
- airport, mode
- row_index_dropped, row_index_kept
- dedup_reason (near_time hoặc dual_runway)
- actual_time_gap_minutes
- key_signature (Flight_No + scheduled + tail + aircraft_type)

Tạo thêm audit_flight_no_spq_to_9g.csv:
- airport, mode
- row_index
- airline_before
- flight_no_before
- flight_no_after
- converted_by_rule (airline_match hoặc pattern_match)

Kiểm tra hậu xử lý bắt buộc:
1. SGN/HAN: không còn dòng nào dùng Flight_Time làm Scheduled landing datetime.
2. DAD: tỷ lệ parse Actual landing từ Flight_Time hợp lệ cao (được báo cáo minh bạch trong audit).
3. Các bước dedup/anomaly/runway sử dụng đúng mốc actual landing datetime.
4. Dedup chỉ xảy ra với gap nhỏ hoặc dual-runway theo key định danh; không xóa ca gap xa.
5. Tất cả Flight_No dạng SPQxxx đã chuyển thành 9Gxxx trong 6 file flights.

## 6) Kế hoạch thực thi cập nhật (sau khi duyệt)
1. Bổ sung source profile theo airport trong code preprocessing.
2. Implement canonicalize_arrival_time_by_source cho DAD vs SGN/HAN.
3. Refactor các hàm đang dùng Scheduled_Time/Actual_Time của arrival sang canonical columns.
4. Refactor deduplicate theo 2 reason hợp lệ: near_time và dual_runway (có guard chống xóa gap xa).
5. Implement rule chuyển Flight_No SPQxxx -> 9Gxxx cho toàn bộ flights CSV.
6. Chạy lại toàn pipeline Silver.
7. Xuất lại Audit + Features + báo cáo đối chiếu trước/sau.

## 7) Deliverables dự kiến
1. data_preprocessing.py đã refactor theo semantics thời gian mới.
2. Silver output mới cho Arrival/Departure.
3. Audit cũ + audit_arrival_time_semantics.csv + audit_deduplicate_decisions.csv + audit_flight_no_spq_to_9g.csv.
4. Feature tables (military events + commercial flights with military features) nhất quán theo actual landing datetime.
