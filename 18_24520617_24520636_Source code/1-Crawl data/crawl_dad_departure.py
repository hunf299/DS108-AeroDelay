from pathlib import Path
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import concurrent.futures
import threading
import traceback
import os

PROJECT_ROOT = Path.cwd().parent.parent.resolve()

BRONZE = PROJECT_ROOT / "18_24520617_24520636_Data" / "Bronze_layer"
DEPARTURE_DIR = BRONZE / "Departure" / "dad_flights_departure_bronze_layer.csv"

csv_lock = threading.Lock()
browser_init_lock = threading.Lock()

rpm_lock = threading.Lock()
total_processed_flights = 0
scraping_start_time = None


def update_and_print_rpm(thread_id):
    global total_processed_flights, scraping_start_time
    with rpm_lock:
        total_processed_flights += 1
        if scraping_start_time is not None:
            elapsed_seconds = time.time() - scraping_start_time
            elapsed_minutes = elapsed_seconds / 60.0
            if elapsed_minutes > 0:
                rpm = total_processed_flights / elapsed_minutes
                print(
                    f"  ---> [RPM Monitor] Luồng {thread_id} | Tổng đã check: {total_processed_flights} chuyến | Tốc độ: {rpm:.2f} chuyến/phút")


def append_to_csv(result_dict, output_path, columns):
    with csv_lock:
        file_exists = os.path.exists(output_path)
        df_new = pd.DataFrame([result_dict], columns=columns)
        df_new.to_csv(output_path, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')


def start_edge_browser(thread_id):
    with browser_init_lock:
        print(f"[Luồng {thread_id}] Đang khởi tạo Edge Browser...")
        options = EdgeOptions()
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")

        driver = webdriver.Edge(options=options)

        if thread_id == 1:
            driver.set_window_rect(0, 0, 900, 800)
        else:
            driver.set_window_rect(900, 0, 900, 800)

        print(f"[Luồng {thread_id}] Đã khởi tạo Edge thành công!")
        time.sleep(2)
        return driver

def sort_final_csv(file_path):
    try:
        print("\n[*] Đang tiến hành sắp xếp lại thứ tự file CSV...")
        df = pd.read_csv(file_path)

        # Sắp xếp: Crawl_Date tăng dần (Ngày cũ -> Ngày mới)
        # Scheduled_Time tăng dần (00:00 -> 23:59)
        df.sort_values(by=['Crawl_Date', 'Scheduled_Time', 'Actual_Time'],
                       ascending=[True, True, True], inplace=True)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print("[v] Đã sắp xếp file chuẩn xác (Ngày và Giờ đều tăng dần)!")
    except Exception as e:
        print(f"[X] Lỗi khi sắp xếp file: {e}")

def crawl_dad_historical_flights_edge(date_chunk, thread_id):
    try:
        # 1. Mở trình duyệt
        driver = start_edge_browser(thread_id)

        for target_date_str in date_chunk:
            print(f"\n[Luồng {thread_id}] Đang cào ngày: {target_date_str}")
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
            while True:
                try:
                    load_more_btn = driver.find_element(By.CSS_SELECTOR, "button.load-more-btn")

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
            print(f"  [Luồng {thread_id}] > Bắt đầu bóc tách BeautifulSoup...")
            soup = BeautifulSoup(page_source, 'html.parser')

            # Tìm tất cả các dòng chứa dữ liệu chuyến bay
            rows = soup.find_all('tr', class_='datarows')

            # Cột cho Departure
            cols_departure = [
                "Crawl_Date", "Scheduled_Time", "Actual_Time", "Destination", "IATA",
                "Airline", "Flight_No", "Checkin_Time", "Terminal", "Checkin_Counter",
                "Gate", "Status"
            ]

            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 10:
                    try:
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
                        destination_full = cols[1].text.strip()
                        match = re.search(r'(.+?)\s*\((.*?)\)', destination_full)

                        if match:
                            clean_destination = match.group(1).strip()
                            iata_code = match.group(2).strip()
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

                        # GHI FILE TRỰC TIẾP & ĐẾM RPM
                        append_to_csv(flight_info, DEPARTURE_DIR, cols_departure)
                        update_and_print_rpm(thread_id)

                    except Exception as e:
                        print(f"    > [Luồng {thread_id}] Lỗi khi bóc tách một dòng dữ liệu: {e}")
                        continue

    except Exception as e:
        print(f"\n[Luồng {thread_id}] BỊ LỖI CRASH:")
        traceback.print_exc()
    finally:
        # Kết thúc luồng mới tắt trình duyệt
        try:
            driver.quit()
        except:
            pass
        print(f"\n[Luồng {thread_id}] ĐÃ XONG!")


# ================= ĐIỀU PHỐI ĐA LUỒNG =================
def run_multithreading():
    start_date = "2026-01-17"
    end_date = "2026-01-18"

    date_list = pd.date_range(start=start_date, end=end_date).strftime('%Y-%m-%d').tolist()
    total_days = len(date_list)

    if total_days == 0:
        print("[*] Không có ngày nào để xử lý.")
        return

    half_point = (total_days + 1) // 2
    part1 = date_list[:half_point]
    part2 = date_list[half_point:]

    print(f"[*] Tổng số ngày: {total_days}")
    print(f"[*] Luồng 1 xử lý: {len(part1)} ngày | Luồng 2 xử lý: {len(part2)} ngày")

    global scraping_start_time
    scraping_start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(crawl_dad_historical_flights_edge, part1, 1)
        future2 = executor.submit(crawl_dad_historical_flights_edge, part2, 2)

        try:
            future1.result()
            future2.result()
        except Exception as e:
            print(f"[X] Có lỗi nghiêm trọng làm sập tiến trình: {e}")

    sort_final_csv(DEPARTURE_DIR)

    print(f"\n[V] ĐÃ XONG TOÀN BỘ QUÁ TRÌNH!")


if __name__ == "__main__":
    run_multithreading()