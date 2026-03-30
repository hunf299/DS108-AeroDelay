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

# ================= CẤU HÌNH BIẾN MÔI TRƯỜNG =================
VN_IATAS = ['HAN', 'DAD', 'CXR', 'PQC', 'VCA', 'VDO', 'HPH', 'VII', 'THD', 'VDH', 'HUI', 'VCL', 'UIH', 'TBB', 'PXU',
            'BMV', 'DLI', 'VKG', 'CAH', 'VCS', 'DIN']
START_DATE = "2026-01-12"
END_DATE = "2026-01-31"

DEST_IATA = "SGN"


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
    print(f"[+] Khởi động trình duyệt Edge cào Arrivals cho {DEST_IATA}...")
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
        url = f"https://www.flightradar24.com/airport/{DEST_IATA.lower()}/history?type=landings&date={target_date}"
        driver.get(url)
        time.sleep(3)

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
                        "Tail_Number": tail_number,
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
                        "Terminal", "Arrival_Runway", "Status", "Tail_Number", "Aircraft_Type", "Category"]
                df = df[cols]
                s_day = format_date_short(START_DATE)
                e_day = format_date_short(END_DATE)
                df.to_csv(f"{DEST_IATA.lower()}_arrivals_history_{s_day}_{e_day}.csv", index=False,
                          encoding='utf-8-sig')

        except Exception as e:
            print(f"[!] Lỗi khi xử lý ngày {target_date}: {type(e).__name__}")
            continue

    driver.quit()
    print(f"\n[v] HOÀN TẤT TOÀN BỘ QUÁ TRÌNH CÀO ARRIVALS! TỔNG SỐ CHUYẾN ĐẾN: {len(all_flights_data)}")


if __name__ == "__main__":
    crawl_arrivals_history_fast()
