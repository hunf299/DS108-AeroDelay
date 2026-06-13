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
import json
import os
import random
import re
import concurrent.futures
import threading
import traceback


# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
VN_IATAS = ['HAN', 'SGN', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']
START_DATE = "2026-01-17"
END_DATE = "2026-01-18"

ORIGIN_IATA = os.environ.get("ORIGIN_DATA", "HAN")
LIMIT_DATE = datetime(2025, 12, 1)
PROJECT_ROOT = Path.cwd().parent.parent.resolve()

BRONZE = PROJECT_ROOT / "Data" / "Bronze_layer"
DEPARTURE_DIR = BRONZE / "Departure" / f"{ORIGIN_IATA.lower()}_flights_departure_bronze_layer.csv"
CACHE_FILE = BRONZE / "Departure" / f"{ORIGIN_IATA.lower()}_fixed_flights_cache.json"

ENG_MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
INV_ENG_MONTHS = {v: k for k, v in ENG_MONTHS.items()}

csv_lock = threading.Lock()
browser_init_lock = threading.Lock()

rpm_lock = threading.Lock()
total_processed_flights = 0
scraping_start_time = None

def get_fr24_date_formats(dt_obj):
    month_str = ENG_MONTHS[dt_obj.month]
    d1 = f"{dt_obj.day:02d} {month_str} {dt_obj.year}"
    d2 = f"{dt_obj.day} {month_str} {dt_obj.year}"
    return d1, d2


def parse_fr24_date(date_str):
    try:
        parts = date_str.split()
        if len(parts) == 3: return datetime(int(parts[2]), INV_ENG_MONTHS[parts[1]], int(parts[0]))
    except:
        pass
    return None


def time_to_mins(t_str):
    try:
        if pd.isna(t_str) or str(t_str).strip().lower() in ["", "—", "n/a", "unknown", "nan"]: return -1
        h, m = map(int, str(t_str).split(':'))
        return h * 60 + m
    except:
        return -1


def is_empty_val(val):
    v_str = str(val).strip().lower()
    return pd.isna(val) or v_str in ['', 'n/a', '—', 'unknown', 'nan']


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache_data):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=4, ensure_ascii=False)


flight_std_cache = load_cache()


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

def append_to_csv(result_dict, output_path, columns):
    with csv_lock:
        file_exists = os.path.exists(output_path)
        df_new = pd.DataFrame([result_dict], columns=columns)
        df_new.to_csv(output_path, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')

def format_date_short(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except:
        return date_str.replace("-", "")


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

def sort_final_csv(file_path):
    try:
        print("\n[*] Đang tiến hành sắp xếp lại thứ tự file CSV...")
        df = pd.read_csv(file_path)

        # Departure ưu tiên sort theo Actual_Time, nếu giống nhau mới sort Scheduled_Time
        df.sort_values(by=['Crawl_Date', 'Actual_Time', 'Scheduled_Time'],
                       ascending=[True, False, False], inplace=True)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print("[v] Đã sắp xếp file chuẩn xác!")
    except Exception as e:
        print(f"[X] Lỗi khi sắp xếp file: {e}")

# ================= HÀM MỞ FLIGHT INFO (BỔ SUNG AIRCRAFT TYPE) =================
def get_std_from_ui(driver, flight_no, t_fmt1, t_fmt2, p_fmt1, p_fmt2, actual_time, cached_std, origin_iata,
                    flight_element=None):
    std_result, is_fixed, info_dest, info_iata, info_airline, info_aircraft, is_valid = "", 0, "", "", "", "", False
    full_schedule = {}

    flight_slug = flight_no.replace(' ', '').lower()
    if flight_slug.startswith("bl"): flight_slug = "vn" + flight_slug[2:]
    url = f"https://www.flightradar24.com/data/flights/{flight_slug}"

    time.sleep(random.uniform(1.0, 2.0))
    main_window = driver.current_window_handle

    try:
        driver.switch_to.new_window('tab')
        driver.get(url)
    except Exception:
        # Fallback phòng hờ
        driver.execute_script(f"window.open('{url}', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "tbl-datatable")))
        time.sleep(1)

        soup_init = BeautifulSoup(driver.page_source, 'html.parser')
        h1_tag = soup_init.find('h1')
        if h1_tag and "Flight history for " in h1_tag.text:
            raw_h1 = h1_tag.text.replace("Flight history for ", "")
            info_airline = raw_h1.lower().split(" flight ")[
                0].title() if " flight " in raw_h1.lower() else raw_h1.strip()

        all_stds = set()
        click_count = 0

        while click_count < 10:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('tr', class_='data-row')
            if not rows: break

            reached_limit = False
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 11:
                    date_td = row.find('td', attrs={"data-time-format": "DD MMM YYYY"})
                    row_date = date_td.text.strip() if date_td else cols[2].text.strip()

                    row_date_obj = parse_fr24_date(row_date)
                    if row_date_obj and row_date_obj < LIMIT_DATE:
                        reached_limit = True;
                        continue

                    row_from = cols[3].find('a', class_='fs-10 fbold').text.strip() if cols[3].find('a') else cols[
                        3].text.strip()
                    row_to = cols[4].find('a', class_='fs-10 fbold').text.strip() if cols[4].find('a') else cols[
                        4].text.strip()

                    row_std = cols[7].text.strip()
                    row_atd = cols[8].text.strip()
                    row_status = cols[10].text.strip().lower()

                    if not row_std or row_std == "—": continue

                    origin_tag = f"({origin_iata.lower()})"
                    r_from, r_to = row_from.lower(), row_to.lower()
                    if origin_tag in r_to: continue
                    if origin_tag not in r_from and r_from not in ["", "—", "n/a", "unknown"]: continue

                    row_dest, row_iata, row_aircraft = "", "", ""
                    if "canceled" not in row_status:
                        if cols[4].find('a'):
                            row_iata = cols[4].find('a').text.replace('(', '').replace(')', '').strip()
                            row_dest = ' '.join(
                                cols[4].get_text(separator=" ").replace(cols[4].find('a').text, '').split())
                        else:
                            row_dest = cols[4].text.strip()

                        # Hút loại máy bay (Cột số 5, VD: "B78X (VN-A874)" -> lấy "B78X")
                        if len(cols) > 5:
                            row_aircraft = cols[5].text.split('(')[0].strip()

                    if row_date not in full_schedule: full_schedule[row_date] = []
                    full_schedule[row_date].append(
                        {'std': row_std, 'atd': row_atd, 'dest': row_dest, 'iata': row_iata, 'aircraft': row_aircraft})
                    all_stds.add(row_std)

            t_flights = full_schedule.get(t_fmt1, []) + full_schedule.get(t_fmt2, [])
            p_flights = full_schedule.get(p_fmt1, []) + full_schedule.get(p_fmt2, [])
            atd_mins = time_to_mins(actual_time)

            def assign_flight_info(f):
                nonlocal std_result, info_dest, info_iata, info_aircraft, is_valid
                std_result = f['std']
                if f.get('dest'): info_dest = f['dest']
                if f.get('iata'): info_iata = f['iata']
                if f.get('aircraft'): info_aircraft = f['aircraft']
                is_valid = True

            def find_best_match(flights, target_atd, target_std):
                if not flights: return None
                if target_std:
                    for f in flights:
                        if f['std'] == target_std: return f
                for f in flights:
                    if f['atd'] == target_atd: return f
                return flights[0]

            matched_flight = None
            if t_flights:
                matched_flight = find_best_match(t_flights, actual_time, cached_std)
            elif p_flights:
                temp_match = find_best_match(p_flights, actual_time, cached_std)
                if temp_match:
                    sm = time_to_mins(temp_match['std'])
                    if (cached_std and temp_match['std'] == cached_std) or temp_match['atd'] == actual_time or (
                            sm != -1 and atd_mins != -1 and sm > atd_mins):
                        matched_flight = temp_match

            if matched_flight:
                assign_flight_info(matched_flight)
                break

            if reached_limit: break

            try:
                load_btn = driver.find_element(By.ID, "btn-load-earlier-flights")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", load_btn)
                time.sleep(1.0)
                click_count += 1
            except:
                break

        is_fixed = 1 if (len(all_stds) == 1 and len(full_schedule) > 1) else 0

    except TimeoutException:
        pass
    except Exception as e:
        pass
    finally:
        try:
            # So sánh ID: Nếu đang ở tab mới thì mới được phép close
            if driver.current_window_handle != main_window:
                driver.close()

            # Luôn ép trình duyệt quay lại focus vào tab chính
            driver.switch_to.window(main_window)
        except:
            pass

    return std_result, is_fixed, info_dest, info_iata, info_airline, info_aircraft, is_valid, full_schedule


# ================= KỊCH BẢN CHÍNH (DEPARTURE) =================
def crawl_historical_business_master(date_chunk, thread_id):
    print(f"[+] Khởi động trình duyệt cào Departures cho {ORIGIN_IATA}...")

    try:
        driver = start_undetected_browser(thread_id)
        driver.get("https://www.flightradar24.com")
        wait_for_manual_login(driver, thread_id)
        driver.maximize_window()

        # Mở trang lịch sử sân bay 1 lần duy nhất ở Tab chính =
        base_url = f"https://www.flightradar24.com/airport/{ORIGIN_IATA.lower()}/departures"
        driver.get(base_url)
        time.sleep(3)

        for target_date in date_chunk:
            print(f"\n{'='*50}")
            print(f"========== ĐANG CÀO NGÀY: {target_date} ==========")
            print(f"{'='*50}")

            dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
            prev_dt_obj = dt_obj - timedelta(days=1)

            fmt1, fmt2 = get_fr24_date_formats(dt_obj)
            p_fmt1, p_fmt2 = get_fr24_date_formats(prev_dt_obj)

            # --- BẪY THỜI GIAN: CHỜ NGƯỜI DÙNG CHỌN NGÀY ---
            print(f"\n[!!!] HÀNH ĐỘNG CẦN THIẾT [!!!]")
            print(f"Vui lòng quay sang trình duyệt và chọn ngày '{target_date}' trên Calendar.")
            print("Tool đang tự động lắng nghe thẻ <h3> để nhận diện...")

            month_str = dt_obj.strftime("%b")
            month_full = dt_obj.strftime("%B")
            day_str = str(dt_obj.day)

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

                print(f"  > Tìm thấy {total_flights} chuyến bay.")

                for i in range(total_flights):
                    try:
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
                        destination = get_text_safe(soup_outer, "airport-history__result-item__airport-city")
                        iata_code = get_text_safe(soup_outer, "airport-history__result-item__airport-iata")

                        clickable_div = flight.find_element(By.CSS_SELECTOR,
                                                            "div[data-testid='airport-history__result-item__data']")

                        # ================= VÒNG LẶP RETRY ĐỂ BUNG BẢNG UI =================
                        category, airline, flight_no, departure_runway, tail_number, aircraft_type, ui_terminal = "", "", "", "", "", "", ""

                        for attempt in range(3):
                            details_check = flight.find_elements(By.CSS_SELECTOR,
                                                                 "dl[data-testid='airport-history__result-item__details__category']")
                            if not details_check or not details_check[0].is_displayed():
                                driver.execute_script("arguments[0].click();", clickable_div)

                            try:
                                WebDriverWait(flight, 4).until(EC.visibility_of_element_located(
                                    (By.CSS_SELECTOR, "dl[data-testid='airport-history__result-item__details__category']")))
                                time.sleep(1.2)  # Chờ render
                            except TimeoutException:
                                pass

                            soup_inner = BeautifulSoup(flight.get_attribute("outerHTML"), 'html.parser')

                            # Hút Dữ liệu
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
                            departure_runway = runway_el.find('dd').text.strip() if runway_el and runway_el.find(
                                'dd') else ""

                            tail_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__aircraft-registration"})
                            tail_number = tail_el.get_text(separator="", strip=True) if tail_el else ""

                            ac_code_el = soup_inner.find(
                                attrs={"data-testid": "airport-history__result-item__details__aircraft-code"})
                            aircraft_type = ac_code_el.text.strip() if ac_code_el else ""

                            ui_terminal = ""
                            dt_tags = soup_inner.find_all('dt')
                            for dt in dt_tags:
                                if "Terminal" in dt.text:
                                    dd_tag = dt.find_next_sibling('dd')
                                    if dd_tag: ui_terminal = dd_tag.text.strip()
                                    break

                            # Điều kiện retry UI
                            if category == "unknown" or is_empty_val(aircraft_type):
                                if attempt < 2:
                                    print(f"      [~] Ẩn Data (Cat/AC). Click Đóng/Mở UI Lần {attempt + 1}/3...")
                                    driver.execute_script("arguments[0].click();", clickable_div)
                                    time.sleep(1.0)
                                    continue
                            break

                        # Logic Gán Terminal
                        if category == "cargo":
                            terminal_val = "0"
                        elif ui_terminal and ui_terminal.lower() not in ["n/a", "—", "-", "unknown", ""]:
                            terminal_val = ui_terminal
                        else:
                            if ORIGIN_IATA.upper() == "SGN":
                                if iata_code in VN_IATAS:
                                    if "vietjet" in airline.lower().replace(" ", ""):
                                        terminal_val = "1"
                                    else:
                                        terminal_val = "3"
                                else:
                                    terminal_val = "2"
                            else:
                                terminal_val = "1" if iata_code in VN_IATAS else "2"

                        # ================= LOGIC CHỮA LÀNH TỪ JSON (CÓ AIRCRAFT_TYPE) =================
                        is_invalid_flight_no = is_empty_val(flight_no)
                        cache_hit, is_fixed, scheduled_time = False, 0, ""
                        is_passenger_or_unknown = ("passenger" in category) or (category == "unknown")

                        if is_invalid_flight_no:
                            print(f"      [i] Chuyến thiếu Flight No -> Lấy ATD ({actual_time}) tính Congestion.")

                        elif is_passenger_or_unknown:
                            needs_deep = is_empty_val(destination) or is_empty_val(airline) or is_empty_val(aircraft_type)
                            atd_mins = time_to_mins(actual_time)

                            if flight_no in flight_std_cache:
                                entry = flight_std_cache[flight_no]
                                matched_f = None

                                if entry.get("type") == "fixed":
                                    scheduled_time, is_fixed, cache_hit = entry["std"], 1, True
                                elif entry.get("type") == "dynamic":
                                    sched = entry.get("schedule", {})
                                    t_flights, p_flights = [], []
                                    for f_date in [fmt1, fmt2]:
                                        val = sched.get(f_date)
                                        if val: t_flights.extend(
                                            val if isinstance(val, list) else [{'std': val, 'atd': ''}])
                                    for f_date in [p_fmt1, p_fmt2]:
                                        val = sched.get(f_date)
                                        if val: p_flights.extend(
                                            val if isinstance(val, list) else [{'std': val, 'atd': ''}])

                                    if t_flights:
                                        if len(t_flights) == 1:
                                            scheduled_time, cache_hit, matched_f = t_flights[0]['std'], True, t_flights[0]
                                        else:
                                            for f in t_flights:
                                                if f['atd'] == actual_time:
                                                    scheduled_time, cache_hit, matched_f = f['std'], True, f;
                                                    break
                                            if not matched_f: scheduled_time, cache_hit, matched_f = t_flights[0][
                                                'std'], True, t_flights[0]

                                    if not cache_hit and p_flights:
                                        for f in p_flights:
                                            sm = time_to_mins(f['std'])
                                            if f['atd'] == actual_time or (sm != -1 and atd_mins != -1 and sm > atd_mins):
                                                scheduled_time, cache_hit, matched_f = f['std'], True, f;
                                                break

                                if cache_hit and needs_deep:
                                    if is_empty_val(destination) and entry.get("dest"): destination, iata_code = entry.get(
                                        "dest"), entry.get("iata", iata_code)
                                    if is_empty_val(airline) and entry.get("airline"): airline = entry.get("airline")
                                    if is_empty_val(aircraft_type) and entry.get("aircraft"): aircraft_type = entry.get(
                                        "aircraft")

                                    if is_empty_val(destination):
                                        if matched_f and matched_f.get("dest") and not is_empty_val(matched_f.get("dest")):
                                            destination, iata_code = matched_f["dest"], matched_f.get("iata", iata_code)
                                        else:
                                            for d_key, f_list in entry.get("schedule", {}).items():
                                                for f_item in (f_list if isinstance(f_list, list) else []):
                                                    if isinstance(f_item, dict) and not is_empty_val(f_item.get("dest")):
                                                        destination, iata_code = f_item["dest"], f_item.get("iata",
                                                                                                            iata_code)
                                                        break
                                                if not is_empty_val(destination): break

                                    needs_deep = is_empty_val(destination) or is_empty_val(airline) or is_empty_val(
                                        scheduled_time) or is_empty_val(aircraft_type)

                            if not cache_hit or needs_deep:
                                print(f"      [!] Bật Flight Info check {flight_no}...")
                                std_res, is_fix, i_dest, i_iata, i_air, i_ac, is_val, full_sched = get_std_from_ui(
                                    driver, flight_no, fmt1, fmt2, p_fmt1, p_fmt2, actual_time,
                                    scheduled_time if cache_hit else "", ORIGIN_IATA, flight
                                )

                                if not is_val:
                                    print(f"  [X] XÓA CHUYẾN {flight_no}: Không thấy lịch sử khớp giờ/sân bay trên bảng.")
                                    continue

                                if not cache_hit:
                                    scheduled_time, is_fixed = std_res, is_fix

                                if needs_deep:
                                    if is_empty_val(destination) and i_dest: destination, iata_code = i_dest, i_iata
                                    if is_empty_val(airline) and i_air: airline = i_air
                                    if is_empty_val(aircraft_type) and i_ac: aircraft_type = i_ac

                                if flight_no not in flight_std_cache: flight_std_cache[flight_no] = {"schedule": {}}
                                if not is_empty_val(destination): flight_std_cache[flight_no]["dest"] = destination
                                if iata_code: flight_std_cache[flight_no]["iata"] = iata_code
                                if not is_empty_val(airline): flight_std_cache[flight_no]["airline"] = airline
                                if not is_empty_val(aircraft_type): flight_std_cache[flight_no][
                                    "aircraft"] = aircraft_type
                                flight_std_cache[flight_no]["type"] = "fixed" if is_fixed == 1 else "dynamic"
                                flight_std_cache[flight_no]["is_fixed"] = is_fixed
                                if is_fixed == 1: flight_std_cache[flight_no]["std"] = scheduled_time
                                if "schedule" not in flight_std_cache[flight_no]: flight_std_cache[flight_no][
                                    "schedule"] = {}
                                flight_std_cache[flight_no]["schedule"].update(full_sched)
                                save_cache(flight_std_cache)
                        else:
                            print(
                                f"      [i] Chuyến {category.capitalize()[:10]} ({flight_no}) -> Lấy ATD ({actual_time}) tính Congestion.")

                        record = {
                            "Crawl_Date": target_date, "Scheduled_Time": scheduled_time, "Actual_Time": actual_time,
                            "Destination": destination, "IATA": iata_code, "Airline": airline, "Flight_No": flight_no,
                            "Terminal": terminal_val, "Departure_Runway": departure_runway,
                            "Status": "Departed", "Scheduled_Tail": tail_number, "Aircraft_Type": aircraft_type,
                            "Is_Fixed_Flight": is_fixed, "Category": category
                        }

                        cols = ["Crawl_Date", "Scheduled_Time", "Actual_Time", "Destination", "IATA", "Airline",
                                "Flight_No",
                                "Terminal", "Departure_Runway", "Status", "Scheduled_Tail", "Aircraft_Type",
                                "Is_Fixed_Flight",
                                "Category"]

                        append_to_csv(record, DEPARTURE_DIR, cols)

                        update_and_print_rpm(thread_id)

                        print(f"  [Luồng {thread_id}] [{i + 1}/{total_flights}] {flight_no} | Đã ghi file.")

                        if is_passenger_or_unknown and not is_invalid_flight_no:
                            print_src = 'Cache+Tab' if cache_hit and needs_deep else 'Cache' if cache_hit else 'Tab'
                            print(
                                f"  [{i + 1}/{total_flights}] {flight_no} | Đích: {iata_code} | AC: {aircraft_type} | Term: {terminal_val} | Nguồn: {print_src}")
                        else:
                            print(
                                f"  [{i + 1}/{total_flights}] {flight_no} | Đích: {iata_code} | ATD: {actual_time} | Term: {terminal_val}")

                    except Exception as e:
                        print(f"  [!] Lỗi bóc tách dòng {i + 1}: {type(e).__name__} - {str(e).splitlines()[0]}")
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
        future1 = executor.submit(crawl_historical_business_master, part1, 1)
        future2 = executor.submit(crawl_historical_business_master, part2, 2)

        try:
            future1.result()
            future2.result()
        except Exception as e:
            print(f"[X] Có lỗi nghiêm trọng làm sập tiến trình: {e}")

    sort_final_csv(DEPARTURE_DIR)

    print(f"\n[V] ĐÃ XONG TOÀN BỘ QUÁ TRÌNH!")

if __name__ == "__main__":
    run_multithreading()