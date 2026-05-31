# Source Code Insights

## Tong Quan

`Source code/` gom ba nhom chinh: crawler FlightRadar/DAD, cleaning + Silver preprocessing, va weather preprocessing. Mot so file nhu `data_processing_spark.py`, `feature_training.py`, `kafka_stream.py`, `model_training.py` hien dang rong, nen logic that su nam chu yeu trong `clean.py`, `data_preprocessing.py`, `weather_preprocessing.py`, va cac file `crawl_*.py`.

## Crawler Insights

Crawler phu thuoc nang vao Selenium, login/manual session, `data-testid` cua FlightRadar, cache JSON, va sleep/retry. FlightRadar thay doi UI se lam sai selector ma khong nhat thiet crash; co the sinh dong rong, sai status, sai runway, thieu tail, hoac sai scheduled time.

Nhung diem can chu y:

- `crawl_arrival_history.py` va `crawl_departure_history.py` co `START_DATE`, `END_DATE`, airport code hard-code trong file.
- `crawl_departure_history.py` va `crawl_latest.py` co cache schedule theo flight number; cache cu co the lam sai scheduled time khi lich bay doi.
- `crawl_missing_*` dung multi-thread/browser profile rieng, can canh tranh ghi CSV bang lock.
- Cac selector `data-testid` la diem de vo nhat; sau moi lan FR24 doi UI, can crawl sample nho va doi chieu bang tay.

## Preprocessing Insights

`clean.py` xu ly chuan hoa airline/category/terminal, SPQ -> 9G, fix route name, manual rows, va DAD-specific rules. `data_preprocessing.py` la pipeline lon nhat: parse datetime, xu ly qua nua dem, deduplicate, same-origin return emergency, runway fill, match arrival-departure, aircraft swap, va export audit.

Nhung constant quan trong:

- `RETURN_THRESHOLD_MINUTES_DEFAULT = 150`
- `ROUTE_MATCH_MAX_HOURS = 6.0`
- `DEDUP_CLUSTER_WINDOW_MINUTES = 150`
- `DEPARTURE_ARRIVAL_MATCH_EARLY_TOLERANCE_HOURS = 2.0`
- `RUNWAY_REGEX = ^(0[1-9]|[1-3][0-9])[LR]$`

Thay cac nguong nay se anh huong truc tiep den so dong duplicate, missing match, return emergency, va training eligibility.

## Weather Pipeline Insights

`weather_preprocessing.py` doc `Bronze_layer/airport_weather_hourly_merged.csv`, audit missing/outlier, clip theo physical bounds, impute theo airport, tinh crosswind/headwind theo runway heading mac dinh, tao risk flags va `Weather_Delay_Risk_Score`. Code hien ghi output vao `Data crawl/Silver_layer_2/Features`, khac voi folder `Silver_layer/Features` dang co san.

## Nhung Dieu Can Dam Bao

- Chay script tu repo root hoac truyen `--project-root "."` de path co space van dung.
- Sau moi thay doi preprocessing, so sanh `audit_summary.csv`, missing match audit, duplicate audit, va sample output.
- Neu them manual fix, phai ghi audit row va summary count tuong ung.
- Neu thay selector crawler, test tren 1 ngay/1 san bay truoc khi crawl dai ngay.
- Neu dung cache FlightRadar, can biet cache theo flight number co the khong du phan biet route/ngay.

## Nhung Dieu Can Tranh

- Khong hard-code them rule moi vao giua pipeline neu khong co audit.
- Khong sua Bronze/Silver bang Excel roi commit ma khong co script tai tao.
- Khong doi ten cot output tuy tien; downstream audit va model can schema on dinh.
- Khong coi output `Silver_layer` va `Silver_layer_2` la cung mot version.
- Khong train model tren dong co `Exclude_From_Propagation_Training = True` neu muc tieu la delay propagation.
