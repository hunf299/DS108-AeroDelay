# Data Layer Insights

## Vai tro cua thu muc nay

`Data crawl/` la noi luu artifact that su cua pipeline AeroDelay: du lieu bay Bronze, du lieu da chuan hoa Silver, audit kiem tra loi, file patch, va weather feature. Trong project nay, audit quan trong gan nhu ngang voi data dau ra, vi nguon FlightRadar thay doi UI/schema lien tuc va co nhieu case can sua tay.

## Bronze Layer

Bronze la snapshot gan nguon crawl nhat. Cac file chinh nam trong:

- `Bronze_layer/Arrival/`: arrival theo san bay `sgn`, `han`, `dad`.
- `Bronze_layer/Departure/`: departure theo san bay.
- `Bronze_layer/airport_weather_hourly_merged.csv`: weather hourly cho feature.
- `Bronze_layer/Audit/`: audit cua clean/patch truoc Silver.

Bronze arrival/departure co the chua `Actual_Time` chi la gio, trong khi `Crawl_Date` quyet dinh ngay service. Khong nen sua truc tiep Bronze neu khong ghi audit, vi sai ngay qua nua dem se lam hong matching arrival-departure o Silver.

## Silver Layer

Silver them datetime day du, co, match status, data completeness, runway fill, same-origin handling, aircraft swap flag, va cac audit missing match. Cac output hien tai nam trong `Silver_layer/`, nhung code moi trong `data_preprocessing.py` va `weather_preprocessing.py` dang ghi ra `Silver_layer_2/`. Truoc khi so sanh ket qua, phai xac dinh dung folder output.

## Audit Insights Hien Tai

Tu `Silver_layer/Audit/audit_summary.csv`:

- Tong rows input: 152,037; rows output: 151,929.
- `runway_missing_before`: 5,285; `runway_filled_nearest`: 5,102; `runway_filled_default`: 183.
- `invalid_runway_fixed`: 1,220; `invalid_iata_fixed`: 1.
- `cluster_duplicate_removed`: 70.
- `departures_marked_without_arrival_total`: 619.
- `arrivals_marked_without_departure_total`: 476.
- `same_origin_rows`: 84, trong do 30 return emergency duoc giu, 38 unmatched bi drop, 16 noncommercial duoc giu.

Cac con so nay la baseline. Neu rerun ma thay lech lon, can doc audit truoc khi tin vao file Silver.

## Nhung Dieu Can Dam Bao

- Luon giu dong bo 3 truong `Crawl_Date`, `Scheduled_Time`, `Actual_Time` khi patch.
- Kiem tra `audit_arrival_time_semantics.csv` de biet source nao la FlightRadar hay DAD-specific.
- Kiem tra `audit_deduplicate_decisions.csv` truoc khi xoa duplicate, vi flight trung so trong ngay co the la rotation that.
- Kiem tra `audit_departure_without_arrival.csv` va `audit_arrival_without_departure.csv` sau moi lan crawl bu sung.
- Weather feature co `visibility` bi cap cao; summary hien tai bao capped rate 83.74%, nen khong xem visibility raw la tin hieu lien tuc hoan hao.

## Nhung Dieu Can Tranh

- Khong overwrite Silver cu bang output moi neu chua backup audit di kem.
- Khong merge CSV chi dua tren `Flight_No`; phai kem route, ngay, gio, va neu co thi tail.
- Khong coi runway fill la du lieu goc. Cac dong fill nearest/default nen duoc danh dau khi train.
- Khong drop missing match hang loat neu chua xac nhan do crawl thieu hay do logic rollover ngay.
- Khong xoa audit vi audit la cach duy nhat truy vet cac manual fix va heuristic.
