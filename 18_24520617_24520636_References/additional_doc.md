### Về thông tin hạ tầng từ 3 hồ sơ sân bay (AIP VVTS, VVNB, VVDN)
Đây là các tài liệu thuộc Tập thông báo tin tức hàng không (AIP), cung cấp dữ liệu kỹ thuật nền tảng cho 3 sân bay lớn nhất Việt Nam:
1. Cảng hàng không quốc tế Tân Sơn Nhất (VVTS - SGN):
* Hệ thống đường cất hạ cánh (CHC): Sử dụng 2 đường CHC song song là 07L/25R và 07R/25L.
* Tọa độ điểm quy chiếu (ARP): Nằm tại giao điểm của đường CHC 07R/25L và đường lăn Bắc - Nam.
* Đặc điểm vận hành: 
  * Mức cao sân bay là 10m (33ft), nhiệt độ tham chiếu là 35.2°C.
  *Thường xuyên sử dụng cấu hình song song: một đường chuyên cất cánh và một đường chuyên hạ cánh để tối ưu hóa năng lực thông qua.
  *Phương thức tiếp cận chủ đạo: ILS/DME cho cả hai đầu đường băng.
2. Cảng hàng không quốc tế Nội Bài (VVNB - HAN):
* Hệ thống đường CHC: Hai đường CHC song song 11L/29R và 11R/29L.
* Tọa độ điểm quy chiếu (ARP): Giao điểm của đường CHC 11L/29R và đường lăn N3.
* Đặc điểm kỹ thuật:
  * Mức cao sân bay 13m (34ft).
  * Hệ thống đường lăn (TWY) phức tạp với các đường lăn nối nhanh (Exit taxiways) giúp giải tỏa tàu bay khỏi đường băng nhanh chóng sau khi hạ cánh.
  * Được trang bị hệ thống radar mặt đất và đèn tiếp cận hiện đại để hỗ trợ vận hành trong điều kiện tầm nhìn thấp (LVP).
3. Cảng hàng không quốc tế Đà Nẵng (VVDN - DAD):
* Hệ thống đường CHC: Hai đường CHC song song 17L/35R và 17R/35L.
* Tọa độ điểm quy chiếu (ARP): Giao điểm của đường CHC 35R/17L và đường lăn E3.
* Đặc điểm vận hành:
  * Mức cao sân bay 9m (30ft), nhiệt độ tham chiếu 36°C.
  * Do đặc thù vị trí, sân bay này có sự đan xen chặt chẽ giữa các hoạt động bay dân dụng và quân sự.
  * Hệ thống bãi đỗ tại Đà Nẵng phân chia rõ rệt khu vực đỗ ống lồng (Jet Bridge) và bãi đỗ xa (Remote Stand).

### Về vận hành runway
Tài liệu này cung cấp các kiến thức nghiệp vụ về cách Không lưu (ATC) và Phi công đưa ra quyết định trong thực tế, giải thích các tình huống dữ liệu biến động:
1. Quy tắc Gió và việc chọn Đường băng:
* Nguyên tắc chung: Tàu bay luôn ưu tiên cất/hạ cánh ngược chiều gió để tăng lực nâng và giảm quãng đường chạy đà.
* Ngoại lệ "Gió xuôi" (Tailwind): Tàu bay có thể cất/hạ cánh gió xuôi nếu đường băng đủ dài (TSN và Nội Bài đều có đường băng dài từ 3.000m - 3.800m). Phi công có thể chấp nhận gió xuôi lên đến 12-15 knots nếu máy tính trên tàu bay (FMC) tính toán đủ quãng đường phanh an toàn.
2. Quy định Giảm tiếng ồn (Noise Abatement):
* Mục đích: Để tránh bay qua các khu vực dân cư nhạy cảm (như trung tâm TP.HCM đối với đầu 07 SGN), ATC sẽ ưu tiên sử dụng một đầu đường băng nhất định ngay cả khi gió không hoàn toàn thuận lợi.
* Điều kiện bắt buộc: Phương thức giảm tiếng ồn sẽ bị hủy bỏ và ATC phải đổi chiều đường băng ngay lập tức nếu:
* Gió xuôi vượt quá ngưỡng an toàn (thường là 10 knots hoặc theo yêu cầu phi công).
* Trời mưa/Đường băng ướt: Đây là yếu tố then chốt. Khi đường băng ướt, ma sát giảm, giới hạn gió xuôi sẽ bị thắt chặt lại rất thấp (thường chỉ còn 5 knots).
3. Sự phối hợp ATC - Phi công:
* ATC có quyền đề xuất hướng đường băng để điều phối luồng không lưu, nhưng Phi công có quyền từ chối nếu cảm thấy điều kiện thời tiết (gió giật, đường ướt) không đảm bảo an toàn cho loại tàu bay của họ.
* Khi có sự thay đổi hướng đường băng (Runway Swap), toàn bộ hệ thống sân bay sẽ bị đình trệ tạm thời để sắp xếp lại luồng tàu bay đang chờ trên trời và dưới đất.

### Về additional weather feature
- Tailwind_Kmh (Tốc độ gió xuôi thực tế): * Phương pháp: Áp dụng công thức lượng giác dựa trên ind_speed, wind_direction và hướng la bàn chuẩn của đầu đường băng đang khai thác (Departure_Runway / Arrival_Runway).
Góc băng: SGN (07 độ/250 độ), HAN (110 độ/290 độ), DAD (170 độ/350 độ).
- Forced_Runway_Swap_Risk (Rủi ro bắt buộc đổi đường băng):
= 0 (Bình thường): Gió thuận lợi hoặc gió xuôi nhẹ (<9 km/h∼5 knots).
= 1 (Áp lực điều hành): Gió xuôi từ 9−27.8 km/h (5−15 knots) nhưng đường khô (Runway_Wet_Risk == 0 và precipitation == 0). Theo phương thức giảm tiếng ồn, phi công chấp nhận được (Accept Tailwind), đường băng không đổi nhưng năng lực xả trạm có thể chậm lại.
= 2 (Bắt buộc đổi băng): Gió xuôi >9 km/h kết hợp đường ướt (Runway_Wet_Risk == 1 hoặc precipitation > 0). Quy tắc giảm tiếng ồn bị hủy bỏ vì an toàn lực phanh → ATC buộc phải đảo chiều toàn bộ sân bay → Gây nghẽn cục bộ diện rộng.
- Gust_Variation_Kmh (Biên độ gió giật): 
- Gust_Variation_Kmh=max(0,Wind_Gust_Estimate_Kmh−wind_speed)
- Fog_Risk_Index (Chỉ số rủi ro sương mù dày):
Bật = 1 khi: Khoảng cách giữa nhiệt độ và điểm sương (temperature - dew_point_2m) <1.5 độ C VÀ độ ẩm humidity >90% VÀ tốc độ gió wind_speed <10 km/h trong khung giờ Đêm/Sáng sớm (Sương mù bức xạ đặc sản của Nội Bài mùa đông).
- Low_Ceiling_Flag (Trần mây thấp nguy hiểm):
Bật = 1 khi: cloud_cover_low >80%.
- Severe_Convection_Risk (Rủi ro dông lốc nhiệt đới):
Bật = 1 khi: Chỉ số năng lượng đối lưu cape >1500 J/kg VÀ lifted_index <−3.