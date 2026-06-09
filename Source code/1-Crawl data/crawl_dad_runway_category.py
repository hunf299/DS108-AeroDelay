from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os
import undetected_chromedriver as uc
import time
import re

PROJECT_ROOT = Path.cwd().parent.parent.resolve()

ROUTE = os.environ.get("ROUTE", "departure")

BRONZE = PROJECT_ROOT / "Data" / "Bronze_layer"
if ROUTE == "departure":
    CSV_FILE = BRONZE / "Departure" / "dad_flights_departure_bronze_layer.csv"
else:
    CSV_FILE = BRONZE / "Arrival" / "dad_flights_arrival_bronze_layer.csv"
TARGET_PATCH_DATES = []


def start_undetected_browser():
    print("[+] Đang khởi tạo Undetected Chromedriver (Vượt Cloudflare)...")

    options = uc.ChromeOptions()
    options.add_argument("--disable-notifications")

    # 1. Thêm các cờ chống sập
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    # Thêm user-agent chuẩn của người thật
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Khởi tạo trình duyệt
    driver = uc.Chrome(options=options)
    driver.maximize_window()

    return driver


def is_empty_val(val):
    v_str = str(val).strip().lower()
    return pd.isna(val) or v_str in ['', 'n/a', '—', 'unknown', 'nan', 'none']


def wait_for_manual_login(driver):
    print("\n[!!!] CHỜ ĐĂNG NHẬP TÀI KHOẢN BUSINESS [!!!]")
    while True:
        try:
            auth_btn = driver.find_element(By.ID, "auth-button")
            if "business" in auth_btn.text.lower():
                print("\n[v] Đã nhận diện tài khoản Business!\n")
                break
            time.sleep(1)
        except:
            time.sleep(1)


def patch_missing_runways():
    print(f"[*] Đang đọc file dữ liệu: {CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print("[X] Lỗi: Không tìm thấy file CSV!")
        return

    df = pd.read_csv(CSV_FILE)

    # ĐỘNG HOÁ TÊN CỘT DỰA VÀO ENV
    runway_col = f"{ROUTE.capitalize()}_Runway"

    if runway_col not in df.columns:
        df[runway_col] = pd.NA
    if "Category" not in df.columns:
        df["Category"] = pd.NA

    # Tìm các ngày bị khuyết Runway
    missing_mask = df[runway_col].apply(is_empty_val)
    if TARGET_PATCH_DATES:
        dates_to_patch = TARGET_PATCH_DATES
    else:
        dates_to_patch = df[missing_mask]['Crawl_Date'].dropna().unique()

    if len(dates_to_patch) == 0:
        print("\n[v] Tuyệt vời! Không có chuyến bay nào bị thiếu Runway. Hoàn tất!")
        return

    print(f"[!] Phát hiện {missing_mask.sum()} chuyến bay bị thiếu Runway phân bố trong {len(dates_to_patch)} ngày.")

    driver = start_undetected_browser()
    driver.get("https://www.flightradar24.com")
    wait_for_manual_login(driver)

    patched_count = 0

    for target_date in sorted(dates_to_patch):
        print(f"\n{'=' * 50}")
        print(f"========== ĐANG XỬ LÝ NGÀY: {target_date} ==========")
        print(f"{'=' * 50}")

        missing_in_date = df[(df['Crawl_Date'] == target_date) & missing_mask]
        print(f"  > Ngày này có {len(missing_in_date)} chuyến cần vá Runway.")
        if missing_in_date.empty: continue

        print(f"\n[!!!] HÀNH ĐỘNG CẦN THIẾT [!!!]")
        print(f"Vui lòng chọn ngày '{target_date}' trên Calendar. Tool đang lắng nghe...")

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
                    time.sleep(1)
                    break
            except Exception:
                pass
            time.sleep(1)

        flights = driver.find_elements(By.CSS_SELECTOR, 'li[data-testid="airport-history__result-item"]')
        total_flights = len(flights)

        for i in range(total_flights):
            still_missing = df[(df['Crawl_Date'] == target_date) &
                               (df[runway_col].apply(is_empty_val) | df['Category'].apply(is_empty_val))]
            if still_missing.empty:
                print("  [v] Đã vá xong toàn bộ Runway bị khuyết cho ngày này!")
                break

            try:
                current_flights = driver.find_elements(By.CSS_SELECTOR,
                                                       'li[data-testid="airport-history__result-item"]')
                if i >= len(current_flights): break
                flight = current_flights[i]

                html_outer = flight.get_attribute("outerHTML")
                soup_outer = BeautifulSoup(html_outer, 'html.parser')

                def get_text_safe(soup_obj, test_id):
                    el = soup_obj.find(attrs={"data-testid": test_id})
                    return el.text.strip() if el else ""

                flight_no_web = get_text_safe(soup_outer, "airport-history__result-item__flight-number")
                iata_code = get_text_safe(soup_outer, "airport-history__result-item__airport-iata")

                if not flight_no_web: continue

                match = still_missing[(still_missing['Flight_No'].astype(str).str.strip() == flight_no_web)]
                if iata_code:
                    match = match[match['IATA'].astype(str).str.strip() == iata_code]

                if match.empty: continue

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", flight)
                time.sleep(0.3)
                scraped_runway = ""
                scraped_category = ""

                runway_span = soup_outer.find(attrs={"data-testid": "airport-history__result-item__airport-runway"})
                if runway_span:
                    scraped_runway = runway_span.get_text(separator="", strip=True)

                if is_empty_val(scraped_runway) or is_empty_val(scraped_category):
                    clickable_div = flight.find_element(By.CSS_SELECTOR,
                                                        "div[data-testid='airport-history__result-item__data']")
                    for attempt in range(3):
                        details_check = flight.find_elements(By.CSS_SELECTOR,
                                                             "dl[data-testid='airport-history__result-item__details__category']")
                        if not details_check or not details_check[0].is_displayed():
                            driver.execute_script("arguments[0].click();", clickable_div)
                        try:
                            WebDriverWait(flight, 4).until(EC.visibility_of_element_located(
                                (By.CSS_SELECTOR, "dl[data-testid='airport-history__result-item__details__category']")))
                            time.sleep(1.0)
                        except:
                            pass
                        soup_inner = BeautifulSoup(flight.get_attribute("outerHTML"), 'html.parser')
                        runway_el = soup_inner.find(
                            attrs={"data-testid": "airport-history__result-item__details__runway"})
                        scraped_runway = runway_el.find('dd').text.strip() if runway_el and runway_el.find('dd') else ""

                        dt_list = soup_inner.find_all("dt", class_="text-xs font-semibold uppercase text-gray-900")
                        scraped_category = ""
                        for dt in dt_list:
                            if "category" in dt.text.lower():
                                dd = dt.find_next_sibling("dd")
                                scraped_category = dd.text.strip() if dd else ""
                                break

                        # Cập nhật vào DataFrame
                    for idx, row in match.iterrows():
                        if not is_empty_val(scraped_runway):
                            df.at[idx, runway_col] = scraped_runway
                        if not is_empty_val(scraped_category):
                            df.at[idx, 'Category'] = scraped_category

                        if not is_empty_val(scraped_runway) or not is_empty_val(scraped_category):
                            patched_count += 1
                            print(
                                f"    [+] VÁ THÀNH CÔNG ({flight_no_web}): Runway -> {scraped_runway}, Cat -> {scraped_category}")
                        break

            except Exception as e:
                continue

        df.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')

    driver.quit()
    print(f"\n[v] HOÀN TẤT VÁ LỖI RUNWAY. TỔNG CỘNG ĐÃ VÁ: {patched_count} CHUYẾN!")


if __name__ == "__main__":
    patch_missing_runways()