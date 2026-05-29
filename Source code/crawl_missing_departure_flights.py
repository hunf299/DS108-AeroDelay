from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import undetected_chromedriver as uc
import time
import re
import os
import concurrent.futures
import threading
import traceback

# ================= CẤU HÌNH ĐƯỜNG DẪN & HẰNG SỐ =================
AUDIT_FILE = r"Z:\PycharmProjects\DS108_AeroDelay\Data crawl\Silver_layer\Audit\audit_arrival_without_departure.csv"
OUTPUT_CSV = r"Z:\PycharmProjects\DS108_AeroDelay\Source code\patched_missing_departures.csv"
LIMIT_DATE = datetime(2025, 12, 15)

VN_IATAS = ['DAD', 'SGN', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH',
            'HUI', 'VCL', 'UIH', 'TBB', 'PXU', 'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']

# KHÓA ĐA LUỒNG
csv_lock = threading.Lock()
browser_init_lock = threading.Lock()

CSV_COLUMNS = [
    "Crawl_Date", "Scheduled_Time", "Actual_Time", "Destination", "IATA",
    "Airline", "Flight_No", "Terminal", "Departure_Runway", "Status",
    "Tail_Number", "Aircraft_Type", "Is_Fixed_Flight", "Category"
]


# ================= HÀM TIỆN ÍCH =================
def start_undetected_browser(thread_id):
    with browser_init_lock:
        print(f"[Luồng {thread_id}] Đang khởi tạo Browser...")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        profile_dir = os.path.join(base_dir, f"chrome_profile_thread_{thread_id}")
        os.makedirs(profile_dir, exist_ok=True)

        options = uc.ChromeOptions()
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        driver = uc.Chrome(options=options, user_data_dir=profile_dir, version_main=148)

        if thread_id == 1:
            driver.set_window_rect(0, 0, 900, 800)
        else:
            driver.set_window_rect(900, 0, 900, 800)

        print(f"[Luồng {thread_id}] Đã khởi tạo Browser thành công!")
        time.sleep(3)
        return driver


def wait_for_manual_login(driver, thread_id):
    print(f"\n[!!!] [Luồng {thread_id}] CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            if driver.find_element(By.ID, "auth-button"):
                print(f"\n[v] [Luồng {thread_id}] Đã nhận diện tài khoản!")
                break
        except:
            pass
        time.sleep(3)


def parse_fr24_date(date_str):
    try:
        return datetime.strptime(date_str, "%d %b %Y")
    except:
        return None


def extract_time(time_str):
    match = re.search(r'\d{2}:\d{2}', time_str)
    return match.group() if match else None


def get_terminal_departure(origin_iata, dest_iata, flight_no, airline):
    """
    Xác định Terminal cho chuyến bay ĐI (Departure).
    Dựa vào điểm đến (dest_iata) để biết là bay nội địa hay quốc tế.
    Trả về Terminal của điểm xuất phát (origin_iata).
    """
    is_domestic = dest_iata.upper() in VN_IATAS
    if not is_domestic: return "2"  # Quốc tế luôn T2

    if origin_iata.upper() in ['DAD', 'HAN']:
        return "1"
    elif origin_iata.upper() == 'SGN':
        if str(flight_no).upper().startswith('VJ') or 'vietjet' in str(airline).lower():
            return "1"
        else:
            return "3"
    return "N/A"


# ================= QUẢN LÝ OUTPUT =================
def initialize_output_file():
    if not os.path.exists(OUTPUT_CSV):
        df_empty = pd.DataFrame(columns=CSV_COLUMNS)
        df_empty.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print(f"[*] Đã tạo mới file Output: {OUTPUT_CSV}")
    else:
        print(f"[*] File Output {OUTPUT_CSV} đã tồn tại. Dữ liệu mới sẽ được ghi nối tiếp.")


def append_to_csv(result_dict):
    with csv_lock:
        df_new = pd.DataFrame([result_dict])
        df_new.to_csv(OUTPUT_CSV, mode='a', header=False, index=False, encoding='utf-8-sig')


# ================= WORKER ĐA LUỒNG =================
def worker_process(dataframe_chunk, thread_id):
    try:
        driver = start_undetected_browser(thread_id)
        driver.get("https://www.flightradar24.com")
        wait_for_manual_login(driver, thread_id)

        time.sleep(3)

        for idx, row in dataframe_chunk.iterrows():
            flight_no = str(row['Flight_No']).strip()
            # Sử dụng cột Arr_Service_Date và Arr_Event_Time từ Audit
            target_arr_date_str = str(row['Arr_Service_Date']).strip()
            target_arr_time = extract_time(str(row['Arr_Event_Time']))

            origin_iata = str(row['Origin']).strip().upper()
            dest_iata = str(row['Destination']).strip().upper()

            print(
                f"\n[Luồng {thread_id}] Đang check: {flight_no} | Arrival: {target_arr_date_str} {target_arr_time} | {origin_iata}->{dest_iata}")

            try:
                target_date_obj = datetime.strptime(target_arr_date_str, "%Y-%m-%d")
            except:
                print(f"  [Luồng {thread_id}] Bỏ qua do lỗi parse ngày ({target_arr_date_str})")
                continue

            url_code = flight_no.replace(' ', '').lower()
            if url_code.startswith("bl"): url_code = "vn" + url_code[2:]
            driver.get(f"https://www.flightradar24.com/data/flights/{url_code}")
            time.sleep(3)

            # Lấy tên hãng
            airline_name = "Unknown"
            soup_init = BeautifulSoup(driver.page_source, 'html.parser')
            h1_tag = soup_init.find('h1')
            if h1_tag and "Flight history for " in h1_tag.text:
                raw_h1 = h1_tag.text.replace("Flight history for ", "")
                if " flight " in raw_h1.lower():
                    airline_name = raw_h1.lower().split(" flight ")[0].title()

            # Bấm Load More
            click_count = 0
            while click_count < 50:
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                rows = soup.find_all('tr', class_='data-row')
                if not rows: break

                oldest_date_td = rows[-1].find('td', attrs={"data-time-format": "DD MMM YYYY"})
                if oldest_date_td:
                    oldest_date_obj = parse_fr24_date(oldest_date_td.text.strip())

                    # Dừng nếu tới Limit Date
                    if oldest_date_obj and oldest_date_obj <= LIMIT_DATE:
                        break

                    # Lùi 2 ngày so với ngày hạ cánh (Target) để phòng ngừa chuyến bay bay xuyên đêm
                    safe_target_date = target_date_obj - timedelta(days=2)
                    if oldest_date_obj and oldest_date_obj <= safe_target_date:
                        break

                try:
                    load_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.ID, "btn-load-earlier-flights")))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", load_btn)
                    time.sleep(2.5)
                    click_count += 1
                except:
                    break

            # Parse Dữ liệu so khớp
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('tr', class_='data-row')

            # Tạo Datetime hoàn chỉnh cho Target từ file Audit
            target_arr_dt = None
            if target_arr_time:
                target_arr_dt = datetime.combine(target_date_obj, datetime.strptime(target_arr_time, "%H:%M").time())

            matched = False
            for r in rows:
                cols = r.find_all('td')
                if len(cols) < 12: continue

                web_date_td = cols[2].text.strip()
                web_date_obj = parse_fr24_date(web_date_td)  # Đây là ngày CẤT CÁNH trên web
                if not web_date_obj: continue

                web_from = cols[3].text.strip()
                web_to = cols[4].text.strip()
                if f"({origin_iata})" not in web_from or f"({dest_iata})" not in web_to: continue

                web_std = extract_time(cols[7].text)
                web_atd = extract_time(cols[8].text)
                web_sta = extract_time(cols[9].text)
                status_text = cols[11].text.strip()
                web_landed = extract_time(status_text) if "Landed" in status_text else None

                # 1. Dựng Full Datetime cho CẤT CÁNH (STD & ATD)
                std_dt = None
                if web_std:
                    std_dt = datetime.combine(web_date_obj, datetime.strptime(web_std, "%H:%M").time())

                atd_dt = None
                if web_atd:
                    atd_dt = datetime.combine(web_date_obj, datetime.strptime(web_atd, "%H:%M").time())
                    # Nếu cất cánh thực tế nhỏ hơn cất cánh dự kiến -> bay qua nửa đêm
                    if std_dt and atd_dt.time() < std_dt.time():
                        atd_dt += timedelta(days=1)

                # 2. Dựng Full Datetime cho HẠ CÁNH (STA & Landed) dựa trên suy luận
                sta_dt = None
                if web_sta:
                    sta_dt = datetime.combine(web_date_obj, datetime.strptime(web_sta, "%H:%M").time())
                    # Nếu giờ STA nhỏ hơn giờ cất cánh (STD) -> hạ cánh sang ngày hôm sau
                    if std_dt and sta_dt.time() < std_dt.time():
                        sta_dt += timedelta(days=1)

                landed_dt = None
                if web_landed:
                    landed_dt = datetime.combine(web_date_obj, datetime.strptime(web_landed, "%H:%M").time())
                    # Mốc so sánh ưu tiên ATD, nếu không có ATD thì dùng STD
                    anchor_dt = atd_dt if atd_dt else std_dt
                    if anchor_dt and landed_dt.time() < anchor_dt.time():
                        landed_dt += timedelta(days=1)

                # 3. TIẾN HÀNH ĐỐI CHIẾU CHÍNH XÁC CẢ NGÀY LẪN GIỜ
                is_match = False
                if target_arr_dt:
                    if sta_dt and sta_dt == target_arr_dt:
                        is_match = True
                    elif landed_dt and landed_dt == target_arr_dt:
                        is_match = True

                if is_match:
                    dest_fullname = web_to.split('(')[0].strip()
                    crawl_date = web_date_obj.strftime("%Y-%m-%d")  # Ngày cất cánh

                    flight_status = "Departed"  # Audit departure mặc định là Departed

                    aircraft_type, actual_tail = "", ""
                    aircraft_col_text = cols[5].text.strip()
                    if '(' in aircraft_col_text and ')' in aircraft_col_text:
                        aircraft_type = aircraft_col_text.split('(')[0].strip()
                        actual_tail = aircraft_col_text.split('(')[1].replace(')', '').strip()

                    terminal = get_terminal_departure(origin_iata, dest_iata, flight_no, airline_name)

                    result_dict = {
                        "Crawl_Date": crawl_date,
                        "Scheduled_Time": std_dt.strftime("%Y-%m-%d %H:%M") if std_dt else "",
                        "Actual_Time": atd_dt.strftime("%Y-%m-%d %H:%M") if atd_dt else "",
                        "Destination": dest_fullname,
                        "IATA": dest_iata,
                        "Airline": airline_name,
                        "Flight_No": flight_no,
                        "Terminal": terminal,
                        "Departure_Runway": "",
                        "Status": flight_status,
                        "Tail_Number": actual_tail,
                        "Aircraft_Type": aircraft_type,
                        "Is_Fixed_Flight": "",
                        "Category": "passenger"
                    }

                    append_to_csv(result_dict)
                    print(
                        f"  [Luồng {thread_id}] [+] Đã ghi Departure chính xác: Cất cánh {crawl_date} | Tail {actual_tail}")

                    matched = True
                    break

            if not matched:
                print(f"  [Luồng {thread_id}] [-] Không tìm thấy khớp.")

        driver.quit()
        print(f"\n[Luồng {thread_id}] ĐÃ XONG!")
    except Exception as e:
        print(f"\n[Luồng {thread_id}] BỊ LỖI CRASH TRONG QUÁ TRÌNH CHẠY:")
        traceback.print_exc()


# ================= ĐIỀU PHỐI ĐA LUỒNG =================
def run_multithreading():
    if not os.path.exists(AUDIT_FILE):
        print(f"[X] Lỗi: Không tìm thấy file {AUDIT_FILE}")
        return

    df_audit = pd.read_csv(AUDIT_FILE)
    total_rows = len(df_audit)

    if total_rows == 0:
        print("[*] File Audit trống, không có chuyến bay nào để xử lý.")
        return

    initialize_output_file()

    half_point = total_rows // 2
    part1 = df_audit.iloc[:half_point]
    part2 = df_audit.iloc[half_point:]

    print(f"[*] Tổng số: {total_rows} chuyến")
    print(f"[*] Luồng 1 xử lý: {len(part1)} chuyến | Luồng 2 xử lý: {len(part2)} chuyến")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(worker_process, part1, 1)
        future2 = executor.submit(worker_process, part2, 2)

        try:
            future1.result()
            future2.result()
        except Exception as e:
            print(f"[X] Có lỗi nghiêm trọng làm sập tiến trình: {e}")

    print(f"\n[V] ĐÃ XONG TOÀN BỘ. Kết quả được lưu tại: {OUTPUT_CSV}")


if __name__ == "__main__":
    run_multithreading()