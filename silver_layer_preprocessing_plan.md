# Kế hoạch triển khai Silver layer preprocessing (đã chốt theo feedback)

## 1) Quyết định đã chốt
1. Return/Emergency threshold: mặc định <= 90 phút (có thể cấu hình max 120 phút, nhưng không dùng 600 phút).
2. DAD runway: giữ nguyên Unknown/N/A, tuyệt đối không ép default runway.
3. Military/Helicopter: không dùng làm dòng huấn luyện thương mại; tách ra thành nguồn tạo đặc trưng nhiễu điều hành.
4. Logic error Tail swap: không ghi đè dữ liệu gốc, chuyển sang mô hình cột mới.
   - Departure: Tail_Number -> Scheduled_Tail.
   - Arrival: Tail_Number -> Actual_Tail.
   - Thêm cờ Is_Aircraft_Swapped theo cặp ghép route.

## 2) Kết quả validate lại theo quyết định mới

### 2.1 Return/Emergency với ngưỡng 90/120 phút
- SGN same-origin arrival: 60 dòng.
  - Return/Emergency <= 90 phút: 1 dòng.
  - Return/Emergency <= 120 phút: 1 dòng.
- HAN same-origin arrival: 24 dòng.
  - Return/Emergency <= 90 phút: 2 dòng.
  - Return/Emergency <= 120 phút: 2 dòng.
- DAD same-origin arrival: 0 dòng.

Kết luận: threshold chặt 90 phút là hợp lý, loại được phần lớn nhiễu same-origin không phải quay đầu thật.

### 2.2 DAD runway
- File arrival DAD hiện không có cột Arrival_Runway.
- File departure DAD hiện không có cột Departure_Runway.

Kết luận: giữ Unknown/N/A là đúng về mặt nghiệp vụ và an toàn mô hình.

### 2.3 Military/Helicopter signal
Số lượng dòng military/helicopter quan sát được:
- sgn_arr: 45
- han_arr: 5
- dad_arr: 0
- sgn_dep: 43
- han_dep: 35
- dad_dep: 0

Kết luận: đủ tín hiệu để tách thành feature hoạt động quân sự, không nên giữ như nhãn thương mại để học target delay.

### 2.4 Aircraft swap (không ghi đè)
Ghép cặp route hợp lệ (arrival sau departure, <= 12h, nearest match theo mỗi departure):
- Tổng departure rows có match arrival: 14,786
- Is_Aircraft_Swapped = True: 438
- Trong đó có đủ cả Scheduled_Tail và Actual_Tail: 392
- Theo route:
  - sgn->dad: 124
  - sgn->han: 104
  - dad->sgn: 56
  - dad->han: 8
  - han->sgn: 85
  - han->dad: 61

## 3) Thiết kế xử lý cập nhật trong data_preprocessing.py

### 3.1 Khung pipeline tổng quát
- Refactor script thành pipeline nhiều bước, có hàm độc lập và audit log.
- Không hard-code path tuyệt đối; resolve theo root dự án.
- Input: Data crawl/Bronze_layer.
- Output: Data crawl/Silver_layer.

### 3.2 Chuẩn hóa schema và data hygiene
- Chuẩn hóa token rỗng về N/A: "", nan, None, null.
- Loại header lẫn trong data (ô trùng tên cột).
- Validate IATA: chỉ chấp nhận dạng 3 ký tự A-Z; sai định dạng -> N/A.
- Tạo cột runway bị thiếu để đồng bộ schema:
  - DAD arrival thêm Arrival_Runway = Unknown.
  - DAD departure thêm Departure_Runway = Unknown.

### 3.3 Chuẩn hóa datetime chống lỗi qua ngày
- Scheduled_DateTime = Crawl_Date + Scheduled_Time.
- Actual_DateTime = Crawl_Date + Actual_Time.
- Nếu actual lệch về đầu ngày theo rule rollover thì +1 ngày.
- Dùng datetime này cho dedup, anomaly matching, runway orientation và swap matching.

### 3.4 Rule dedup an toàn
Chỉ xóa khi có bằng chứng duplicate gần thời gian, tránh xóa chuyến delay thật:
1. Cùng key định danh + Actual_DateTime chênh <= 10 phút.
2. Hoặc cùng key định danh, khác runway/terminal do ghi nhận đa trạm.
3. Ranking giữ dòng tốt nhất: runway hợp lệ > đủ định danh > status hoàn tất (Arrived/Departed).
4. Chênh thời gian xa (ví dụ cách nhiều giờ) thì giữ nguyên.

### 3.5 Rule anomaly same-origin (arrival)
- Xác định same-origin khi IATA (origin code) trùng airport của file arrival.
- Match với departure cùng airport theo Flight_No và Actual_DateTime.
- Định nghĩa:
  - is_return_or_emergency = True nếu có cặp gap <= 90 phút (option cấu hình 120).
  - is_same_origin_unmatched = True nếu không có match trong ngưỡng.
- Hành động trên bảng chuyến thương mại:
  1. Passenger/Unknown/Cargo + same-origin unmatched -> loại khỏi bảng huấn luyện thương mại.
  2. Return/Emergency matched -> giữ và gắn cờ anomaly.

### 3.6 Rule runway normalization
Runway map chuẩn:
- SGN: dep 25L/07R, arr 25R/07L.
- HAN: dep 11R/29L, arr 11L/29R.
- DAD: dep 35R/17L, arr 35L/17R.

Áp dụng:
- SGN/HAN: có thể suy orientation bằng cửa sổ +-30 phút, majority >= 60%, rồi điền/chỉnh runway null.
- DAD: không suy diễn ép default; giữ Arrival_Runway/Departure_Runway = Unknown khi thiếu.
- Emergency return tại SGN/HAN: chuyển arrival runway sang runway dạng khẩn cấp tương ứng hướng khai thác hiện hành.

### 3.7 Rule airline normalization
- Canonical theo prefix Flight_No cho hãng VN:
  - 0V -> VASCO
  - VN -> Vietnam Airlines
  - QH -> Bamboo Airways
  - VU -> Vietravel Airlines
  - 9G -> Sun PhuQuoc Airways
  - VJ -> VietJet Air
- KOREAN AIRLINES -> Korean Air.
- Điền airline null theo prefix (đặc biệt DAD prefix 9G).
- Chuẩn hóa tên hãng all-caps về dạng chuẩn hiển thị.

### 3.8 Rule terminal normalization
Rule chung:
1. Origin/Destination = N/A -> Terminal = N/A.
2. Arrival có origin trùng airport file -> Terminal = N/A.
3. Nhóm non-passenger -> Terminal = 0.

Rule theo sân bay:
- SGN:
  - Quốc tế: 2
  - Nội địa: prefix 0V/VN/QH/VU/9G -> 3, prefix VJ -> 1
- HAN, DAD:
  - Quốc tế: 2
  - Nội địa: 1

### 3.9 Rule category unknown
- Nếu thiếu >= 3 trường định danh quan trọng (Flight_No, Airline, Tail, Aircraft_Type, IATA) thì set Category = unknown.
- Chuẩn hóa các ô trống còn lại thành N/A.

### 3.10 Rule aircraft swap theo thiết kế mới
- Không ghi đè tail gốc.
- Đổi tên cột:
  - Departure: Tail_Number -> Scheduled_Tail
  - Arrival: Tail_Number -> Actual_Tail
- Ghép 6 route theo Flight_No + thời gian hợp lệ <= 12h, chọn nearest match theo từng departure.
- Tạo cột:
  - Matched_Actual_Tail (trên departure, từ arrival nearest-match)
  - Is_Aircraft_Swapped = Scheduled_Tail != Matched_Actual_Tail (khi đủ dữ liệu)
- Lưu bảng audit swap riêng để trace toàn bộ cặp match.

### 3.11 Tách military/helicopter thành feature engineering input
- Tạo bảng phụ military_activity_events từ các dòng military/helicopter/non-commercial.
- Aggregate theo airport và cửa sổ thời gian quanh chuyến thương mại:
  - Military_Count_1h
  - Military_Count_3h
  - Is_Military_Active
- Bảng huấn luyện thương mại chỉ giữ flight thương mại có target delay hợp lệ.

## 4) Kế hoạch triển khai thực thi
1. Refactor data_preprocessing.py thành pipeline module + config.
2. Implement hygiene: normalize NA, remove header rows, validate IATA.
3. Implement datetime rollover + dedup an toàn.
4. Implement anomaly same-origin với threshold mặc định 90 phút.
5. Implement runway normalization (SGN/HAN) và policy Unknown cho DAD.
6. Implement airline/terminal/category normalization.
7. Implement aircraft swap logic theo Scheduled_Tail/Actual_Tail + flag (không overwrite).
8. Tách military/helicopter sang bảng events và sinh feature aggregate.
9. Ghi output Silver + audit report và chạy validation hậu xử lý.

## 5) Deliverables dự kiến
1. Script hoàn chỉnh tại Source code/data_preprocessing.py.
2. Bộ dữ liệu Silver cleaned cho Arrival/Departure.
3. Bảng audit:
   - duplicate removals
   - same-origin anomaly actions
   - runway fill/normalize actions
   - aircraft swap matches
4. Bảng phụ military activity để phục vụ feature engineering.

## 6) Path alignment
- Bỏ hard-coded absolute path hiện tại.
- Resolve path theo project root để chạy được đa máy.
- Đảm bảo I/O đúng cấu trúc Bronze_layer -> Silver_layer.
