import pandas as pd
import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ================= CẤU HÌNH =================
DEST_IATA = "DAD"
ORIGINAL_CSV = "Data crawl crawl/Arrival/{ORIGIN_IATA.lower()}_flights_arrival_bronze_layer.csv"
AIRCRAFT_CSV_FILE = f"{DEST_IATA.lower()}_aircraft.csv"

# Mapping tháng (giữ nguyên của bạn)
INV_ENG_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                  "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def parse_fr24_date(date_str):
    try:
        parts = date_str.split()
        if len(parts) >= 3:
            return datetime(int(parts[2]), INV_ENG_MONTHS[parts[1]], int(parts[0]))
    except:
        pass
    return None


def wait_for_manual_login(driver):
    print("\n[!!!] CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print("[v] Đã nhận diện tài khoản Business!")
                break
            time.sleep(3)
        except:
            time.sleep(3)


def load_flights_until_target_date(driver, target_date="2025-12-01"):
    print(f"    [>] Đang tải dữ liệu đến ngày {target_date}...")
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
            time.sleep(3)
        except:
            break


# ================= BIẾN TẠM ĐỂ GHÉP DỮ LIỆU =================
# Dictionary này sẽ lưu { 'Flight_No': 'Tail_Number' } trong phiên chạy hiện tại
flight_to_tail_map = {}


def crawl_and_update_aircraft_csv():
    """BƯỚC 1: Thu thập dữ liệu và điền vào flight_to_tail_map"""
    global flight_to_tail_map
    print(f"\n[*] BƯỚC 1: Thu thập Tail Number & Aircraft Type từ Web...")

    df_main = pd.read_csv(ORIGINAL_CSV)
    # Tìm các Flight_No đang bị thiếu Tail_Number
    flights_to_crawl = df_main[df_main['Tail_Number'].isna() | (df_main['Tail_Number'] == '')]['Flight_No'].unique()

    if len(flights_to_crawl) == 0:
        print("  [v] Không có dữ roi trống. Bỏ qua crawl.")
        return

    aircraft_results = []
    options = EdgeOptions()
    driver = webdriver.Edge(options=options)
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    for flight_no in flights_to_crawl:
        search_code = flight_no.replace("BL", "VN") if flight_no.startswith("BL") else flight_no
        driver.get(f"https://www.flightradar24.com/data/flights/{search_code.replace(' ', '').lower()}")
        time.sleep(2)
        load_flights_until_target_date(driver)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('tr', class_='data-row')

        if rows:
            # Lấy dòng mới nhất có dữ liệu aircraft
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 5:
                    ac_text = cols[5].text.strip()
                    if '(' in ac_text:
                        a_type = ac_text.split('(')[0].strip()
                        tail = ac_text.split('(')[1].split(')')[0].strip()

                        # Lưu vào map để tí nữa vá vào file gốc
                        flight_to_tail_map[flight_no] = tail
                        # Lưu vào list để cập nhật file aircraft.csv
                        aircraft_results.append({'Tail_Number': tail, 'Aircraft_Type': a_type})
                        break  # Tìm thấy cái gần nhất rồi thì qua Flight_No khác

    driver.quit()

    # Cập nhật file aircraft.csv (danh mục tra cứu loại tàu bay)
    if aircraft_results:
        new_aircraft_df = pd.DataFrame(aircraft_results).drop_duplicates(subset=['Tail_Number'])
        if os.path.exists(AIRCRAFT_CSV_FILE):
            old_df = pd.read_csv(AIRCRAFT_CSV_FILE)
            new_aircraft_df = pd.concat([old_df, new_aircraft_df]).drop_duplicates(subset=['Tail_Number'])
        new_aircraft_df.to_csv(AIRCRAFT_CSV_FILE, index=False, encoding='utf-8-sig')


def patch_original_csv():
    """BƯỚC 2: Vá lỗi dựa trên Flight_No -> Tail_Number -> Aircraft_Type"""
    print(f"\n[*] BƯỚC 2: Vá lỗi dữ liệu vào file gốc...")

    if not os.path.exists(ORIGINAL_CSV): return
    df_main = pd.read_csv(ORIGINAL_CSV)

    # 1. Điền Tail_Number dựa vào Flight_No (từ map vừa crawl)
    if flight_to_tail_map:
        df_main['Tail_Number'] = df_main['Tail_Number'].fillna(df_main['Flight_No'].map(flight_to_tail_map))

    # 2. Điền Aircraft_Type dựa vào Tail_Number (từ file aircraft.csv)
    if os.path.exists(AIRCRAFT_CSV_FILE):
        df_ac = pd.read_csv(AIRCRAFT_CSV_FILE)
        ac_mapping = df_ac.set_index('Tail_Number')['Aircraft_Type'].to_dict()
        df_main['Aircraft_Type'] = df_main['Aircraft_Type'].fillna(df_main['Tail_Number'].map(ac_mapping))

    # Ghi đè lại file gốc
    df_main.to_csv(ORIGINAL_CSV, index=False, encoding='utf-8-sig')
    print(f"[v] HOÀN TẤT! Đã cập nhật Tail Number và Aircraft Type cho {len(flight_to_tail_map)} số hiệu chuyến bay.")


if __name__ == "__main__":
    crawl_and_update_aircraft_csv()
    patch_original_csv()