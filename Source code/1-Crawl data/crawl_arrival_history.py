import os
from pathlib import Path
from selenium import webdriver
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

# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
VN_IATAS = ['DAD', 'SGN', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']
START_DATE = "2026-01-17"
END_DATE = "2026-01-17"

DEST_IATA = os.environ.get("ORIGIN_DATA", "DAD")

PROJECT_ROOT = Path.cwd().parent.parent.resolve()

BRONZE = PROJECT_ROOT / "Data" / "Bronze_layer"
ARRIVAL_DIR = BRONZE / "Arrival" / f"{DEST_IATA.lower()}_flights_arrival_bronze_layer.csv"


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


# ================= KỊCH BẢN CHÍNH ================
def crawl_arrivals_history_fast():
    print(f"[+] Khởi động trình duyệt undetected_chrome cào Flightradar24...")

    # Khởi tạo Options của undetected_chromedriver
    options = uc.ChromeOptions()
    options.add_argument("--disable-notifications")

    # 1. Thêm các cờ chống sập
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    driver = uc.Chrome(options=options)
    driver.maximize_window()
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    # == BỔ SUNG: Mở trang lịch sử sân bay 1 lần duy nhất ở Tab chính ==
    base_url = f"https://www.flightradar24.com/airport/{DEST_IATA.lower()}/arrivals"
    driver.get(base_url)
    time.sleep(3)

    date_list = pd.date_range(start=START_DATE, end=END_DATE).strftime('%Y-%m-%d').tolist()
    all_flights_data = []

    for target_date in date_list:
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

                    category, airline, flight_no, arrival_runway, tail_number, aircraft_type, flight_time, ui_terminal = "", "", "", "", "", "", "", ""

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
                        flight_time = ""
                        ui_terminal = ""
                        dt_tags = soup_inner.find_all('dt')
                        for dt in dt_tags:
                            dt_text = dt.text.strip().lower()
                            if "terminal" in dt_text:
                                dd_tag = dt.find_next_sibling('dd')
                                if dd_tag: ui_terminal = dd_tag.text.strip()
                            elif "flight time" in dt_text:
                                dd_tag = dt.find_next_sibling('dd')
                                if dd_tag: flight_time = dd_tag.text.strip()

                        if category == "unknown" or is_empty_val(aircraft_type) or is_empty_val(flight_time):
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
                        "Flight_Time": flight_time,
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
                    all_flights_data.append(record)

                    print(
                        f"  [{i + 1}/{total_flights}] {flight_no} | Nguồn: {iata_code} | ATA: {actual_time} | F-Time: {flight_time} | Term: {terminal_val} | AC: {aircraft_type} | TN: {tail_number} | Category: {category}")

                except Exception as e:
                    print(f"  [!] Lỗi bóc tách dòng {i + 1}: {type(e).__name__} - {str(e).splitlines()[0]}")
                    continue

            # Lưu dự phòng sau mỗi ngày
            if all_flights_data:
                df = pd.DataFrame(all_flights_data)
                cols = ["Crawl_Date", "Actual_Time", "Flight_Time", "Origin", "IATA", "Airline", "Flight_No",
                        "Terminal", "Arrival_Runway", "Status", "Actual_Tail", "Aircraft_Type", "Category"]
                df = df[cols]
                s_day = format_date_short(START_DATE)
                e_day = format_date_short(END_DATE)
                df.to_csv(ARRIVAL_DIR, index=False,
                          encoding='utf-8-sig')

        except Exception as e:
            print(f"[!] Lỗi khi xử lý ngày {target_date}: {type(e).__name__}")
            continue

    driver.quit()
    print(f"\n[v] HOÀN TẤT TOÀN BỘ QUÁ TRÌNH CÀO ARRIVALS! TỔNG SỐ CHUYẾN ĐẾN: {len(all_flights_data)}")


if __name__ == "__main__":
    crawl_arrivals_history_fast()