from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime, timedelta
import re

def format_date_short(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except:
        return date_str.replace("-", "")

def crawl_dad_historical_flights_edge(target_date_str):
    print(f"\n[+] Khởi động trình duyệt Edge cho ngày: {target_date_str}")

    options = EdgeOptions()
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")

    driver = webdriver.Edge(options=options)

    url = f"https://danangairport.vn/flights-flight-status-arrival?f=1&t=0&date={target_date_str}&time=0"
    driver.get(url)
    time.sleep(3)

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

    while True:
        try:
            load_more_btn = driver.find_element(By.CSS_SELECTOR, "button.load-more-btn")

            if load_more_btn.get_attribute("disabled"):
                print("  > Nút Load More đã bị mờ (disabled). Đã bung hết dữ liệu!")
                break

            current_page = load_more_btn.get_attribute("data-current-page")
            total_pages = load_more_btn.get_attribute("data-total-pages")
            print(f"  > Đang bung trang {current_page} / {total_pages}...")

            driver.execute_script("arguments[0].click();", load_more_btn)
            time.sleep(3)

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
    print(f"  > Số dòng 'datarows' tìm thấy: {len(rows)}")

    for row in rows:
        cols = row.find_all('td')

        if len(cols) < 8:
            continue

        try:
            # --- 1. Xử lý Cột 0: Thời gian
            time_td = cols[0]
            scheduled_div = time_td.find('div', class_='del')
            scheduled_time = scheduled_div.get_text(strip=True) if scheduled_div else ""

            actual_time = ""
            for div in time_td.find_all('div'):
                if 'del' not in div.get('class', []):
                    actual_time = div.get_text(strip=True)
                    break

            if not scheduled_time: scheduled_time = actual_time

            # --- 2. Xử lý Cột 1: Điểm đến & IATA (Nằm trong thẻ <b>) ---
            # Ví dụ: "TP. Hồ Chí Minh (SGN)"
            destination_b = cols[1].find('b')
            destination_full = destination_b.get_text(strip=True) if destination_b else cols[1].get_text(strip=True)

            # Dùng Regex tách IATA
            match = re.search(r'(.+?)\s*\((.*?)\)', destination_full)
            if match:
                clean_destination = match.group(1).strip()
                iata_code = match.group(2).strip()
            else:
                clean_destination = destination_full
                iata_code = ""

            # --- 3. Xử lý Cột 3: Tên Hãng (Nằm trong thẻ <b>) ---
            airline_b = cols[3].find('b')
            airline_name = airline_b.get_text(strip=True) if airline_b else cols[3].get_text(strip=True)

            # --- 4. Xử lý Cột 4: Số hiệu chuyến bay
            raw_flight_no = "".join(cols[4].find_all(string=True, recursive=False))
            clean_flight_no = raw_flight_no.replace('"', '').strip()

            # --- 5. Xử lý Cột 5: Terminal
            raw_terminal = "".join(cols[5].find_all(string=True, recursive=False))
            clean_terminal = raw_terminal.replace('"', '').strip()

            clean_belt = cols[6].get_text(strip=True)

            status_span = cols[7].find('span')
            clean_status = status_span.get_text(strip=True) if status_span else cols[7].get_text(strip=True)

            # --- LẮP RÁP DATA ---
            flight_info = {
                "Crawl_Date": target_date_str,
                "Scheduled_Time": scheduled_time,
                "Actual_Time": actual_time,
                "Origin": clean_destination,
                "IATA": iata_code,
                "Airline": airline_name,
                "Flight_No": clean_flight_no,
                "Terminal": clean_terminal,
                "Belt": clean_belt,
                "Status": clean_status
            }
            flights_data.append(flight_info)

        except Exception as e:
            print(f"    > Lỗi khi bóc tách một dòng dữ liệu: {e}")
            continue

    print(f"  > Hoàn tất ngày {target_date_str}: Cào được {len(flights_data)} chuyến.")
    return flights_data


if __name__ == "__main__":
    all_flights = []

    start_date = "2026-02-26"
    end_date = "2026-02-26"

    current = datetime.strptime(start_date, "%Y-%m-%d")
    e_date = datetime.strptime(end_date, "%Y-%m-%d")


    while current <= e_date:
        date_str = current.strftime('%Y-%m-%d')

        # Gọi hàm cào
        daily_data = crawl_dad_historical_flights_edge(date_str)
        all_flights.extend(daily_data)

        # Tiến lên 1 ngày
        current += timedelta(days=1)

        time.sleep(3)

    print("\n[!] Đang lưu toàn bộ dữ liệu ra file CSV...")
    df = pd.DataFrame(all_flights)
    s_day = format_date_short(start_date)
    e_day = format_date_short(end_date)
    df.to_csv(f"dad_flights_{s_day}_{e_day}_arrival_bronze_layer.csv", index=False, encoding='utf-8-sig')
    print(f"[v] Thành công! Đã lưu tổng cộng {len(df)} chuyến bay.")