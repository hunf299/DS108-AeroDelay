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
VN_IATAS = ['HAN', 'DAD', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']

ORIGIN_IATA = "SGN"
LIMIT_DATE = datetime(2025, 12, 1)
CACHE_FILE = f"{ORIGIN_IATA.lower()}_fixed_flights_cache.json"

ENG_MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
INV_ENG_MONTHS = {v: k for k, v in ENG_MONTHS.items()}


# ================= CÁC HÀM HỖ TRỢ & BỘ NHỚ =================
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
    print("\n[!!!] CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print("\n[v] Đã nhận diện tài khoản Business!\n")
                break
            time.sleep(3)
        except:
            time.sleep(3)


# ================= HÀM MỞ FLIGHT INFO (Chỉ kích hoạt khi thiếu Data crawl) =================
def get_std_from_ui(driver, flight_no, t_fmt1, t_fmt2, p_fmt1, p_fmt2, actual_time, cached_std, origin_iata,
                    flight_element=None):
    std_result, is_fixed, info_dest, info_iata, info_airline, is_valid = "", 0, "", "", "", False
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
                    row_std, row_atd = cols[7].text.strip(), cols[8].text.strip()
                    row_status = cols[10].text.strip().lower()

                    if not row_std or row_std == "—": continue
                    if f"({origin_iata.lower()})" in row_to.lower(): continue

                    row_dest, row_iata = "", ""
                    if "canceled" not in row_status:
                        if cols[4].find('a'):
                            row_iata = cols[4].find('a').text.replace('(', '').replace(')', '').strip()
                            row_dest = ' '.join(
                                cols[4].get_text(separator=" ").replace(cols[4].find('a').text, '').split())
                        else:
                            row_dest = cols[4].text.strip()

                    if row_date not in full_schedule: full_schedule[row_date] = []
                    full_schedule[row_date].append({'std': row_std, 'atd': row_atd, 'dest': row_dest, 'iata': row_iata})
                    all_stds.add(row_std)

            t_flights = full_schedule.get(t_fmt1, []) + full_schedule.get(t_fmt2, [])
            p_flights = full_schedule.get(p_fmt1, []) + full_schedule.get(p_fmt2, [])
            atd_mins = time_to_mins(actual_time)

            matched_flight = None
            if t_flights:
                matched_flight = next((f for f in t_flights if f['std'] == cached_std), None) or next(
                    (f for f in t_flights if f['atd'] == actual_time), t_flights[0])
            elif p_flights:
                for f in p_flights:
                    if f['std'] == cached_std or f['atd'] == actual_time or (
                            time_to_mins(f['std']) != -1 and atd_mins != -1 and time_to_mins(f['std']) > atd_mins):
                        matched_flight = f;
                        break

            if matched_flight:
                std_result = matched_flight['std']
                if matched_flight.get('dest'): info_dest = matched_flight['dest']
                if matched_flight.get('iata'): info_iata = matched_flight['iata']
                is_valid = True
                break

            if reached_limit: break
            try:
                btn = driver.find_element(By.ID, "btn-load-earlier-flights")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                driver.execute_script("arguments[0].click();", btn);
                time.sleep(1.0);
                click_count += 1
            except:
                break

        is_fixed = 1 if (len(all_stds) == 1 and len(full_schedule) > 1) else 0

    except:
        pass
    finally:
        driver.close();
        driver.switch_to.window(driver.window_handles[0])

    return std_result, is_fixed, info_dest, info_iata, info_airline, is_valid, full_schedule


# ================= KỊCH BẢN CHÍNH =================
def crawl_fr24_departures():
    print(f"[+] Khởi động trình duyệt Edge cào Flightradar24 ({ORIGIN_IATA})...")
    options = EdgeOptions()
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
    options.add_argument("--disable-notifications")

    driver = webdriver.Edge(options=options)
    url = f"https://www.flightradar24.com/airport/{ORIGIN_IATA.lower()}/departures"
    driver.get(url)

    try:
        cookie_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
        cookie_btn.click()
        print("  > Đã tắt bảng Cookie.")
        time.sleep(1)
    except:
        pass

    wait_for_manual_login(driver)
    time.sleep(3)

    # --- TÍNH NĂNG: NHẤN EARLIER FLIGHTS CHO ĐẾN KHI XÁM NÚT ---
    print("  [>] Đang tải toàn bộ dữ liệu hiện có bằng nút 'Earlier flights'...")
    while True:
        try:
            load_more_btn = driver.find_element(By.CSS_SELECTOR,
                                                "button[data-testid='airport-panel__schedules__earlier-flights']")
            if load_more_btn.get_attribute("disabled") is not None:
                print("  [v] Nút 'Earlier flights' đã bị vô hiệu hóa (màu xám). Bắt đầu lấy dữ liệu...")
                break
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_btn)
            time.sleep(0.5)
            load_more_btn.click()
            time.sleep(2.0)  # Đợi 2s để DOM cập nhật an toàn
        except Exception:
            break

    day_blocks_xpath = "//h3/ancestor::div[contains(@class, 'w-full')]"
    day_blocks = driver.find_elements(By.XPATH, day_blocks_xpath)
    num_days = len(day_blocks)
    flights_data = []

    print(f"[!] Tìm thấy {num_days} khối ngày hiển thị trên màn hình.")

    for d in range(num_days):
        # Re-find block ngày
        current_day_block = driver.find_elements(By.XPATH, day_blocks_xpath)[d]

        # 1. TRÍCH XUẤT VÀ XỬ LÝ NGÀY TỪ THẺ H3
        h3_text = current_day_block.find_element(By.TAG_NAME, "h3").text
        try:
            month_day_str = h3_text.split(',')[-1].strip()
            current_year = datetime.now().year
            parsed_date = datetime.strptime(f"{month_day_str} {current_year}", "%b %d %Y")
            crawl_date_val = parsed_date.strftime('%Y-%m-%d')
        except Exception:
            crawl_date_val = datetime.now().strftime('%Y-%m-%d')

        # 2. TÌM TẤT CẢ CHUYẾN BAY TRONG KHỐI NGÀY NÀY
        flights_in_day = current_day_block.find_elements(By.XPATH,
                                                         ".//li[contains(@class, 'airport__flight-list-item')]")
        num_flights = len(flights_in_day)
        print(f"\n========== ĐANG XỬ LÝ NGÀY: {crawl_date_val} ({num_flights} chuyến) ==========")

        for f in range(num_flights):
            try:
                # Re-find lại block và chuyến bay để chống lỗi giật DOM
                block_refresh = driver.find_elements(By.XPATH, day_blocks_xpath)[d]
                flight = block_refresh.find_elements(By.XPATH, ".//li[contains(@class, 'airport__flight-list-item')]")[
                    f]

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", flight)
                time.sleep(0.3)

                # ================= FIX LỖI CLICK HEADER MỚI =================
                # Thuộc tính flight-header__ đã bị FR24 xóa, giờ dùng thẻ div mang data-testid airport-panel__schedules__flight...
                header = flight.find_element(By.CSS_SELECTOR, "div[data-testid^='airport-panel__schedules__flight__']")
                driver.execute_script("arguments[0].click();", header)

                # Đợi render status
                WebDriverWait(flight, 4).until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div[data-testid='airport-flight-details__status']")))
                time.sleep(0.3)

                # CHUYỂN HTML CHO BEAUTIFULSOUP
                html = flight.get_attribute("outerHTML")
                soup = BeautifulSoup(html, 'html.parser')

                # ================= FIX LỖI ẨN MÃ TESTID CỦA FR24 =================
                def get_fr24_text(test_id):
                    # Tìm theo data-testid HOẶC testid (Vì FR24 xài lẫn lộn cả hai)
                    elem = soup.find(attrs={"data-testid": test_id}) or soup.find(attrs={"testid": test_id})
                    return elem.text.strip().replace('\n', '') if elem else ""

                status = get_fr24_text("airport-flight-details__status")
                flight_no = get_fr24_text("airport-flight-details__flight-number")
                if "unknown" in status.lower(): continue

                # Bóc tách IATA chuẩn
                dest_span = soup.find('span', class_=lambda c: c and 'truncate' in c and 'text-gray-1300' in c)
                destination = dest_span.text.strip() if dest_span else ""
                iata_code = ""
                if dest_span:
                    iata_wrapper = dest_span.find_next_sibling('span')
                    if iata_wrapper: iata_code = iata_wrapper.text.strip().replace('"', '')

                scheduled = get_fr24_text("airport-flight-details__scheduled-departure")
                actual = get_fr24_text("airport-flight-details__actual-departure")
                airline = get_fr24_text("airport-flight-details__airline")
                category = get_fr24_text("airport-flight-details__aircraft-category").lower()

                # ================= LẤY AIRCRAFT TYPE VÀ TAIL NUMBER =================
                tail_el = soup.find(attrs={"data-testid": "airport-flight-details__registration"})
                tail_number = tail_el.get_text(separator="", strip=True) if tail_el else ""

                aircraft_type = ""
                if tail_el and tail_el.parent:
                    # Aircraft code (Vd: B78X) nằm ở span class="mr-1" cùng cấp với thẻ Tail Number
                    ac_span = tail_el.parent.find('span', class_='mr-1')
                    if ac_span: aircraft_type = ac_span.text.strip()

                # ================= LẤY TERMINAL (TỪ THẺ <dt> VÀ <dd>) =================
                terminal_val = "1" if iata_code in VN_IATAS else "2"  # Giá trị mặc định
                dt_tags = soup.find_all('dt')
                for dt in dt_tags:
                    if "Terminal" in dt.text:
                        dd_tag = dt.find_next_sibling('dd')
                        if dd_tag: terminal_val = dd_tag.text.strip()
                        break

                # ================= KIỂM TRA CACHE & MỞ TAB BÙ THIẾU =================
                is_invalid_flight = is_empty_val(flight_no)
                cache_hit, is_fixed = False, 0
                is_passenger = "passenger" in category

                if not is_invalid_flight and is_passenger:
                    needs_deep = is_empty_val(destination) or is_empty_val(airline) or is_empty_val(scheduled)

                    if flight_no in flight_std_cache:
                        entry = flight_std_cache[flight_no]
                        is_fixed = entry.get("is_fixed", 0)
                        cache_hit = True

                        if needs_deep:
                            if is_empty_val(destination) and not is_empty_val(entry.get("dest")):
                                destination, iata_code = entry.get("dest"), entry.get("iata", iata_code)
                            if is_empty_val(airline) and not is_empty_val(entry.get("airline")):
                                airline = entry.get("airline")
                            needs_deep = is_empty_val(destination) or is_empty_val(airline) or is_empty_val(scheduled)

                    if not cache_hit or needs_deep:
                        dt_obj = datetime.strptime(crawl_date_val, "%Y-%m-%d")
                        fmt1, fmt2 = get_fr24_date_formats(dt_obj)
                        p_fmt1, p_fmt2 = get_fr24_date_formats(dt_obj - timedelta(days=1))

                        print(f"      [!] Bật Flight Info check {flight_no}...")
                        std_res, is_fix, i_dest, i_iata, i_air, is_val, full_sched = get_std_from_ui(
                            driver, flight_no, fmt1, fmt2, p_fmt1, p_fmt2, actual, scheduled, ORIGIN_IATA, flight
                        )

                        if is_val:
                            is_fixed = is_fix
                            if is_empty_val(scheduled) and std_res: scheduled = std_res
                            if is_empty_val(destination) and i_dest: destination, iata_code = i_dest, i_iata
                            if is_empty_val(airline) and i_air: airline = i_air

                            flight_std_cache[flight_no] = {
                                "type": "fixed" if is_fixed == 1 else "dynamic",
                                "is_fixed": is_fixed,
                                "dest": destination,
                                "iata": iata_code,
                                "airline": airline,
                                "schedule": full_sched
                            }
                            if is_fixed == 1: flight_std_cache[flight_no]["std"] = scheduled
                            save_cache(flight_std_cache)

                record = {
                    "Crawl_Date": crawl_date_val,
                    "Scheduled_Time": scheduled,
                    "Actual_Time": actual,
                    "Destination": destination,
                    "IATA": iata_code,
                    "Airline": airline,
                    "Flight_No": flight_no,
                    "Terminal": terminal_val,
                    "Departure_Runway": "",
                    "Status": status,
                    "Tail_Number": tail_number,
                    "Aircraft_Type": aircraft_type,
                    "Is_Fixed_Flight": is_fixed,
                    "Category": category
                }

                flights_data.append(record)

                print_src = 'Cache' if cache_hit and not needs_deep else 'Tab' if not cache_hit else 'C+T'
                print(
                    f"  [{f + 1}/{num_flights}] Cào OK: {flight_no} | Tail: {tail_number} | IATA: {iata_code} | Terminal: {terminal_val} | AC: {aircraft_type} | Src: {print_src}")

            except Exception as e:
                print(f"  [!] Lỗi chuyến {f + 1}: {str(e)[:40]}...")
                continue

    driver.quit()

    # LƯU FILE
    print("\n[!] Đang xuất file CSV...")
    if flights_data:
        df = pd.DataFrame(flights_data)
        s_date = df['Crawl_Date'].iloc[0].replace("-", "")[2:]
        e_date = df['Crawl_Date'].iloc[-1].replace("-", "")[2:]
        filename = f"{ORIGIN_IATA.lower()}_departures_fr24_{s_date}_{e_date}.csv"
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"[v] Xong! Thu hoạch được {len(df)} dòng dữ liệu từ {ORIGIN_IATA}. Đã lưu vào {filename}")
    else:
        print("[!] Không có dữ liệu để xuất.")


if __name__ == "__main__":
    crawl_fr24_departures()