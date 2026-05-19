from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
import os
import undetected_chromedriver as uc
import time
import re

# ================= CẤU HÌNH ================="
CSV_FILE = r"Z:\PycharmProjects\DS108-AeroDelay\Data crawl\Silver_layer\Departure\dad_flights_departure_silver_layer.csv"

# Nếu bạn muốn chỉ vá 1 vài ngày cụ thể, điền vào đây (VD: ["2026-03-15"]).
# Để trống [] tool sẽ tự quét toàn bộ CSV.
TARGET_PATCH_DATES = ["2026-02-08", "2026-03-07"]


def start_undetected_browser():
    print("[+] Đang khởi tạo Undetected Chromedriver (Vượt Cloudflare)...")

    options = uc.ChromeOptions()
    # Thêm user-agent chuẩn của người thật
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Khởi tạo trình duyệt
    # Lưu ý: Không dùng chế độ ẩn danh (incognito) hay headless vì dễ bị Cloudflare nghi ngờ
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
            time.sleep(3)
        except:
            time.sleep(3)


def patch_missing_runways():
    print(f"[*] Đang đọc file dữ liệu: {CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print("[X] Lỗi: Không tìm thấy file CSV!")
        return

    df = pd.read_csv(CSV_FILE)

    # Tìm các ngày bị khuyết Runway
    missing_mask = df['Departure_Runway'].apply(is_empty_val)
    if TARGET_PATCH_DATES:
        dates_to_patch = TARGET_PATCH_DATES
    else:
        dates_to_patch = df[missing_mask]['Crawl_Date'].dropna().unique()

    if len(dates_to_patch) == 0:
        print("\n[v] Tuyệt vời! Không có chuyến bay nào bị thiếu Runway. Hoàn tất!")
        return

    print(f"[!] Phát hiện {missing_mask.sum()} chuyến bay bị thiếu Runway phân bố trong {len(dates_to_patch)} ngày.")

    # Khởi động Trình duyệt
    driver = start_undetected_browser()
    driver.maximize_window()

    # Chỉ load trang chủ lịch sử 1 lần
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

        # --- BẪY THỜI GIAN: CHỜ NGƯỜI DÙNG CHỌN NGÀY ---
        print(f"\n[!!!] HÀNH ĐỘNG CẦN THIẾT [!!!]")
        print(f"Vui lòng quay sang trình duyệt và chọn ngày '{target_date}' trên Calendar.")
        print("Tool đang tự động lắng nghe thẻ <h3> để nhận diện...")

        # Parse target_date ra format của FR24 để so sánh (VD: "May 5")
        # Parse target_date ra format của FR24 để so sánh
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        month_str = target_dt.strftime("%b")  # Jan, Feb, Mar...
        month_full = target_dt.strftime("%B")  # January, February...
        day_str = str(target_dt.day)

        # Tạo mẫu Regex để bắt CHÍNH XÁC ngày (\b đảm bảo không bị dính chữ số đằng sau)
        # VD: \bMay 2\b sẽ không bao giờ khớp với "May 24" hay "May 25"
        pattern_short = rf"\b{month_str} {day_str}\b"
        pattern_full = rf"\b{month_full} {day_str}\b"

        while True:
            try:
                # Đọc thẻ h3
                h3_element = driver.find_element(By.CSS_SELECTOR, "h3.inline-flex.items-center.text-sm")
                h3_text = h3_element.text.strip()

                # So khớp chính xác bằng Regex thay vì toán tử 'in'
                if re.search(pattern_short, h3_text) or re.search(pattern_full, h3_text):
                    print(f"\n  [v] Đã nhận diện đúng ngày: '{h3_text}'")
                    print("  [>] Chờ 3s cho dữ liệu bảng ổn định...")
                    time.sleep(3)  # Chờ bảng load xong sau khi đổi ngày
                    break
            except Exception:
                pass
            time.sleep(2)

        # --- BẮT ĐẦU QUÉT BẢNG ---
        flights = driver.find_elements(By.CSS_SELECTOR, 'li[data-testid="airport-history__result-item"]')
        total_flights = len(flights)

        for i in range(total_flights):
            # Check xem đã vá xong hết chưa
            still_missing = df[(df['Crawl_Date'] == target_date) & (df['Departure_Runway'].apply(is_empty_val))]
            if still_missing.empty:
                print("  [v] Đã vá xong toàn bộ Runway bị khuyết cho ngày này!")
                break

            try:
                current_flights = driver.find_elements(By.CSS_SELECTOR,
                                                       'li[data-testid="airport-history__result-item"]')
                if i >= len(current_flights): break
                flight = current_flights[i]

                # Bóc tách bề mặt (Outer HTML)
                html_outer = flight.get_attribute("outerHTML")
                soup_outer = BeautifulSoup(html_outer, 'html.parser')

                def get_text_safe(soup_obj, test_id):
                    el = soup_obj.find(attrs={"data-testid": test_id})
                    return el.text.strip() if el else ""

                # LẤY FLIGHT_NO VÀ IATA TỪ BÊN NGOÀI
                flight_no_web = get_text_safe(soup_outer, "airport-history__result-item__flight-number")
                iata_code = get_text_safe(soup_outer, "airport-history__result-item__airport-iata")

                # Bỏ qua nếu trên web không hiển thị Flight No (không có cơ sở để match)
                if not flight_no_web:
                    continue

                # ================= SO KHỚP BẰNG FLIGHT_NO VÀ IATA =================
                # Sử dụng .astype(str).str.strip() để tránh lỗi khoảng trắng ẩn trong pandas
                match = still_missing[(still_missing['Flight_No'].astype(str).str.strip() == flight_no_web)]
                if iata_code:
                    match = match[match['IATA'].astype(str).str.strip() == iata_code]

                if match.empty:
                    continue

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", flight)
                time.sleep(0.3)

                departure_runway = ""

                # ================= CƠ CHẾ FAST PATH (LẤY TỪ THẺ SPAN NGOÀI) =================
                runway_span = soup_outer.find(attrs={"data-testid": "airport-history__result-item__airport-runway"})
                if runway_span:
                    # Lấy text và dọn dẹp các ký tự thừa
                    departure_runway = runway_span.get_text(separator="", strip=True)

                # ================= CƠ CHẾ SLOW PATH (BUNG BẢNG RETRY 3 LẦN) =================
                if is_empty_val(departure_runway):
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
                        departure_runway = runway_el.find('dd').text.strip() if runway_el and runway_el.find(
                            'dd') else ""

                        if not is_empty_val(departure_runway):
                            break
                        else:
                            if attempt < 2:
                                driver.execute_script("arguments[0].click();", clickable_div)
                                time.sleep(1.0)

                # ================= CẬP NHẬT VÀO CSV =================
                for idx, row in match.iterrows():
                    if not is_empty_val(departure_runway):
                        df.at[idx, 'Departure_Runway'] = departure_runway
                        patched_count += 1
                        print(f"    [+] VÁ THÀNH CÔNG ({flight_no_web}): Runway -> {departure_runway}")
                    else:
                        print(f"    [-] Bó tay ({flight_no_web}): Web không hiển thị Runway.")
                    break  # Chỉ cập nhật dòng đầu tiên tìm thấy

            except Exception as e:
                print(f"  [!] Lỗi dòng {i + 1}: {type(e).__name__}")
                continue

        df.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
        print(f"  [v] Đã lưu cập nhật CSV cho ngày {target_date}")

    driver.quit()
    print(f"\n[v] HOÀN TẤT VÁ LỖI RUNWAY. TỔNG CỘNG ĐÃ VÁ: {patched_count} CHUYẾN!")


if __name__ == "__main__":
    patch_missing_runways()