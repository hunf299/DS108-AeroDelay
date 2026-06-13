import os
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime, timedelta
import re
import concurrent.futures
import threading
import traceback

# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
VN_IATAS = ['DAD', 'SGN', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']
START_DATE = "2026-01-17"
END_DATE = "2026-01-18"

DEST_IATA = os.environ.get("ORIGIN_DATA", "HAN")

PROJECT_ROOT = Path.cwd().parent.parent.resolve()

BRONZE = PROJECT_ROOT / "Data" / "Bronze_layer"
ARRIVAL_DIR = BRONZE / "Arrival" / f"{DEST_IATA.lower()}_flights_arrival_bronze_layer.csv"

csv_lock = threading.Lock()
browser_init_lock = threading.Lock()

rpm_lock = threading.Lock()
total_processed_flights = 0
scraping_start_time = None

# ================= CÁC HÀM HỖ TRỢ =================
def format_date_short(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except:
        return date_str.replace("-", "")


def is_empty_val(val):
    v_str = str(val).strip().lower()
    return pd.isna(val) or v_str in ['', 'n/a', '—', 'unknown', 'nan']


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


def start_undetected_browser(thread_id):
    with browser_init_lock:
        print(f"[Luồng {thread_id}] Đang khởi tạo Browser...")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        profile_dir = os.path.join(base_dir, f"chrome_profile_thread_{thread_id}")
        os.makedirs(profile_dir, exist_ok=True)

        options = uc.ChromeOptions()
        options.add_argument("--disable-notifications")
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

def append_to_csv(result_dict, output_path, columns):
    with csv_lock:
        file_exists = os.path.exists(output_path)
        df_new = pd.DataFrame([result_dict], columns=columns)
        df_new.to_csv(output_path, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')

def sort_final_csv(file_path):
    try:
        print("\n[*] Đang tiến hành sắp xếp lại thứ tự file CSV...")
        df = pd.read_csv(file_path)
        # Sắp xếp: Crawl_Date tăng dần (True), Actual_Time giảm dần từ 23:59 -> 00:00 (False)
        df.sort_values(by=['Crawl_Date', 'Actual_Time'], ascending=[True, False], inplace=True)
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print("[v] Đã sắp xếp file chuẩn xác!")
    except Exception as e:
        print(f"[X] Lỗi khi sắp xếp file: {e}")

# ================= KỊCH BẢN CHÍNH ================
def crawl_arrivals_history_fast(date_chunk, thread_id):
    print(f"[+] Khởi động trình duyệt undetected_chrome cào Flightradar24...")

    try:
        driver = start_undetected_browser(thread_id)
        driver.get("https://www.flightradar24.com")
        wait_for_manual_login(driver, thread_id)
        driver.maximize_window()

        # Mở trang lịch sử sân bay 1 lần duy nhất ở Tab chính
        base_url = f"https://www.flightradar24.com/airport/{DEST_IATA.lower()}/arrivals"
        driver.get(base_url)
        time.sleep(3)

        for target_date in date_chunk:
            print(f"\n{'='*50}")
            print(f"========== ĐANG CÀO NGÀY: {target_date} ==========")
            print(f"{'='*50}")

            # --- BẪY THỜI GIAN: CHỜ NGƯỜI DÙNG CHỌN NGÀY ---
            print(f"\n[!!!] HÀNH ĐỘNG CẦN THIẾT [!!!]")
            print(f"Vui lòng quay sang trình duyệt và chọn ngày '{target_date}' trên Calendar.")
            print("Tool đang tự động lắng nghe thẻ <h3> để nhận diện...")

            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            month_str = target_dt.strftime("%b")
            month_full = target_dt.strftime("%B")
            day_str = str(target_dt.day)

            pattern_short = rf"\b{month_str} {day_str}\b"
            pattern_full = rf"\b{month_full} {day_str}\b"

            while True:
                try:
                    h3_element = driver.find_element(By.CSS_SELECTOR, "h3.inline-flex.items-center.text-sm")
                    h3_text = h3_element.text.strip()
                    if re.search(pattern_short, h3_text) or re.search(pattern_full, h3_text):
                        print(f"\n  [v] Đã nhận diện đúng ngày: '{h3_text}'")
                        print("  [>] Chờ 2s cho dữ liệu bảng ổn định...")
                        time.sleep(2)
                        break
                except Exception:
                    pass
                time.sleep(1)

            try:
                try:
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "ul[data-testid='airport-history__results-list']")))
                except TimeoutException:
                    print(f"  [?] Không có dữ liệu chuyến bay nào cho ngày {target_date}.")
                    continue

                flights = driver.find_elements(By.CSS_SELECTOR, 'li[data-testid="airport-history__result-item"]')
                total_flights = len(flights)
                if total_flights == 0: continue

                print(f"  > Tìm thấy {total_flights} chuyến bay hạ cánh.")

                for i in range(total_flights):
                    try:
                        # Chống lỗi Stale Element bằng cách lấy lại danh sách sau mỗi vòng lặp
                        current_flights = driver.find_elements(By.CSS_SELECTOR,
                                                               'li[data-testid="airport-history__result-item"]')
                        if i >= len(current_flights): break
                        flight = current_flights[i]

                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", flight)
                        time.sleep(0.3)

                        html_outer = flight.get_attribute("outerHTML")
                        soup_outer = BeautifulSoup(html_outer, 'html.parser')

                        def get_text_safe(soup_obj, test_id):
                            el = soup_obj.find(attrs={"data-testid": test_id})
                            return el.text.strip() if el else ""

                        actual_time = get_text_safe(soup_outer, "airport-history__result-item__time").replace('\n', '')
                        origin = get_text_safe(soup_outer, "airport-history__result-item__airport-city")
                        iata_code = get_text_safe(soup_outer, "airport-history__result-item__airport-iata")

                        clickable_div = flight.find_element(By.CSS_SELECTOR,
                                                            "div[data-testid='airport-history__result-item__data']")

                        category, airline, flight_no, arrival_runway, tail_number, aircraft_type, ui_terminal = "", "", "", "", "", "", ""

                        for attempt in range(3):
                            # Mở tab nếu đang đóng
                            details_check = flight.find_elements(By.CSS_SELECTOR,
                                                                 "dl[data-testid='airport-history__result-item__details__category']")
                            if not details_check or not details_check[0].is_displayed():
                                driver.execute_script("arguments[0].click();", clickable_div)

                            try:
                                WebDriverWait(flight, 4).until(EC.visibility_of_element_located(
                                    (By.CSS_SELECTOR, "dl[data-testid='airport-history__result-item__details__category']")))
                                time.sleep(1.2)
                            except TimeoutException:
                                pass

                            soup_inner = BeautifulSoup(flight.get_attribute("outerHTML"), 'html.parser')

                            # Hút dữ liệu
                            cat_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__category"})
                            category_raw = cat_el.find('dd').text.strip().lower() if cat_el and cat_el.find('dd') else ""
                            category = "unknown" if not category_raw or category_raw in ["n/a", "—", ""] else category_raw

                            airline_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__airline"})
                            airline = airline_el.find('dd').text.strip() if airline_el and airline_el.find('dd') else ""

                            fno_el = soup_inner.find(attrs={"data-testid": "airport-history__result-item__details__flight"})
                            flight_no = fno_el.find('dd').text.strip() if fno_el and fno_el.find('dd') else ""

                            runway_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__runway"})
                            arrival_runway = runway_el.find('dd').text.strip() if runway_el and runway_el.find('dd') else ""

                            tail_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__aircraft-registration"})
                            tail_number = tail_el.get_text(separator="", strip=True) if tail_el else ""

                            ac_code_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__aircraft-code"})
                            aircraft_type = ac_code_el.text.strip() if ac_code_el else ""

                            # Quét linh động lấy Flight Time và Terminal
                            ui_terminal = ""
                            dt_tags = soup_inner.find_all('dt')
                            for dt in dt_tags:
                                dt_text = dt.text.strip().lower()
                                if "terminal" in dt_text:
                                    dd_tag = dt.find_next_sibling('dd')
                                    if dd_tag: ui_terminal = dd_tag.text.strip()

                            if category == "unknown" or is_empty_val(aircraft_type):
                                if attempt < 2:
                                    print(f"      [~] Bị ẩn Data (Cat/AC/Time). Click Lần {attempt + 1}/3...")
                                    driver.execute_script("arguments[0].click();", clickable_div)
                                    time.sleep(1.0)
                                    continue
                            break

                        # ================= LOGIC GÁN TERMINAL =================
                        if category == "cargo":
                            terminal_val = "0"
                        elif ui_terminal and ui_terminal.lower() not in ["n/a", "—", "-", "unknown", ""]:
                            terminal_val = ui_terminal
                        else:
                            if DEST_IATA.upper() == "SGN":
                                if iata_code in VN_IATAS:
                                    if "vietjet" in airline.lower().replace(" ", ""):
                                        terminal_val = "1"
                                    else:
                                        terminal_val = "3"
                                else:
                                    terminal_val = "2"
                            else:
                                terminal_val = "1" if iata_code in VN_IATAS else "2"

                        # Đóng gói dữ liệu
                        record = {
                            "Crawl_Date": target_date,
                            "Actual_Time": actual_time,
                            "Origin": origin,
                            "IATA": iata_code,
                            "Airline": airline,
                            "Flight_No": flight_no,
                            "Terminal": terminal_val,
                            "Arrival_Runway": arrival_runway,
                            "Status": "Landed",
                            "Actual_Tail": tail_number,
                            "Aircraft_Type": aircraft_type,
                            "Category": category
                        }

                        cols = ["Crawl_Date", "Actual_Time", "Origin", "IATA", "Airline", "Flight_No",
                                "Terminal", "Arrival_Runway", "Status", "Actual_Tail", "Aircraft_Type", "Category"]
                        append_to_csv(record, ARRIVAL_DIR,cols)

                        update_and_print_rpm(thread_id)

                        print(f"  [Luồng {thread_id}] [{i + 1}/{total_flights}] {flight_no} | Đã ghi file.")

                        print(
                            f"  [{i + 1}/{total_flights}] {flight_no} | Nguồn: {iata_code} | ATA: {actual_time} | Term: {terminal_val} | AC: {aircraft_type} | TN: {tail_number} | Category: {category}")

                    except Exception as e:
                        print(f"  [!] Lỗi bóc tách dòng {i + 1}: {type(e).__name__} - {str(e).splitlines()[0]}")
                        continue

            except Exception as e:
                print(f"[!] Lỗi khi xử lý ngày {target_date}: {type(e).__name__}")
                continue

    except Exception as e:
        print(f"\n[Luồng {thread_id}] BỊ LỖI CRASH:")
        traceback.print_exc()
    finally:
        try:
            driver.quit()
        except:
            pass
        print(f"\n[Luồng {thread_id}] ĐÃ XONG!")

def run_multithreading():
    date_list = pd.date_range(start=START_DATE, end=END_DATE).strftime('%Y-%m-%d').tolist()
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
        future1 = executor.submit(crawl_arrivals_history_fast, part1, 1)
        future2 = executor.submit(crawl_arrivals_history_fast, part2, 2)

        try:
            future1.result()
            future2.result()
        except Exception as e:
            print(f"[X] Có lỗi nghiêm trọng làm sập tiến trình: {e}")

    sort_final_csv(ARRIVAL_DIR)

    print(f"\n[V] ĐÃ XONG TOÀN BỘ QUÁ TRÌNH!")

if __name__ == "__main__":
    run_multithreading()