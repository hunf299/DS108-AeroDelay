# EDA Weather Overhaul Change Log

## Van de tu review va cach da sua

| Van de review | Da kiem tra | Da sua o file nao | Ket qua |
|---|---|---|---|
| EDA giong khi tuong thuy van, chua noi anh huong van hanh bay | Doi cach doc sang visibility threshold, crosswind knot, runway wet, case xau theo san bay | `Source code/weather_preprocessing.py`, `Source code/eda_weather_plan_notebook.ipynb`, `10_aviation_weather_operational_review.md` | Them `Aviation_Operational_Risk_Score` va dien giai theo approach visibility, runway wet, runway selection, pilot workload |
| Chua phan tich huong gio | Tinh wind sector theo 8 huong va theo airport/month | `weather_preprocessing.py`, notebook, `06_wind_direction_sector_by_airport*.csv` | HAN noi bat voi SE 36.78% va NE 27.45%; DAD chu dao NE/E/N; SGN chu dao SE |
| Gió trong hàng không nên dùng knot, không chỉ km/h | Quy doi km/h sang knot | `weather_preprocessing.py`, notebook | Them `Wind_Kt`, `Crosswind_Kt`, `Headwind_Kt`, `Wind_Gust_Estimate_Kt`, `Crosswind_Max_3H_Kt` |
| Crosswind 10 kt can duoc nhac den | Tinh xwind >=10/15/20 kt theo gio va flight exposure | `weather_preprocessing.py`, notebook, `06_crosswind_operational_threshold_summary.csv` | HAN co 71 gio >=10 kt, DAD 12, SGN 1; khong co >=15 kt |
| Qua tap trung DAD | Tinh worst cases rieng cho DAD/HAN/SGN | notebook, `06_worst_operational_weather_cases_by_airport.csv`, `10_aviation_weather_operational_review.md` | SGN co case xau low visibility + heavy rain + wet runway; HAN co rain/wet runway; DAD severe visibility hiem |
| HAN thang 1-3 co mua dac biet | Tinh monthly precip/rain/wet runway cho tung airport | notebook, `06_monthly_precip_operational_profile.csv`, `06_han_precip_jan_mar_operational_note.csv` | HAN Jan: 117 rain hours; Feb: 151 rain hours; Mar: 46 rain hours. Thang 3 on hon Jan-Feb |
| Visibility correlation voi risk bi am, trong khi tam nhin quan trong | So sanh raw visibility voi deficit/threshold features | `weather_preprocessing.py`, notebook, `06_visibility_correlation_direction_check.csv` | Raw visibility corr = -0.431 la dung vi visibility cang cao cang tot; `Visibility_Severity_Score` va deficit co corr duong |
| Nhan xet humidity-visibility bi lech sang delay risk | Tinh correlation all vs non-capped theo airport va sua dung pham vi bieu do | `Source code/eda_weather_plan_notebook.ipynb`, `03_visibility_humidity_capped_sensitivity.csv`, `10_aviation_weather_operational_review.md` | Sua ket luan: day la phan humidity vs visibility; capped la mot ly do lon, nhung non-capped corr van yeu; humidity khong du lam proxy truc tiep cho fog/visibility |
| Low visibility DAD bi mat trong output moi | Kiem tra Bronze/Silver/Silver_layer_2 va audit cleaning | `Source code/weather_preprocessing.py`, `Data crawl/Silver_layer_2/Audit/audit_weather_cleaning_actions.csv` | Phat hien IQR clipping da day low visibility DAD len 14,780 m; da tat IQR clip cho `visibility`, `precipitation`, `wind_speed` |
| Notebook EDA weather chua duoc cap nhat | Sua notebook truc tiep va clear output cu | `Source code/eda_weather_plan_notebook.ipynb` | Notebook uu tien `Silver_layer_2`, them section 6.2, compile khong loi syntax |

## File da thay doi

- `Source code/weather_preprocessing.py`: them aviation features, wind sector, visibility deficit, operational score.
- `Source code/weather_preprocessing.py`: sua cleaning de khong IQR-clip event variables `visibility`, `precipitation`, `wind_speed`.
- `Source code/eda_weather_plan_notebook.ipynb`: them aviation-oriented overview, uu tien schema moi, them section 6.2, them output CSV moi.
- `weather_preprocessing.md`: them ghi chu aviation EDA update.
- `Data crawl/Silver_layer/Audit/eda_weather_reports/10_aviation_weather_operational_review.md`: viet lai report insight theo huong hang khong.
- `Data crawl/Silver_layer/Audit/eda_weather_reports/11_eda_weather_overhaul_changes.md`: file tong quan nay.

## File report moi duoc sinh

- `06_wind_direction_sector_by_airport.csv`
- `06_wind_direction_sector_by_airport_month.csv`
- `06_monthly_precip_operational_profile.csv`
- `06_han_precip_jan_mar_operational_note.csv`
- `06_visibility_correlation_direction_check.csv`
- `03_visibility_humidity_capped_sensitivity.csv`
- `06_worst_operational_weather_cases_by_airport.csv`

## Validation da chay

- Chay lai `python "Source code/weather_preprocessing.py" --project-root "."` thanh cong.
- Kiem tra output moi co cac cot `Wind_Sector`, `Crosswind_Kt`, `Visibility_Deficit_5KM_M`, `Visibility_Severity_Score`, `Aviation_Operational_Risk_Score`.
- Kiem tra audit cleaning moi: `IQR_Clipped = 0` cho `visibility`, `precipitation`, `wind_speed`; DAD phuc hoi `134` gio visibility < 10 km.
- Compile tat ca code cells trong `eda_weather_plan_notebook.ipynb`: `syntax_errors = 0`.
- Sinh thanh cong cac CSV report moi trong `eda_weather_reports`.
