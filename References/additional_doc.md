### Về runway

1. Nguyên tắc vận hành đường băng
Phân công nhiệm vụ: Sân bay Tân Sơn Nhất sử dụng 2 đường CHC song song: 25L/07R chuyên cất cánh và 25R/07L chuyên hạ cánh.  
Linh hoạt: Dù có phân công cố định, ATC vẫn có thể thay đổi hướng tùy theo điều kiện thực tế để đảm bảo an toàn và tối ưu hóa hoạt động.  
2. Các yếu tố quyết định thay đổi hướng CHC
Hướng gió: Theo quy định trong AIP, tàu bay thường cất hạ cánh ngược chiều gió. Tuy nhiên, nếu phi công đề nghị và điều kiện cho phép, tàu bay vẫn có thể hạ cánh với gió xuôi (giới hạn thường là dưới 10kts, hoặc tùy vào khả năng chấp nhận của phi công).  
Quy định giảm tiếng ồn: ATC có thể chủ động chọn đường băng không ngược gió hoàn toàn để tránh các khu vực nhạy cảm tiếng ồn. Nếu các giới hạn an toàn về gió bị vi phạm, phương thức này sẽ bị hủy bỏ và ưu tiên quay về hướng đón gió thuận lợi nhất.  
Tình trạng mặt đường băng:
Trời khô: Với chiều dài đường băng lớn (3.048m - 3.800m), phi công có thể tính toán và chấp nhận hạ cánh gió xuôi nếu máy tính (FMC) xác nhận đủ quãng đường phanh.  
Trời mưa: Giới hạn chịu đựng gió xuôi giảm xuống đáng kể; nếu gió xuôi vượt ngưỡng, ATC bắt buộc đổi chiều đường băng hoặc phi công sẽ từ chối hạ cánh.  
Các yếu tố khác: Ngoài các yếu tố trên, còn nhiều điều kiện không lưu khác có thể khiến ATC yêu cầu thay đổi hướng CHC

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