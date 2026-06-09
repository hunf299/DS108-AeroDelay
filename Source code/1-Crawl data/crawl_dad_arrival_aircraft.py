import pandas as pd
import time
import os
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from pathlib import Path

# ================= CẤU HÌNH TÊN CỘT TRONG CSV =================
COL_FLIGHT_NO = 'Flight_No'
COL_TAIL_NUMBER = 'Actual_Tail'
COL_AIRCRAFT_TYPE = 'Aircraft_Type'
COL_ARR_DATE = 'Arrival_Date'  # Yêu cầu định dạng YYYY-MM-DD
COL_ARR_TIME = 'Arrival_Time'  # Yêu cầu định dạng HH:MM

# ================= CẤU HÌNH ĐƯỜNG DẪN =================
current_dir = Path.cwd().parent.parent.resolve()
DEST_IATA = "DAD"
ORIGINAL_CSV = current_dir / "Data" / "Bronze_layer" / "Arrival" / "{DEST_IATA.lower()}_flights_arrival_bronze_layer.csv"
AIRCRAFT_CSV_FILE = f"{DEST_IATA.lower()}_arrival_aircraft.csv"

# ================= BIẾN TOÀN CỤC =================
INV_ENG_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                  "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}

crawled_data_map = {}
# Dictionary lưu thời gian bay trung bình: { 'Flight_No': avg_mins }
flight_avg_time_map = {}


# ================= CÁC HÀM TIỆN ÍCH =================
def parse_fr24_date(date_str):
    """Chuyển đổi chuỗi ngày trên FR24 thành datetime object"""
    try:
        parts = date_str.split()
        if len(parts) >= 3:
            return datetime(int(parts[2]), INV_ENG_MONTHS[parts[1]], int(parts[0]))
    except:
        pass
    return None


def get_average_flight_time_mins(rows):
    """Tính trung bình thời gian bay từ các dòng hiển thị HTML (giả sử cột số 6)"""
    total_mins = 0
    count = 0
    for row in rows:
        cols = row.find_all('td')
        if len(cols) > 6:
            fl_time_text = cols[6].text.strip()
            if ':' in fl_time_text:
                try:
                    h, m = fl_time_text.split(':')
                    total_mins += int(h) * 60 + int(m)
                    count += 1
                except:
                    pass
    # Trả về trung bình, mặc định 90 phút nếu không có data
    return total_mins // count if count > 0 else 90


def get_fr24_date(arrival_date_str, arrival_time_str, avg_flight_mins):
    """Trừ thời gian bay trung bình để tìm ra ngày hiển thị trên FR24"""
    try:
        arr_dt = datetime.strptime(f"{arrival_date_str} {arrival_time_str}", "%Y-%m-%d %H:%M")
        expected_dep_dt = arr_dt - timedelta(minutes=avg_flight_mins)
        return expected_dep_dt.strftime("%Y-%m-%d")
    except Exception as e:
        return arrival_date_str


def wait_for_manual_login(driver):
    print("\n[!!!] CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print("[v] Đã nhận diện tài khoản Business!")
                break
            time.sleep(1)
        except:
            time.sleep(1)


def load_flights_until_target_date(driver, target_date):
    """Bấm Load Earlier cho đến khi xuất hiện ngày target_date trên HTML"""
    print(f"    [>] Đang bấm Load Earlier lùi về ngày {target_date}...")
    while True:
        try:
            rows = driver.find_elements(By.CLASS_NAME, "data-row")
            if rows:
                last_date_str = rows[-1].find_element(By.XPATH, ".//td[@data-time-format='DD MMM YYYY']").text.strip()
                last_dt = parse_fr24_date(last_date_str)
                if last_dt and last_dt.strftime("%Y-%m-%d") <= target_date:
                    break
            load_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "btn-load-earlier-flights")))
            driver.execute_script("arguments[0].click();", load_btn)
            time.sleep(1)
        except:
            break


def crawl_and_update_aircraft_csv():
    global crawled_data_map, flight_avg_time_map
    print(f"\n[*] BƯỚC 1: Khởi động trình thu thập Web...")

    if not os.path.exists(ORIGINAL_CSV):
        print(f"[!] Không tìm thấy file {ORIGINAL_CSV}")
        return

    df_main = pd.read_csv(ORIGINAL_CSV)

    # BỔ SUNG KHỞI TẠO CỘT NẾU CHƯA CÓ
    if COL_TAIL_NUMBER not in df_main.columns:
        df_main[COL_TAIL_NUMBER] = pd.NA

    df_missing = df_main[df_main[COL_TAIL_NUMBER].isna() | (df_main[COL_TAIL_NUMBER] == '')]
    flights_to_crawl = df_missing[COL_FLIGHT_NO].dropna().unique()

    if len(flights_to_crawl) == 0:
        print("  [v] Dữ liệu đã đầy đủ. Bỏ qua crawl.")
        return

    aircraft_results = []
    print(f"[+] Khởi động trình duyệt undetected_chrome để thu thập dữ liệu...")

    # Khởi tạo tùy chọn cấu hình của undetected_chromedriver
    options = uc.ChromeOptions()
    options.add_argument("--disable-notifications")

    # 1. Thêm các cờ chống sập
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    driver = uc.Chrome(options=options)
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    for flight_no in flights_to_crawl:
        search_code = flight_no.replace("BL", "VN") if flight_no.startswith("BL") else flight_no
        driver.get(f"https://www.flightradar24.com/data/flights/{search_code.replace(' ', '').lower()}")
        time.sleep(1)

        # 1. Tính toán Average Flight Time
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        initial_rows = soup.find_all('tr', class_='data-row')
        avg_mins = get_average_flight_time_mins(initial_rows)
        flight_avg_time_map[flight_no] = avg_mins

        print(f"\n[*] Đang xử lý: {flight_no} | Bay TB: {avg_mins} phút")

        # 2. Tạo Set các ngày cần tìm trên FR24 cho Flight_No này
        missing_for_this_flight = df_missing[df_missing[COL_FLIGHT_NO] == flight_no]
        target_dates = set()

        for _, row in missing_for_this_flight.iterrows():
            arr_date = str(row[COL_ARR_DATE])
            arr_time = str(row[COL_ARR_TIME])
            fr_date = get_fr24_date(arr_date, arr_time, avg_mins)
            target_dates.add(fr_date)

        if not target_dates:
            continue

        print(f"    [>] Cần tìm các ngày: {sorted(list(target_dates))}")

        # 3. Load Earlier đến ngày cũ nhất
        oldest_target_date = min(target_dates)
        load_flights_until_target_date(driver, oldest_target_date)

        # 4. Quét toàn bộ HTML để nhặt Data
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        all_rows = soup.find_all('tr', class_='data-row')

        for row in all_rows:
            cols = row.find_all('td')
            if len(cols) > 5:
                row_dt = parse_fr24_date(cols[2].text.strip())
                if not row_dt: continue

                row_date_str = row_dt.strftime("%Y-%m-%d")

                # Khớp ngày!
                if row_date_str in target_dates:
                    ac_text = cols[5].text.strip()
                    if '(' in ac_text:
                        a_type = ac_text.split('(')[0].strip()
                        tail = ac_text.split('(')[1].split(')')[0].strip()

                        # Lưu vào Map cho Bước 2
                        crawled_data_map[(flight_no, row_date_str)] = tail

                        # Lưu vào List cho file aircraft.csv
                        aircraft_results.append({'Actual_Tail': tail, 'Aircraft_Type': a_type})

                        # Xóa ngày đã tìm thấy
                        target_dates.remove(row_date_str)
                        print(f"      + Đã tìm thấy {tail} cho ngày {row_date_str}")

                # Tối ưu: Nếu đã tìm đủ các ngày của chuyến này, dừng quét HTML
                if not target_dates:
                    break

        if target_dates:
            print(f"    [!] Không tìm thấy dữ liệu cho các ngày: {target_dates} (Có thể bị hủy hoặc trống trên web)")

    driver.quit()

    # Cập nhật DB máy bay (aircraft.csv)
    if aircraft_results:
        new_aircraft_df = pd.DataFrame(aircraft_results).drop_duplicates(subset=['Actual_Tail'])
        if os.path.exists(AIRCRAFT_CSV_FILE):
            old_df = pd.read_csv(AIRCRAFT_CSV_FILE)
            new_aircraft_df = pd.concat([old_df, new_aircraft_df]).drop_duplicates(subset=['Actual_Tail'])
        new_aircraft_df.to_csv(AIRCRAFT_CSV_FILE, index=False, encoding='utf-8-sig')

def patch_original_csv():
    print(f"\n[*] BƯỚC 2: Vá dữ liệu vào file CSV gốc...")
    if not os.path.exists(ORIGINAL_CSV): return

    df_main = pd.read_csv(ORIGINAL_CSV)

    # BỔ SUNG KHỞI TẠO CỘT
    if COL_TAIL_NUMBER not in df_main.columns:
        df_main[COL_TAIL_NUMBER] = pd.NA
    if COL_AIRCRAFT_TYPE not in df_main.columns:
        df_main[COL_AIRCRAFT_TYPE] = pd.NA

    # Hàm trợ giúp: Tính ngày để tra cứu Tail_Number
    def get_crawled_tail(row):
        f_no = row[COL_FLIGHT_NO]
        # Nếu chưa crawl được thời gian TB (do không thiếu, hoặc web lỗi), mặc định 90 phút
        avg_mins = flight_avg_time_map.get(f_no, 90)

        fr24_date = get_fr24_date(str(row[COL_ARR_DATE]), str(row[COL_ARR_TIME]), avg_mins)
        key = (f_no, fr24_date)

        return crawled_data_map.get(key, row[COL_TAIL_NUMBER])

    # 1. Điền Tail_Number
    if crawled_data_map:
        df_main[COL_TAIL_NUMBER] = df_main.apply(
            lambda row: get_crawled_tail(row) if pd.isna(row[COL_TAIL_NUMBER]) or str(
                row[COL_TAIL_NUMBER]).strip() == '' else row[COL_TAIL_NUMBER],
            axis=1
        )

    # 2. Điền Aircraft_Type dựa vào Tail_Number
    if os.path.exists(AIRCRAFT_CSV_FILE):
        df_ac = pd.read_csv(AIRCRAFT_CSV_FILE)
        ac_mapping = df_ac.set_index('Actual_Tail')['Aircraft_Type'].to_dict()
        df_main[COL_AIRCRAFT_TYPE] = df_main[COL_AIRCRAFT_TYPE].fillna(df_main[COL_TAIL_NUMBER].map(ac_mapping))

    df_main.to_csv(ORIGINAL_CSV, index=False, encoding='utf-8-sig')
    print(f"[v] HOÀN TẤT! Đã vá {len(crawled_data_map)} dữ liệu hợp lệ.")


if __name__ == "__main__":
    crawl_and_update_aircraft_csv()
    patch_original_csv()