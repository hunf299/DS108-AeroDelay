# Đặc tả Kỹ thuật Hệ thống Feature Engineering

## Mô hình dữ liệu

Tất cả dữ liệu sau khi trích xuất đặc trưng sẽ được ghi vào:

```text
Data crawl/
├── Silver_layer/
└── Gold_layer/
    ├── Arrival/
    ├── Departure/
    ├── Features/
    └── Audit/
```

Các file dữ liệu tầng Gold được xuất bản phân tách theo từng sân bay và loại hình di chuyển:

- `Gold_layer/Departure/{sgn,han,dad}_flights_departure_gold_layer.csv`
- `Gold_layer/Arrival/{sgn,han,dad}_flights_arrival_gold_layer.csv`
- `Gold_layer/Features/master_aero_features_gold.csv`

Dữ liệu đầu ra của thư mục Audit bao gồm:

- `data_leakage_report.csv`
- `imputation_metrics_log.csv`
- `feature_summary_stats.csv`

## Cấu trúc Dữ liệu

Mỗi file sân bay thuộc tầng Gold phải bảo toàn chính xác các cột dữ liệu gốc từ file tầng Silver tương ứng, cộng thêm các cột đặc trưng (feature) đã được phê duyệt. Quy trình trích xuất đặc trưng bắt đầu từ file CSV gốc tầng Silver của sân bay đó, sau đó thực hiện liên kết (join) duy nhất với danh sách các cột đặc trưng nằm trong danh sách trắng (whitelisted).

Các quy tắc bắt buộc:

- File Departure (Chuyến đi) của SGN/HAN tuyệt đối không được lấy chéo các cột chỉ có ở DAD.
- File Arrival (Chuyến đến) của SGN/HAN tuyệt đối không được lấy chéo cột `Belt` chỉ có ở DAD.
- Tất cả các file tầng Gold thuộc nhóm Arrival không được lặp cột `Scheduled_Time`.
- Các cột phụ trung gian nghiêm cấm xuất hiện trong dữ liệu đầu ra tầng Gold: `Airport`, `Source_File`, `Source_Row_Index`, `Tail_Number`, `Origin_IATA`, `Destination_IATA`, `Event_Time`, `Actual_Event_Time`, `Scheduled_Event_Time`, `Observed_Actual_Departure`, `Flight_Date`, `Observed_Prev_Actual_Arrival`.

Quy tắc ánh xạ trực tiếp (Direct mapping):
- Cột Crawl_Date đóng vai trò là ngày thực hiện chuyến bay (Flight_Date).
- Cột Scheduled_Time đóng vai trò là thời gian dự kiến (Scheduled_Event_Time / Event_Time).
- Cột Actual_Time đóng vai trò là thời gian thực tế (Actual_Event_Time / Observed_Actual_Departure).
- Sử dụng trực tiếp Scheduled_Tail đối với file Departure và Actual_Tail đối với file Arrival (Không tạo cột dùng chung Tail_Number).
- Giữ lại duy nhất trường Prev_Actual_Arrival và loại bỏ hoàn toàn trường trùng lặp Observed_Prev_Actual_Arrival.
- Đổi tên cột generic Airport thành Origin trong các file thuộc nhóm Departure, và đổi thành Destination trong các file thuộc nhóm Arrival.

## Bảo toàn Số lượng Mẫu 

Pipeline áp dụng chính sách nghiêm cấm xóa dòng dữ liệu (No-Drop Policy). Tất cả dữ liệu đầu vào từ tầng Silver (bao gồm cả các trường hợp khuyết thiếu hoặc dữ liệu nhiễu đã qua xử lý) phải được bảo toàn với tỷ lệ số dòng 1:1 khi chuyển sang tầng Gold. Trước khi tiến hành trích xuất đặc trưng, đối với các bản ghi bị khuyết trường `Scheduled_Time`, hệ thống sẽ thực hiện điền khuyết tạm thời bằng giá trị của cột `Actual_Time`.

Tất cả các chuyến bay phi thương mại như bay chở hàng (`cargo`), bay thuê chuyến (`general aviation`), chuyên cơ thương gia (`business jet`), hay bay quân sự/chính phủ (`military or government`) bắt buộc phải được giữ lại để tham gia vào các phép tính cửa sổ trượt rolling-window nhằm đo lường mật độ:

* `Airport_Load_Factor` (Hệ số tải/Mật độ khai thác sân bay)
* `Number_of_Flights_in_Last_Hour` (Số lượng chuyến bay trong một giờ qua)
* `Is_Airport_Congested` (Trạng thái sân bay quá tải)

Chỉ có các chuyến bay chở hành khách (`passenger`) mới đủ điều kiện tham gia vào tập dữ liệu huấn luyện mô hình dự báo trễ dây chuyền. Tất cả các bản ghi phi thương mại sẽ bị ép gán cờ `Exclude_From_Propagation_Training = True` trước khi xuất bản sang tầng Gold.

## Xử lý Khuyết Link (Missing Link Imputation)

Các bản ghi bị khuyết link dữ liệu (khuyết đầu đi hoặc đầu đến) sẽ được định vị từ các file audit và đánh dấu bằng cờ `Is_Imputed_Link = 1`.

Thời gian xoay vòng tàu bay tiêu chuẩn (baseline turnaround) được tính toán từ các bản ghi sạch (không khuyết link) bằng cách lấy giá trị trung vị (median) của thời gian xoay vòng theo từng cụm `[Aircraft_Type, airport]`.

Quy tắc điền khuyết toán học:

* Đối với nhóm khuyết đầu đi (`arrival_without_departure`): `Imputed_Actual_Arrival = Scheduled_Time - Standard_Turnaround`; đồng thời gán `Arrival_Delay = 0`.
* Đối với nhóm khuyết đầu đến (`departure_without_arrival`): `Imputed_Actual_Departure = Prev_Actual_Arrival + Standard_Turnaround`.

Tuyệt đối không có bất kỳ bản ghi khuyết link nào bị xóa bỏ trong suốt quá trình điền khuyết này.

## Gán nhãn Ngày Đặc biệt (Special Days)

Trường `Is_Special_Days` được gán giá trị `= 1` khi ngày diễn ra hoạt động bay rơi vào các dịp cao điểm:

* Kỳ nghỉ Giáng sinh: Ngày 24 tháng 12 và Ngày 25 tháng 12.
* Năm mới (Tết Dương lịch): Ngày 31 tháng 12 và Ngày 1 tháng 1.
* Giai đoạn cao điểm vận hành Tết Nguyên Đán (Việt Nam).
* Ngày Giỗ Tổ Hùng Vương.
* Ngày Giải phóng và Quốc tế Lao động: Ngày 30 tháng 4 và Ngày 1 tháng 5.
* Ngày Quốc khánh: Ngày 2 tháng 9.
* Cao điểm du lịch Hè: Toàn bộ các ngày trong Tháng 6 và Tháng 7.

## Kiểm định Chất lượng Cuối cùng (Final Sanity Checks)

Trước khi mỗi file thuộc tầng Gold được tiến hành lưu trữ:

1. Tải cấu trúc cột (schema) của file CSV tầng Silver tương ứng.
2. Định nghĩa danh sách các cột hợp lệ bao gồm: Các cột gốc tầng Silver cộng thêm các cột đặc trưng đã được phê duyệt.
3. Loại bỏ cột `Scheduled_Time` ra khỏi dữ liệu đầu ra của nhóm Arrival.
4. Xóa bỏ (drop) bất kỳ cột nào nằm ngoài danh sách cấu trúc hợp lệ nêu trên.
5. Thực hiện kiểm định nghiêm ngặt (assert) để đảm bảo các cột trong file Gold hoàn toàn là tập con (subset) của danh sách cấu trúc hợp lệ; đồng thời xác thực số lượng dòng đầu ra phải trùng khớp chính xác 100% với file tầng Silver gốc tương ứng.