from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime, timedelta
import re

def crawl_dad_historical_flights_edge(target_date_str):
    print(f"\n[+] Khởi động trình duyệt Edge cho ngày: {target_date_str}")

    # 1. Cấu hình Edge
    options = EdgeOptions()
    # options.add_argument('--headless') # Bỏ dấu thăng (#) ở đầu dòng này nếu muốn trình duyệt chạy ẩn
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")

    driver = webdriver.Edge(options=options)

    # 2. Truy cập URL
    url = f"https://danangairport.vn/flights-flight-status-departure?f=1&t=0&date={target_date_str}&time=0"
    driver.get(url)
    time.sleep(3)  # Đợi trang tải mớ HTML ban đầu

    # 3. Tiêm Javascript để bẻ khóa bộ lọc ngày/giờ
    js_inject = f"""
        var dateSelect = document.getElementById('date');
        if (dateSelect) {{
            var selectedDateOption = dateSelect.querySelector('option[selected]');
            if (selectedDateOption) {{ selectedDateOption.value = '{target_date_str}'; }}
            dateSelect.value = '{target_date_str}';
        }}
        var timeSelect = document.getElementById('time');
        if (timeSelect) {{
            var selectedTimeOption = timeSelect.querySelector('option[selected]');
            if (selectedTimeOption) {{ selectedTimeOption.removeAttribute('selected'); }}
            timeSelect.value = '0';
        }}
    """
    driver.execute_script(js_inject)
    print("  > Đã hack xong bộ lọc DOM. Chuẩn bị bung dữ liệu...")
    time.sleep(2)

    # 4. Vòng lặp bấm nút "Load More" cho đến khi hết chuyến
    # 4. Vòng lặp bấm nút "Load More" cho đến khi hết chuyến
    while True:
        try:
            load_more_btn = driver.find_element(By.CSS_SELECTOR, "button.load-more-btn")

            # --- CHỐT CHẶN BẠN VỪA PHÁT HIỆN ---
            # Kiểm tra nếu nút có thuộc tính disabled (hoặc bị web ẩn đi)
            if load_more_btn.get_attribute("disabled"):
                print("  > Nút Load More đã bị mờ (disabled). Đã bung hết dữ liệu!")
                break

            current_page = load_more_btn.get_attribute("data-current-page")
            total_pages = load_more_btn.get_attribute("data-total-pages")
            print(f"  > Đang bung trang {current_page} / {total_pages}...")

            # Ép click bằng JS
            driver.execute_script("arguments[0].click();", load_more_btn)
            time.sleep(3)  # Chờ server DAD nhả dữ liệu về

            # Chốt chặn an toàn số 2: Nếu lỡ vòng lặp kẹt ở trang cuối
            if current_page == total_pages:
                print("  > Đã chạm mốc trang cuối cùng!")
                break

        except Exception as e:
            print("  > Không tìm thấy nút Load More. Dừng bung dữ liệu.")
            break

    # Lấy toàn bộ mã nguồn HTML và đóng Edge cho nhẹ máy
    page_source = driver.page_source
    driver.quit()

    # --- 5. BÓC TÁCH DỮ LIỆU BẰNG BEAUTIFULSOUP ---
    print("  > Bắt đầu dùng dao mổ BeautifulSoup bóc tách...")
    soup = BeautifulSoup(page_source, 'html.parser')
    flights_data = []

    # Tìm tất cả các dòng chứa dữ liệu chuyến bay
    rows = soup.find_all('tr', class_='datarows')

    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 10:

            # --- 1. Xử lý Cột 0: Thời gian (Scheduled & Actual) ---
            time_td = cols[0]
            del_div = time_td.find('div', class_='del')
            if del_div:
                scheduled_time = del_div.text.strip()
                actual_time = ""
                for div in time_td.find_all('div'):
                    classes = div.get('class', [])
                    if 'del' not in classes and 'd-none' not in classes:
                        actual_time = div.text.strip()
                        break
            else:
                divs = time_td.find_all('div')
                valid_divs = [d for d in divs if 'd-none' not in d.get('class', [])]
                scheduled_time = valid_divs[0].text.strip() if valid_divs else time_td.text.strip()
                actual_time = scheduled_time

            # --- 2. Xử lý Cột 1: Tách Destination và IATA ---
            # Ví dụ: "Ho Chi Minh City (SGN)"
            destination_full = cols[1].text.strip()

            # Dùng Regex để tách phần tên và phần trong ngoặc
            # (.+?) lấy phần chữ trước dấu cách và ngoặc đơn
            # \((.*?)\) lấy phần chữ nằm trong ngoặc
            match = re.search(r'(.+?)\s*\((.*?)\)', destination_full)

            if match:
                clean_destination = match.group(1).strip()  # Kết quả: "Ho Chi Minh City"
                iata_code = match.group(2).strip()  # Kết quả: "SGN"
            else:
                clean_destination = destination_full
                iata_code = ""

            # --- 3. Xử lý Cột 4: Số hiệu chuyến bay (Flight Number) ---
            raw_flight_no = "".join(cols[4].find_all(string=True, recursive=False))
            clean_flight_no = raw_flight_no.replace('"', '').strip()

            # --- 4. Xử lý Cột 6: Terminal (Chỉ lấy số 1 hoặc 2) ---
            raw_terminal = "".join(cols[6].find_all(string=True, recursive=False))
            clean_terminal = raw_terminal.replace('"', '').strip()

            # --- 5. Xử lý Cột 8: Gate chuẩn ---
            clean_gate = cols[8].text.strip()

            # --- LẮP RÁP DATA ---
            flight_info = {
                "Crawl_Date": target_date_str,
                "Scheduled_Time": scheduled_time,
                "Actual_Time": actual_time,
                "Destination": clean_destination,
                "IATA": iata_code,
                "Airline": cols[3].text.strip(),
                "Flight_No": clean_flight_no,
                "Checkin_Time": cols[5].text.strip(),
                "Terminal": clean_terminal,
                "Checkin_Counter": cols[7].text.strip(),
                "Gate": clean_gate,
                "Status": cols[9].text.strip()
            }
            flights_data.append(flight_info)

    print(f"  > Hoàn tất ngày {target_date_str}: Cào được {len(flights_data)} chuyến.")
    return flights_data

if __name__ == "__main__":
    all_flights = []

    start_date = datetime(2026, 3, 16)
    end_date = datetime(2026, 3, 16)

    current = start_date

    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')

        # Gọi hàm cào
        daily_data = crawl_dad_historical_flights_edge(date_str)
        all_flights.extend(daily_data)

        # Tiến lên 1 ngày
        current += timedelta(days=1)

        # Ngủ đông 3 giây để tránh làm sập server của Cảng vụ Đà Nẵng
        time.sleep(3)

        # Xuất xưởng ra file CSV
    print("\n[!] Đang lưu toàn bộ dữ liệu ra file CSV...")
    df = pd.DataFrame(all_flights)
    df.to_csv("dad_flights_departure_bronze_layer.csv", index=False, encoding='utf-8-sig')
    print(f"[v] Thành công! Đã lưu tổng cộng {len(df)} chuyến bay.")