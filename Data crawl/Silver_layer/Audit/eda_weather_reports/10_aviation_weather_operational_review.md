# Aviation Weather Operational EDA Review

## Muc tieu

EDA weather duoc chinh lai theo huong van hanh hang khong: visibility, mua, gio, huong gio va runway condition phai duoc dien giai thanh kha nang anh huong takeoff/landing, runway selection, spacing/holding, braking, pilot workload hoac delay propagation. Khong chi doc nhu khi tuong thuy van rieng le.

## Can cu va gioi han

- Gio/crosswind trong phan hang khong dung knot. `1 kt = 1.852 km/h`.
- Visibility duoc doc them theo statute mile: `3 SM ~= 4,828 m`, `1 SM ~= 1,609 m`.
- METAR/flight category chuan can ceiling, RVR, gust va weather code. Dataset hien tai thieu cac truong nay, nen chi dung cum `visibility-only IFR-like`, khong khang dinh IFR/MVFR day du.
- Crosswind tinh theo runway heading mac dinh: SGN 250, HAN 110, DAD 350. Crosswind magnitude khong doi neu runway dao chieu, nhung headwind/tailwind va runway selection thi co doi. Vi vay huong gio phai duoc phan tich rieng.

## Nhung feature da bo sung

- `Wind_Kt`, `Crosswind_Kt`, `Headwind_Kt`.
- `Wind_Sector`, `Wind_Runway_Relative_Angle_Deg`, `Is_Tailwind_Default_Runway_5kt`.
- `Visibility_SM`, `Visibility_Deficit_5KM_M`, `Visibility_Deficit_3SM_M`, `Visibility_Severity_Score`.
- `Is_Crosswind_10kt`, `Is_Crosswind_15kt`, `Is_Crosswind_20kt`.
- `Is_Below_3SM_Visibility`, `Is_Below_1SM_Visibility`.
- `Aviation_Operational_Risk_Score`.
- Cleaning da duoc sua de khong IQR-clip `visibility`, `precipitation`, `wind_speed`. Cac bien event cuc tri nay la tin hieu van hanh, khong phai outlier nen xoa.

## Visibility: khong chi nhin nguong 10 km

| Airport | Hours | Vis < 10 km | Vis < 5 km | Vis < 3 SM | Vis < 1 SM |
|---|---:|---:|---:|---:|---:|
| DAD | 2,208 | 134 (6.07%) | 9 (0.41%) | 8 (0.36%) | 0 |
| HAN | 2,208 | 3 (0.14%) | 0 | 0 | 0 |
| SGN | 2,208 | 19 (0.86%) | 5 (0.23%) | 5 (0.23%) | 0 |

DAD dung la co nhieu gio visibility duoi 10 km nhat, nhung phan lon la giam nhe. Khi chuyen sang nguong hang khong `<3 SM`, chi con 8 gio. Vi vay khong nen noi DAD bi anh huong khai thac nang do tam nhin neu chi dua tren nguong 10 km.

## Visibility tuong quan am voi risk co phai sai?

Khong. Raw `visibility` cang cao thi dieu kien cang tot, nen correlation voi risk co the am. Trong output moi:

- `visibility`: corr voi operational risk = `-0.431`.
- `Visibility_Severity_Score`: `+0.201`.
- `Is_Low_Visibility`: `+0.201`.
- `Visibility_Deficit_5KM_M`: `+0.188`.
- `Visibility_Deficit_3SM_M`: `+0.179`.

Ket luan: tam nhin van quan trong, nhung khong nen doc raw visibility nhu feature cung chieu voi risk. Khi bao cao, dung deficit/threshold flags de dien giai tac dong.

## Humidity va visibility co giai thich duoc suong mu khong?

Phan nay chi noi ve quan he `humidity` voi `visibility`, khong phai quan he voi delay risk. Ket luan hien tai: khong nen ket luan manh. Tuong quan `visibility` voi `humidity` theo san bay rat yeu:

- DAD: `-0.091` tren toan bo data; non-capped subset `-0.129`.
- HAN: `-0.078` tren toan bo data; non-capped subset `-0.059`.
- SGN: `-0.068` tren toan bo data; non-capped subset `+0.096`.

Visibility cap la ly do quan trong: SGN cap `96.0%`, HAN `92.8%`, DAD `62.4%`. Nhung khi bo capped values, quan he van yeu/khong on dinh. Vi vay nhan xet "do am cao lam giam tam nhin" khong duoc dataset nay the hien ro. Khong nen dung humidity lam proxy truc tiep cho fog/low visibility. Dataset thieu dew point, ceiling/cloud base, METAR weather code, RVR va fog observation; nen EDA chi nen xem humidity la bien phu hoac interaction feature.

## Crosswind va huong gio

| Airport | Dominant wind sectors | Hours xwind >=10 kt | Hours xwind >=15 kt | Max xwind |
|---|---|---:|---:|---:|
| DAD | NE 24.68%, E 21.33%, N 15.53% | 12 (0.54%) | 0 | 11.22 kt |
| HAN | SE 36.78%, NE 27.45%, S 10.51% | 71 (3.22%) | 0 | 14.41 kt |
| SGN | SE 30.39%, N 16.39%, S 12.50% | 1 (0.05%) | 0 | 10.15 kt |

Insight moi: neu noi ve gio, HAN dang dang chu y hon DAD. HAN co gio chu dao SE/NE va so gio crosswind >=10 kt cao nhat, nhung chua co gio >=15 kt. Do do nen viet la "moc can theo doi cho runway selection/pilot workload", khong viet la "gio ngang manh gay anh huong nghiem trong".

## HAN Jan-Mar: khong phai visibility, ma la rain/wet runway/crosswind

| Month | Rain hours | Rain rate | Heavy rain hours | Precip sum | Wet runway hours | Operational risk mean |
|---|---:|---:|---:|---:|---:|---:|
| 2026-01 | 117 | 15.73% | 1 | 52.0 mm | 117 | 0.335 |
| 2026-02 | 151 | 22.47% | 0 | 51.6 mm | 151 | 0.446 |
| 2026-03 | 46 | 11.98% | 0 | 15.8 mm | 46 | 0.255 |

Nhan xet "thang 3 HAN van on" phu hop voi data: visibility khong xau, mua thang 3 giam so voi Jan-Feb. Diem dang viet trong bao cao la Jan-Feb cua HAN co nhieu rain/wet runway hours, dac biet thang 2 co rain rate 22.47%.

## Case xau theo tung san bay

- SGN `2025-12-25 18:00`: visibility `4,400 m` (`2.73 SM`), precipitation `13.9 mm/h`, runway wet risk `2`, crosswind `1.55 kt`. Tac dong chinh: approach visibility + runway wet/braking, khong phai gio ngang.
- HAN `2026-01-01 05:00`: visibility tot/capped, precipitation `6.6 mm/h`, runway wet risk `2`. Tac dong chinh: heavy rain + wet runway.
- DAD worst cases trong score moi chu yeu la light rain + crosswind gan/vuot 10 kt, khong phai visibility nghiem trong.

## Ket luan viet lai cho EDA

- DAD: visibility duoi 10 km xuat hien nhieu, nhung severe visibility rat hiem; khong nen overstate.
- HAN: visibility on, nhung rain/wet runway Jan-Feb va crosswind >=10 kt la pattern can noi.
- SGN: it gio xau hon DAD theo ti le, nhung co case xau ro ve low visibility + heavy rain + wet runway; do traffic lon nen can tinh flight exposure.
- Visibility raw am voi risk la dung logic; dung visibility deficit/threshold de trinh bay tac dong.
- Huong gio phai di kem crosswind/headwind, vi crosswind khong noi het runway selection va tailwind risk.
