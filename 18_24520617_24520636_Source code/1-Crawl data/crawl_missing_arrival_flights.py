from pathlib import Path
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
PROJECT_ROOT = Path.cwd().parent.parent.resolve()
if not (PROJECT_ROOT / "18_24520617_24520636_Data").exists():
    raise FileNotFoundError("Cannot find project root containing '18_24520617_24520636_Data'.")

SILVER = PROJECT_ROOT / "18_24520617_24520636_Data" / "Silver_layer"
AUDIT_FILE = SILVER / "Audit" / "audit_departure_without_arrival.csv"
OUTPUT_CSV = PROJECT_ROOT / "18_24520617_24520636_Data" / "final_merged_patched_flights.csv"
LIMIT_DATE = datetime(2025, 12, 15)

VN_IATAS = ['DAD', 'SGN', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH',
            'HUI', 'VCL', 'UIH', 'TBB', 'PXU', 'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']

# KHÓA ĐA LUỒNG
csv_lock = threading.Lock()
browser_init_lock = threading.Lock()

# QUẢN LÝ TỐC ĐỘ RPM
rpm_lock = threading.Lock()
total_processed_flights = 0
scraping_start_time = None

CSV_COLUMNS = [
    "Crawl_Date", "Scheduled_Time", "Actual_Time", "Origin", "IATA",
    "Airline", "Flight_No", "Terminal", "Arrival_Runway", "Status",
    "Actual_Tail", "Aircraft_Type", "Category"
]


# ================= HÀM TIỆN ÍCH =================
def update_and_print_rpm(thread_id):
    global total_processed_flights, scraping_start_time
    with rpm_lock:
        total_processed_flights += 1

        # Chỉ tính thời gian nếu đã bắt đầu cào thực sự
        if scraping_start_time is not None:
            elapsed_seconds = time.time() - scraping_start_time
            elapsed_minutes = elapsed_seconds / 60.0

            if elapsed_minutes > 0:
                rpm = total_processed_flights / elapsed_minutes
                print(
                    f"  ---> [RPM Monitor] Luồng {thread_id} | Tổng đã check: {total_processed_flights} chuyến | Tốc độ: {rpm:.2f} chuyến/phút")

def start_undetected_browser(thread_id):
    """
    Sử dụng browser_init_lock để đảm bảo 2 luồng không tranh nhau gọi uc.Chrome() cùng 1 tíc tắc.
    """
    with browser_init_lock:
        print(f"[Luồng {thread_id}] Đang khởi tạo Browser...")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        profile_dir = os.path.join(base_dir, f"chrome_profile_thread_{thread_id}")
        os.makedirs(profile_dir, exist_ok=True)
        # --------------------------

        options = uc.ChromeOptions()
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        # Khởi tạo browser
        driver = uc.Chrome(options=options, user_data_dir=profile_dir, version_main=148)

        # Sắp xếp 2 cửa sổ
        if thread_id == 1:
            driver.set_window_rect(0, 0, 900, 800)
        else:
            driver.set_window_rect(900, 0, 900, 800)

        print(f"[Luồng {thread_id}] Đã khởi tạo Browser thành công!")
        time.sleep(3)  # Nghỉ 3 giây trước khi nhả Lock cho luồng tiếp theo
        return driver


def wait_for_manual_login(driver, thread_id):
    print(f"\n[!!!] LUỒNG {thread_id} CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print(f"\n[v] LUỒNG {thread_id} đã nhận diện tài khoản Business!\n")
                break
            time.sleep(2)
        except:
            time.sleep(2)


def parse_fr24_date(date_str):
    try:
        return datetime.strptime(date_str, "%d %b %Y")
    except:
        return None


def extract_time(time_str):
    match = re.search(r'\d{2}:\d{2}', time_str)
    return match.group() if match else None


def get_terminal(origin_iata, dest_iata, flight_no, airline):
    is_domestic = origin_iata.upper() in VN_IATAS
    if not is_domestic: return "2"

    if dest_iata.upper() in ['DAD', 'HAN']:
        return "1"
    elif dest_iata.upper() == 'SGN':
        if str(flight_no).upper().startswith('VJ') or 'vietjet' in str(airline).lower():
            return "1"
        else:
            return "3"
    return "N/A"


# ================= TẠO FILE CSV OUTPUT =================
def initialize_output_file():
    if not os.path.exists(OUTPUT_CSV):
        df_empty = pd.DataFrame(columns=CSV_COLUMNS)
        df_empty.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print(f"[*] Đã tạo mới file Output: {OUTPUT_CSV}")
    else:
        print(f"[*] File Output {OUTPUT_CSV} đã tồn tại. Dữ liệu mới sẽ được ghi nối tiếp (append).")


def append_to_csv(result_dict):
    with csv_lock:
        df_new = pd.DataFrame([result_dict])
        df_new.to_csv(OUTPUT_CSV, mode='a', header=False, index=False, encoding='utf-8-sig')


# ================= HÀM XỬ LÝ CHÍNH CHO TỪNG LUỒNG =================
def worker_process(dataframe_chunk, thread_id):
    try:
        driver = start_undetected_browser(thread_id)
        driver.get("https://www.flightradar24.com")
        wait_for_manual_login(driver, thread_id)

        time.sleep(3)

        for idx, row in dataframe_chunk.iterrows():
            flight_no = str(row['Flight_No']).strip()
            target_dep_date_str = str(row['Dep_Service_Date']).strip()
            origin_iata = str(row['Origin']).strip().upper()
            dest_iata = str(row['Destination']).strip().upper()
            target_atd = extract_time(str(row['Dep_Event_Time']))
            target_std = extract_time(str(row['Scheduled_Time']))

            print(f"\n[Luồng {thread_id}] Đang check: {flight_no} | {target_dep_date_str} | {origin_iata}->{dest_iata}")
            target_date_obj = datetime.strptime(target_dep_date_str, "%Y-%m-%d")

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

            # Bấm Load More (Tối đa 50 lần để đảm bảo lùi đủ xa)
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

                    # Quét sâu hơn 1 ngày so với ngày Target để đảm bảo bảng load đủ 24h
                    safe_target_date = target_date_obj - timedelta(days=1)
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
                    break  # Hết nút Load More

            # Parse Dữ liệu so khớp
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('tr', class_='data-row')

            matched = False
            for r in rows:
                cols = r.find_all('td')
                if len(cols) < 12: continue

                web_date_td = cols[2].text.strip()
                web_date_obj = parse_fr24_date(web_date_td)
                if not web_date_obj or web_date_obj != target_date_obj: continue

                web_from = cols[3].text.strip()
                web_to = cols[4].text.strip()
                if f"({origin_iata})" not in web_from or f"({dest_iata})" not in web_to: continue

                web_std = extract_time(cols[7].text)
                web_atd = extract_time(cols[8].text)
                web_sta = extract_time(cols[9].text)
                status_text = cols[11].text.strip()

                if (target_std and target_std == web_std) or (target_atd and target_atd == web_atd):
                    origin_fullname = web_from.split('(')[0].strip()

                    sta_dt = None
                    if web_sta and web_atd:
                        atd_dt = datetime.combine(web_date_obj, datetime.strptime(web_atd, "%H:%M").time())
                        sta_dt = datetime.combine(web_date_obj, datetime.strptime(web_sta, "%H:%M").time())
                        if sta_dt.time() < atd_dt.time(): sta_dt += timedelta(days=1)

                    flight_status = "Unknown"
                    actual_time_dt = None
                    if "Landed" in status_text:
                        flight_status = "Landed"
                        landed_time = extract_time(status_text)
                        if landed_time and web_atd:
                            actual_time_dt = datetime.combine(web_date_obj,
                                                              datetime.strptime(landed_time, "%H:%M").time())
                            if actual_time_dt.time() < atd_dt.time(): actual_time_dt += timedelta(days=1)

                    crawl_date = ""
                    if dest_iata == 'DAD' and sta_dt:
                        crawl_date = sta_dt.strftime("%Y-%m-%d")
                    elif dest_iata in ['HAN', 'SGN'] and actual_time_dt:
                        crawl_date = actual_time_dt.strftime("%Y-%m-%d")
                    else:
                        crawl_date = target_dep_date_str

                    aircraft_type, actual_tail = "", ""
                    aircraft_col_text = cols[5].text.strip()
                    if '(' in aircraft_col_text and ')' in aircraft_col_text:
                        aircraft_type = aircraft_col_text.split('(')[0].strip()
                        actual_tail = aircraft_col_text.split('(')[1].replace(')', '').strip()

                    terminal = get_terminal(origin_iata, dest_iata, flight_no, airline_name)

                    result_dict = {
                        "Crawl_Date": crawl_date,
                        "Scheduled_Time": sta_dt.strftime("%Y-%m-%d %H:%M") if sta_dt else "",
                        "Actual_Time": actual_time_dt.strftime("%Y-%m-%d %H:%M") if actual_time_dt else "",
                        "Origin": origin_fullname,
                        "IATA": origin_iata,
                        "Airline": airline_name,
                        "Flight_No": flight_no,
                        "Terminal": terminal,
                        "Arrival_Runway": "",
                        "Status": flight_status,
                        "Actual_Tail": actual_tail,
                        "Aircraft_Type": aircraft_type,
                        "Category": "passenger"
                    }

                    # Ghi ngay lập tức
                    append_to_csv(result_dict)
                    print(f"  [Luồng {thread_id}] [+] Đã ghi: Date {crawl_date} | Tail {actual_tail}")

                    matched = True
                    break

            if not matched:
                print(f"  [Luồng {thread_id}] [-] Không tìm thấy khớp.")

            update_and_print_rpm(thread_id)

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

    global scraping_start_time
    scraping_start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(worker_process, part1, 1)
        future2 = executor.submit(worker_process, part2, 2)

        # Lệnh result() sẽ ép Python hiện lỗi ra màn hình nếu luồng bị crash
        try:
            future1.result()
            future2.result()
        except Exception as e:
            print(f"[X] Có lỗi nghiêm trọng làm sập tiến trình: {e}")

    print(f"\n[V] ĐÃ XONG TOÀN BỘ. Kết quả được lưu tại: {OUTPUT_CSV}")


if __name__ == "__main__":
    run_multithreading()