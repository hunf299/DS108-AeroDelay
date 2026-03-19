from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime, timedelta
import json
import os
import random

# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
VN_IATAS = ['SGN', 'DAD', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']
START_DATE = "2025-12-16"
END_DATE = "2025-12-20"

DEST_IATA = "HAN"
LIMIT_DATE = datetime(2025, 12, 1)
CACHE_FILE = f"{DEST_IATA.lower()}_fixed_flights_arrival_cache.json"

ENG_MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
INV_ENG_MONTHS = {v: k for k, v in ENG_MONTHS.items()}


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


def wait_for_manual_login(driver):
    print("\nCHỜ ĐĂNG NHẬP TÀI KHOẢN")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print("\n[v] Đã nhận diện tài khoản!\n")
                break
            time.sleep(3)
        except:
            time.sleep(3)


def format_date_short(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except:
        return date_str.replace("-", "")


def get_std_from_ui(driver, flight_no, t_fmt1, t_fmt2, p_fmt1, p_fmt2, actual_time, cached_std, dest_iata,
                    flight_element=None):
    std_result, is_fixed, info_origin, info_iata, info_airline, is_valid = "", 0, "", "", "", False
    full_schedule = {}

    flight_slug = flight_no.replace(' ', '').lower()
    url = f"https://www.flightradar24.com/data/flights/{flight_slug}"

    time.sleep(random.uniform(1.5, 2.5))
    initial_handles = len(driver.window_handles)

    if flight_element:
        try:
            info_btn = flight_element.find_element(By.CSS_SELECTOR,
                                                   "a[data-testid='flight-actions__action-flight-info']")
            js_hack_click = "var btn = arguments[0]; var target_url = arguments[1]; btn.setAttribute('href', target_url); btn.setAttribute('target', '_blank'); btn.click();"
            driver.execute_script(js_hack_click, info_btn, url)
            time.sleep(1.0)
        except:
            pass

    if len(driver.window_handles) <= initial_handles:
        driver.execute_script(f"window.open('{url}', '_blank');")
        time.sleep(1.0)

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

                    dest_tag = f"({dest_iata.lower()})"
                    r_from, r_to = row_from.lower(), row_to.lower()

                    # Nếu sân bay đích hiện tại lại nằm ở cột khởi hành
                    if dest_tag in r_from: continue
                    # Nếu sân bay đích hiện tại KHÔNG nằm ở cột hạ cánh
                    if dest_tag not in r_to and r_to not in ["", "—", "n/a", "unknown"]: continue

                    row_origin, row_iata = "", ""
                    if "canceled" not in row_status:
                        if cols[3].find('a'):
                            row_iata = cols[3].find('a').text.replace('(', '').replace(')', '').strip()
                            row_origin = ' '.join(
                                cols[3].get_text(separator=" ").replace(cols[3].find('a').text, '').split())
                        else:
                            row_origin = cols[3].text.strip()

                    if row_date not in full_schedule: full_schedule[row_date] = []
                    full_schedule[row_date].append(
                        {'std': row_std, 'atd': row_atd, 'origin': row_origin, 'iata': row_iata})
                    all_stds.add(row_std)

            t_flights = full_schedule.get(t_fmt1, []) + full_schedule.get(t_fmt2, [])
            p_flights = full_schedule.get(p_fmt1, []) + full_schedule.get(p_fmt2, [])
            atd_mins = time_to_mins(actual_time)

            def assign_flight_info(f):
                nonlocal std_result, info_origin, info_iata, is_valid
                std_result = f['std']
                if f.get('origin'): info_origin = f['origin']
                if f.get('iata'): info_iata = f['iata']
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
        driver.close()
        driver.switch_to.window(driver.window_handles[0])

    return std_result, is_fixed, info_origin, info_iata, info_airline, is_valid, full_schedule


def crawl_historical_business_master():
    print(f"[+] Khởi động trình duyệt Edge ...")
    options = EdgeOptions()
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")

    driver = webdriver.Edge(options=options)
    driver.maximize_window()
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    date_list = pd.date_range(start=START_DATE, end=END_DATE).strftime('%Y-%m-%d').tolist()
    all_flights_data = []

    for target_date in date_list:
        print(f"\n========== ĐANG CÀO NGÀY: {target_date} ==========")
        # Đã đổi URL thành type=landings
        url = f"https://www.flightradar24.com/airport/{DEST_IATA.lower()}/history?type=landings&date={target_date}"
        driver.get(url)
        time.sleep(3)

        dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
        prev_dt_obj = dt_obj - timedelta(days=1)

        fmt1, fmt2 = get_fr24_date_formats(dt_obj)
        p_fmt1, p_fmt2 = get_fr24_date_formats(prev_dt_obj)

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
                    current_flights = driver.find_elements(By.CSS_SELECTOR,
                                                           'li[data-testid="airport-history__result-item"]')
                    if i >= len(current_flights): break
                    flight = current_flights[i]

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", flight)
                    time.sleep(0.3)

                    # Bóc tách bên ngoài bảng (Lấy Origin thay vì Destination)
                    html_outer = flight.get_attribute("outerHTML")
                    soup_outer = BeautifulSoup(html_outer, 'html.parser')

                    def get_text_safe(soup_obj, test_id):
                        el = soup_obj.find(attrs={"data-testid": test_id})
                        return el.text.strip() if el else ""

                    actual_time = get_text_safe(soup_outer, "airport-history__result-item__time").replace('\n', '')
                    origin = get_text_safe(soup_outer, "airport-history__result-item__airport-city")
                    iata_code = get_text_safe(soup_outer, "airport-history__result-item__airport-iata")

                    # Bung bảng chi tiết
                    clickable_div = flight.find_element(By.CSS_SELECTOR,
                                                        "div[data-testid='airport-history__result-item__data']")
                    driver.execute_script("arguments[0].click();", clickable_div)

                    WebDriverWait(flight, 8).until(EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, "dl[data-testid='airport-history__result-item__details__category']")))
                    time.sleep(1.0)

                    soup_inner = BeautifulSoup(flight.get_attribute("outerHTML"), 'html.parser')

                    # 1. Category
                    cat_el = soup_inner.find(attrs={"data-testid": "airport-history__result-item__details__category"})
                    category_raw = cat_el.find('dd').text.strip().lower() if cat_el and cat_el.find('dd') else ""
                    category = "unknown" if not category_raw or category_raw in ["n/a", "—", ""] else category_raw

                    # 2. Airline
                    airline_el = soup_inner.find(
                        attrs={"data-testid": "airport-history__result-item__details__airline"})
                    airline = airline_el.find('dd').text.strip() if airline_el and airline_el.find('dd') else ""

                    # 3. Flight No
                    fno_el = soup_inner.find(attrs={"data-testid": "airport-history__result-item__details__flight"})
                    flight_no = fno_el.find('dd').text.strip() if fno_el and fno_el.find('dd') else ""

                    # 4. Arrival Runway (Hạ cánh)
                    runway_el = soup_inner.find(attrs={"data-testid": "airport-history__result-item__details__runway"})
                    arrival_runway = runway_el.find('dd').text.strip() if runway_el and runway_el.find('dd') else ""

                    # 5. Tail Number (Dính liền)
                    tail_el = soup_inner.find(
                        attrs={"data-testid": "airport-history__result-item__details__aircraft-registration"})
                    tail_number = tail_el.get_text(separator="", strip=True) if tail_el else ""

                    # 6. Aircraft Type
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

                    if category == "cargo":
                        terminal_val = "0"
                    elif ui_terminal and ui_terminal.lower() not in ["n/a", "—", "-", "unknown", ""]:
                        terminal_val = ui_terminal
                    else:
                        if DEST_IATA.upper() == "SGN":
                            if iata_code in VN_IATAS:  # Bay nội địa
                                if "vietjet" in airline.lower().replace(" ", ""):
                                    terminal_val = "1"
                                else:
                                    terminal_val = "3"
                            else:
                                terminal_val = "2"  # SGN Quốc tế
                        else:
                            terminal_val = "1" if iata_code in VN_IATAS else "2"

                    is_invalid_flight_no = is_empty_val(flight_no)
                    cache_hit, is_fixed, scheduled_time = False, 0, ""
                    is_passenger_or_unknown = ("passenger" in category) or (category == "unknown")

                    if is_invalid_flight_no:
                        print(f"      [i] Chuyến thiếu Flight No -> Lấy ATA ({actual_time}) tính Congestion.")

                    elif is_passenger_or_unknown:
                        needs_deep = is_empty_val(origin) or is_empty_val(airline)
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
                                if is_empty_val(origin) and entry.get("origin"): origin, iata_code = entry.get(
                                    "origin"), entry.get("iata", iata_code)
                                if is_empty_val(airline) and entry.get("airline"): airline = entry.get("airline")

                                if is_empty_val(origin):
                                    if matched_f and matched_f.get("origin") and not is_empty_val(
                                            matched_f.get("origin")):
                                        origin, iata_code = matched_f["origin"], matched_f.get("iata", iata_code)
                                    else:
                                        for d_key, f_list in entry.get("schedule", {}).items():
                                            for f_item in (f_list if isinstance(f_list, list) else []):
                                                if isinstance(f_item, dict) and not is_empty_val(f_item.get("origin")):
                                                    origin, iata_code = f_item["origin"], f_item.get("iata", iata_code)
                                                    break
                                            if not is_empty_val(origin): break

                                needs_deep = is_empty_val(origin) or is_empty_val(airline) or is_empty_val(
                                    scheduled_time)

                        if not cache_hit or needs_deep:
                            print(f"      [!] Bật Flight Info check {flight_no}...")
                            std_res, is_fix, i_orig, i_iata, i_air, is_val, full_sched = get_std_from_ui(
                                driver, flight_no, fmt1, fmt2, p_fmt1, p_fmt2, actual_time,
                                scheduled_time if cache_hit else "", DEST_IATA, flight
                            )

                            if not is_val:
                                print(
                                    f"  [X] XÓA CHUYẾN {flight_no}: Không thấy lịch sử khớp giờ/sân bay trên bảng FR24.")
                                continue

                            if not cache_hit:
                                scheduled_time, is_fixed = std_res, is_fix

                            if needs_deep:
                                if is_empty_val(origin) and i_orig: origin, iata_code = i_orig, i_iata
                                if is_empty_val(airline) and i_air: airline = i_air

                            if flight_no not in flight_std_cache: flight_std_cache[flight_no] = {"schedule": {}}
                            if not is_empty_val(origin): flight_std_cache[flight_no]["origin"] = origin
                            if iata_code: flight_std_cache[flight_no]["iata"] = iata_code
                            if not is_empty_val(airline): flight_std_cache[flight_no]["airline"] = airline
                            flight_std_cache[flight_no]["type"] = "fixed" if is_fixed == 1 else "dynamic"
                            flight_std_cache[flight_no]["is_fixed"] = is_fixed
                            if is_fixed == 1: flight_std_cache[flight_no]["std"] = scheduled_time
                            if "schedule" not in flight_std_cache[flight_no]: flight_std_cache[flight_no][
                                "schedule"] = {}
                            flight_std_cache[flight_no]["schedule"].update(full_sched)
                            save_cache(flight_std_cache)
                    else:
                        print(
                            f"      [i] Chuyến {category.capitalize()[:10]} ({flight_no}) -> Lấy ATA ({actual_time}) tính Congestion.")

                    record = {
                        "Crawl_Date": target_date, "Scheduled_Time": scheduled_time, "Actual_Time": actual_time,
                        "Origin": origin, "IATA": iata_code, "Airline": airline, "Flight_No": flight_no,
                        "Terminal": terminal_val, "Arrival_Runway": arrival_runway,
                        "Status": "Landed", "Tail_Number": tail_number, "Aircraft_Type": aircraft_type,
                        "Is_Fixed_Flight": is_fixed, "Category": category
                    }
                    all_flights_data.append(record)

                    if is_passenger_or_unknown and not is_invalid_flight_no:
                        print_src = 'Cache+Tab' if cache_hit and needs_deep else 'Cache' if cache_hit else 'Tab'
                        print(
                            f"  [{i + 1}/{total_flights}] {flight_no} | TỪ: {iata_code} | AC: {aircraft_type} | Term: {terminal_val} | Nguồn: {print_src}")
                    else:
                        print(
                            f"  [{i + 1}/{total_flights}] {flight_no} | TỪ: {iata_code} | ATA: {actual_time} | Term: {terminal_val}")

                except Exception as e:
                    print(f"  [!] Lỗi bóc tách dòng {i + 1}: {type(e).__name__} - {str(e).splitlines()[0]}")
                    continue

            if all_flights_data:
                df = pd.DataFrame(all_flights_data)
                cols = ["Crawl_Date", "Scheduled_Time", "Actual_Time", "Origin", "IATA", "Airline", "Flight_No",
                        "Terminal", "Arrival_Runway", "Status", "Tail_Number", "Aircraft_Type", "Is_Fixed_Flight",
                        "Category"]
                df = df[cols]
                s_day = format_date_short(START_DATE)
                e_day = format_date_short(END_DATE)
                df.to_csv(f"{DEST_IATA.lower()}_arrivals_history_{s_day}_{e_day}.csv", index=False,
                          encoding='utf-8-sig')

        except Exception as e:
            print(f"[!] Lỗi khi xử lý ngày {target_date}: {type(e).__name__}")
            continue

    driver.quit()
    print(f"\n[v] HOÀN TẤT TOÀN BỘ QUÁ TRÌNH. TỔNG SỐ CHUYẾN ĐẾN: {len(all_flights_data)}")


if __name__ == "__main__":
    crawl_historical_business_master()