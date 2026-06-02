from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
import json
import os

# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
ORIGIN_IATA = "DAD"
CSV_FILE = f"Data crawl/Departure/{ORIGIN_IATA.lower()}_flights_departure_bronze_layer.csv"
CACHE_FILE = "dad_fixed_flights.json"
AIRCRAFT_CSV_FILE = f"{ORIGIN_IATA.lower()}_aircraft.csv"

ENG_MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
INV_ENG_MONTHS = {v: k for k, v in ENG_MONTHS.items()}


# ================= HÀM TIỆN ÍCH =================
def parse_fr24_date(date_str):
    """Parse ngày từ format FlightRadar24"""
    try:
        parts = date_str.split()
        if len(parts) >= 3:
            return datetime(int(parts[2]), INV_ENG_MONTHS[parts[1]], int(parts[0]))
    except:
        pass
    return None


def is_empty_val(val):
    """Kiểm tra giá trị trống"""
    v_str = str(val).strip().lower()
    return pd.isna(val) or v_str in ['', 'n/a', '—', 'unknown', 'nan']


def load_cache():
    """Load cache từ file JSON"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache_data):
    """Lưu cache vào file JSON"""
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=4, ensure_ascii=False)


# ================= CÁC HÀM XỬ LÝ SELENIUM (MỚI THÊM) =================
def get_earliest_flight_date(flights):
    """
    Lấy ngày của chuyến bay cũ nhất trong list hiện tại đang hiển thị.
    (Chuyến bay cuối cùng thường là cũ nhất)
    """
    try:
        last_flight = flights[-1]
        try:
            # Tìm theo thuộc tính data-time-format
            date_element = last_flight.find_element(By.XPATH, ".//td[@data-time-format='DD MMM YYYY']")
            date_str = date_element.text.strip()
        except:
            # Nếu không có thì lấy cột thứ 3 (như logic BeautifulSoup của bạn)
            cols = last_flight.find_elements(By.TAG_NAME, "td")
            if len(cols) > 2:
                date_str = cols[2].text.strip()
            else:
                return "9999-12-31"

        # Parse ngày
        dt_obj = parse_fr24_date(date_str)
        if dt_obj:
            return dt_obj.strftime("%Y-%m-%d")
    except Exception:
        pass
    return "9999-12-31"  # Trả về tương lai xa nếu lỗi để tiếp tục click 'Load More'


def load_flights_until_target_date(driver, target_date="2025-12-01"):
    """
    Tải dữ liệu bằng cách ép click nút Load More, kết hợp scroll mạnh mẽ.
    """
    print(f"    [>] Đang tải thêm dữ liệu chuyến bay đến ngày {target_date}...")
    click_count = 0
    max_retries = 3
    retries = 0

    while True:
        flights = driver.find_elements(By.XPATH, "//tr[contains(@class, 'data-row')]")
        if not flights:
            print("    [!] Không tìm thấy dòng dữ liệu nào.")
            break

        earliest_date = get_earliest_flight_date(flights)

        # Kiểm tra điều kiện dừng an toàn
        if earliest_date != "9999-12-31" and earliest_date <= target_date:
            print(f"    [v] Đã tải đến ngày {earliest_date} (Tổng {click_count} lần click)")
            break

        try:
            # Dùng WebDriverWait để đảm bảo nút thực sự tồn tại trên DOM
            load_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "btn-load-earlier-flights"))
            )

            if not load_btn.is_displayed():
                print("    [v] Nút tải thêm đã ẩn (Hết dữ liệu lịch sử).")
                break

            # Scroll xuống cuối cùng của trang trước khi click để tránh bị đè
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)

            # Cuộn nút vào giữa màn hình
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_btn)
            time.sleep(1)

            driver.execute_script("arguments[0].click();", load_btn)

            # Tăng thời gian chờ dữ liệu render (rất quan trọng)
            time.sleep(3.5)

            click_count += 1
            print(f"    [-] Đã click Load More lần {click_count} (Ngày cũ nhất hiện tại: {earliest_date})")
            retries = 0  # Reset retries nếu click thành công

        except Exception as e:
            if retries < max_retries:
                retries += 1
                print(f"    [!] Thử tìm lại nút Load More (Lần {retries})...")
                time.sleep(2)
                continue
            else:
                print(f"    [!] Đã hết chuyến bay hoặc lỗi: {str(e)[:50]}")
                break

def create_fixed_flights_cache_from_csv():
    print("\n[*] BƯỚC 1: Tạo file JSON từ CSV...")

    if not os.path.exists(CSV_FILE):
        print(f"  [X] Không tìm thấy file: {CSV_FILE}")
        return {}

    df = pd.read_csv(CSV_FILE)
    print(f"  [+] Tải {len(df)} dòng từ CSV")

    cache_data = {}

    for flight_no, group in df.groupby('Flight_No'):
        flight_no = str(flight_no).strip()
        if not flight_no or flight_no.lower() in ['nan', 'n/a', '']:
            continue

        schedule = {}

        for idx, row in group.iterrows():
            crawl_date = row['Crawl_Date']

            # Chuyển ngày từ YYYY-MM-DD sang DD Mon YYYY
            try:
                dt_obj = datetime.strptime(str(crawl_date), "%Y-%m-%d")
                fr24_date = f"{dt_obj.day:02d} {ENG_MONTHS[dt_obj.month]} {dt_obj.year}"
            except:
                fr24_date = crawl_date

            if fr24_date not in schedule:
                schedule[fr24_date] = []

            flight_info = {
                'std': str(row['Scheduled_Time']).strip() if pd.notna(row['Scheduled_Time']) else "—",
                'dest': str(row['Destination']).strip() if pd.notna(row['Destination']) else "",
                'iata': str(row['IATA']).strip() if pd.notna(row['IATA']) else "",
                'tail_number': str(row.get('Tail_Number', '')).strip() if pd.notna(row.get('Tail_Number', '')) else ""
            }

            schedule[fr24_date].append(flight_info)

        cache_data[flight_no] = {
            "schedule": schedule
        }

    save_cache(cache_data)
    print(f"  [v] Tạo thành công {len(cache_data)} flights vào {CACHE_FILE}")

    return cache_data

def wait_for_manual_login(driver):
    """Chờ người dùng đăng nhập Business Account"""
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


def crawl_tail_numbers_from_flight_info(cache_data):
    """
    Crawl tail number từ Flight Info page và map vào JSON.
    Hỗ trợ tra cứu chéo mã BL -> VN, khớp dữ liệu linh hoạt và BỎ QUA chuyến đã đủ data.
    """
    print("\n[*] BƯỚC 2: Crawl Tail Numbers từ Flight Info...")

    # === BƯỚC LỌC DỮ LIỆU (PRE-CHECK) ===
    flights_to_crawl = []

    for flight_no, data in cache_data.items():
        schedule = data.get('schedule', {})
        needs_crawl = False

        # Kiểm tra xem có ngày nào/chuyến nào bị trống tail_number không
        for date, flights in schedule.items():
            for f in flights:
                tail = str(f.get('tail_number', '')).strip()
                if not tail or tail in ['—', 'N/A', 'nan', 'NaN', 'None', 'unknown']:
                    needs_crawl = True
                    break  # Chỉ cần 1 chuyến thiếu là phải crawl lại mã này
            if needs_crawl:
                break

        if needs_crawl:
            flights_to_crawl.append(flight_no)

    print(f"  [i] Phát hiện {len(flights_to_crawl)} / {len(cache_data)} chuyến bay bị thiếu Tail Number cần crawl.")

    # Nếu JSON đã full data, không cần mở trình duyệt nữa
    if not flights_to_crawl:
        print("  [v] Tất cả chuyến bay đều đã có đủ Tail Number. Bỏ qua bước Crawl Web!")
        return cache_data

    # === KHỞI ĐỘNG TRÌNH DUYỆT ===
    print(f"[+] Khởi động trình duyệt undetected_chrome cào Flightradar24 ({ORIGIN_IATA})...")

    # Khởi tạo Options của undetected_chromedriver
    options = uc.ChromeOptions()
    options.add_argument("--disable-notifications")

    options.add_argument("--headless")

    # Khởi trị driver bằng uc
    driver = uc.Chrome(options=options)
    driver.maximize_window()
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    crawled_flights = 0
    flights_with_tail = 0

    # CHỈ LẶP QUA CÁC CHUYẾN BAY CÒN THIẾU DATA
    for flight_no in flights_to_crawl:
        print(f"\n  > Crawl: {flight_no}")

        # === XỬ LÝ MÃ BL -> VN ===
        search_flight_no = flight_no
        if flight_no.upper().startswith("BL"):
            search_flight_no = "VN" + flight_no[2:]
            print(f"    [i] Tự động đổi mã tra cứu: {flight_no} -> {search_flight_no}")

        flight_slug = search_flight_no.replace(' ', '').lower()
        url = f"https://www.flightradar24.com/data/flights/{flight_slug}"

        try:
            driver.get(url)
            time.sleep(2)

            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "tbl-datatable")))
            time.sleep(1)

            # ====== GỌI HÀM LOAD MORE CHỐNG TRƯỢT ======
            load_flights_until_target_date(driver, target_date="2025-12-01")
            # ==========================================

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('tr', class_='data-row')

            if not rows:
                print(f"    [?] Không tìm thấy dữ liệu")
                crawled_flights += 1
                continue

            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 6:
                    continue

                # 1. Lấy Ngày
                date_td = row.find('td', attrs={"data-time-format": "DD MMM YYYY"})
                row_date = date_td.text.strip() if date_td else cols[2].text.strip()

                # 2. Lấy Sân bay đến (Cột 4) để lọc nhiễu
                to_airport = cols[4].text.strip().lower()

                # 3. Lấy STD
                row_std = cols[7].text.strip() if len(cols) > 7 else ""

                # 4. Lấy Tail Number
                ac_col_text = cols[5].text.strip() if len(cols) > 5 else ""
                tail_number = ""
                if '(' in ac_col_text and ')' in ac_col_text:
                    tail_number = ac_col_text.split('(')[1].split(')')[0].strip()

                # 5. Khớp dữ liệu linh hoạt
                if tail_number and row_date in cache_data[flight_no]['schedule']:
                    for flight in cache_data[flight_no]['schedule'][row_date]:
                        # Bỏ qua nếu chuyến này ĐÃ CÓ tail_number từ các lần chạy trước
                        if flight.get('tail_number', '').strip() not in ['', '—', 'N/A', 'nan']:
                            continue

                        # Điều kiện 1: STD khớp hoàn toàn (Ưu tiên)
                        if flight['std'] == row_std:
                            flight['tail_number'] = tail_number
                            flights_with_tail += 1
                            print(f"    [{row_date}] {row_std} -> {tail_number} (Khớp STD)")
                            break

                        # Điều kiện 2: Lệch giờ vài phút nhưng IATA đích có trong chuỗi của FR24 (Giúp cứu vớt ZT661)
                        elif flight['iata'].lower() in to_airport:
                            flight['tail_number'] = tail_number
                            flights_with_tail += 1
                            print(
                                f"    [{row_date}] {row_std} -> {tail_number} (Lệch giờ, Khớp IATA: {flight['iata']})")
                            break

            crawled_flights += 1

        except Exception as e:
            print(f"    [!] Lỗi: {str(e)[:60]}")
            crawled_flights += 1
            continue

    driver.quit()

    print(f"\n  [v] Crawl thành công {crawled_flights} chuyến bay")
    print(f"  [v] Bổ sung thêm {flights_with_tail} flights với tail number")

    save_cache(cache_data)
    return cache_data

def create_aircraft_csv(cache_data):
    print("\n[*] BƯỚC 3: Tạo file Aircraft CSV...")

    tail_numbers = set()

    for flight_no, flight_data in cache_data.items():
        schedule = flight_data.get('schedule', {})
        for date, flights in schedule.items():
            for flight in flights:
                tail = flight.get('tail_number', '').strip()
                if tail and tail not in ['', '—', 'N/A', 'nan']:
                    tail_numbers.add(tail)

    tail_numbers = sorted(list(tail_numbers))
    print(f"  [+] Tìm thấy {len(tail_numbers)} unique tail numbers")

    aircraft_df = pd.DataFrame({
        'Aircraft_Type': [''] * len(tail_numbers),
        'Tail_Number': tail_numbers
    })

    aircraft_df.to_csv(AIRCRAFT_CSV_FILE, index=False, encoding='utf-8-sig')
    print(f"  [v] Tạo file {AIRCRAFT_CSV_FILE} thành công")

def calculate_is_fixed_for_flights(cache_data):
    print("\n[*] BƯỚC 3.5: Tính is_fixed cho các chuyến bay...")

    is_fixed_map = {}

    for flight_no, flight_data in cache_data.items():
        schedule = flight_data.get('schedule', {})

        if not schedule:
            is_fixed_map[flight_no] = 0
            continue

        all_stds = set()
        for date, flights in schedule.items():
            for flight in flights:
                std = flight.get('std', '').strip()
                if std and std not in ['—', 'N/A', 'nan']:
                    all_stds.add(std)

        num_dates = len(schedule)
        num_unique_stds = len(all_stds)

        if num_unique_stds == 1 and num_dates > 1:
            is_fixed_map[flight_no] = 1
        else:
            is_fixed_map[flight_no] = 0

    print(f"  [v] Tính toán {len(is_fixed_map)} chuyến bay")
    print(f"      - Fixed flights: {sum(is_fixed_map.values())}")
    print(f"      - Dynamic flights: {len(is_fixed_map) - sum(is_fixed_map.values())}")

    return is_fixed_map

def update_csv_with_tail_numbers_and_is_fixed(cache_data, is_fixed_map):
    print("\n[*] BƯỚC 4: Cập nhật CSV với Tail Numbers và Is_Fixed...")

    if not os.path.exists(CSV_FILE):
        print(f"  [X] Không tìm thấy file: {CSV_FILE}")
        return

    df = pd.read_csv(CSV_FILE)
    print(f"  [+] Tải {len(df)} dòng từ CSV")

    tail_matched = 0
    is_fixed_filled = 0

    for idx, row in df.iterrows():
        flight_no = str(row['Flight_No']).strip()
        scheduled_time = str(row['Scheduled_Time']).strip()
        crawl_date = str(row['Crawl_Date']).strip()

        # ===== Cập nhật Tail_Number =====
        if flight_no in cache_data and (
                pd.isna(row['Tail_Number']) or str(row['Tail_Number']).strip() in ['', 'nan', 'NaN']):
            schedule = cache_data[flight_no].get('schedule', {})

            try:
                dt_obj = datetime.strptime(crawl_date, "%Y-%m-%d")
                fr24_date = f"{dt_obj.day:02d} {ENG_MONTHS[dt_obj.month]} {dt_obj.year}"

                if fr24_date in schedule:
                    for flight in schedule[fr24_date]:
                        if flight.get('std', '').strip() == scheduled_time:
                            tail = flight.get('tail_number', '').strip()
                            if tail and tail not in ['', '—', 'N/A', 'nan']:
                                df.at[idx, 'Tail_Number'] = tail
                                tail_matched += 1
                            break
            except:
                pass

        # ===== Cập nhật Is_Fixed_Flight =====
        if flight_no in is_fixed_map:
            is_fixed_val = is_fixed_map[flight_no]
            if pd.isna(row['Is_Fixed_Flight']) or str(row['Is_Fixed_Flight']).strip() in ['', 'nan', 'NaN']:
                df.at[idx, 'Is_Fixed_Flight'] = is_fixed_val
                is_fixed_filled += 1

    df.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
    print(f"  [v] Cập nhật thành công:")
    print(f"      - Tail numbers được điền: {tail_matched}")
    print(f"      - Is_Fixed_Flight được điền: {is_fixed_filled}")

def save_is_fixed_to_cache(cache_data, is_fixed_map):
    print("\n[*] BƯỚC 5: Lưu is_fixed vào cache JSON...")

    for flight_no, is_fixed_val in is_fixed_map.items():
        if flight_no in cache_data:
            cache_data[flight_no]['is_fixed'] = is_fixed_val

    save_cache(cache_data)
    print(f"  [v] Lưu is_fixed cho {len(is_fixed_map)} chuyến bay vào {CACHE_FILE}")

def main():
    """Chạy toàn bộ quy trình"""
    print("=" * 70)
    print(f"        DAD AIRCRAFT CRAWLING & PROCESSING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    cache_data = create_fixed_flights_cache_from_csv()

    cache_data = crawl_tail_numbers_from_flight_info(cache_data)
    print("  [i] Bỏ qua bước crawl tail numbers")

    create_aircraft_csv(cache_data)
    is_fixed_map = calculate_is_fixed_for_flights(cache_data)
    update_csv_with_tail_numbers_and_is_fixed(cache_data, is_fixed_map)
    save_is_fixed_to_cache(cache_data, is_fixed_map)

    print("\n" + "=" * 70)
    print("  [v] HOÀN TẤT TẤT CẢ CÁC BƯỚC")
    print("=" * 70)


if __name__ == "__main__":
    main()