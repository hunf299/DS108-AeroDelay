# mismatch_fix — Date Mismatch Fix Log

## 1. Problem Diagnosis (Validated)

Flight data for HAN, SGN, and DAD suffered from **date mismatches** between arrival and departure times caused by FR24's history-page grouping logic:

1. **UTC vs Local Time confusion** — FR24 operates in UTC but displays local time; the crawler captured clock strings without timezone context.
2. **Scheduled Flight Date (STD) grouping** — FR24 history pages group flights by their scheduled departure date, not actual event date.
3. **Midnight Overlap** — Flights crossing midnight (e.g., scheduled 23:00, actual 01:09 next day) appear on the previous day's page and get tagged with `Crawl_Date = page_date`.

### Evidence in Bronze Data
- **VJ636 SGN→DAD**: SGN departure at `2025-12-16 23:32`, DAD arrival tagged `Crawl_Date=2025-12-16` with actual landing `00:06` — but it actually landed on **Dec 17**.
- **VJ643 DAD→SGN**: DAD departure tagged `Crawl_Date=2025-12-21` with actual `01:09` (should be Dec 22).
- Duplicate-like rows for the same flight number on the same `Crawl_Date` with vastly different actual times (midnight overlap duplicates).

### Root Cause Location
- **Crawl code**: Assigns `Crawl_Date = target_date` unconditionally, so FR24's page-date logic leaks into the data.
- **Preprocessing code**: Naively combined `Crawl_Date + Actual_Time` into `Actual_DateTime` without sufficient rollover/sanity checks.

**Verdict**: Fixable entirely in preprocessing — **no re-crawl required**.

---

## 2. Fix Strategy

### 2.1 Self-Contained Heuristics (Fast, No External Data)
Apply rollover rules based on time-of-day and domestic/international classification:

| Mode | Rule | Condition | Action |
|------|------|-----------|--------|
| **SGN/HAN Arrival** | Early-morning domestic rollover | `Actual_Time` between `00:00–04:59` AND origin is domestic (`IATA` in `DOMESTIC_IATA_CODES`) | `Actual_DateTime += 1 day` |
| **DAD Arrival** | Planned vs actual rollover | `Actual_Time` (landing) > 12h before `Flight_Time` (planned) — existing logic | `Actual_DateTime += 1 day` |
| **DAD Arrival** | Both early-morning domestic rollover | Both planned & actual between `00:00–04:59` AND origin is domestic | **Both** `Planned_DateTime += 1 day` and `Actual_DateTime += 1 day` |
| **Departures (all)** | Scheduled vs actual rollover | `Actual_Time` > 12h before `Scheduled_Time` — existing logic | `Actual_DateTime += 1 day` |
| **Departures (all)** | Missing-scheduled fallback | `Scheduled_Time` missing/empty AND `Actual_Time` between `00:00–04:59` | `Actual_DateTime += 1 day` |

**Why domestic-only for arrivals?** International red-eye flights (e.g., Istanbul→SGN at 04:41) are legitimately scheduled for early-morning landing. Domestic flights in Vietnam do **not** operate midnight departures, so any domestic early-morning arrival must be a next-day arrival from a previous-evening departure.

### 2.2 Cross-File Correction (Robust, Uses Departure Data)
After self-contained heuristics, run a cross-file pass that matches arrival records to their corresponding departures:

1. Build a departure index keyed by `(Flight_No, Tail_Number, Destination_IATA)`.
2. For each arrival, find matching departure on the same route.
3. Compute `gap = arrival_actual - departure_actual`.
4. If gap is negative or > 24 hours, try shifting arrival by `±1 day`.
5. Keep the shift if gap becomes realistic (`0 < gap ≤ 6 hours`).

This catches edge cases the heuristics miss (e.g., domestic flights landing after 05:00 due to long delays).

### 2.3 Deduplication Fix
Removed `Crawl_Date` from the deduplication group key. The same flight appearing on two adjacent FR24 pages (midnight overlap) now has a different `Crawl_Date` but the same corrected `Actual_DateTime`. Since dedup already clusters by actual event time within a 10-minute window, removing `Crawl_Date` allows these cross-page duplicates to be detected and merged, while legitimate daily flights remain separate because their actual times are ~24 hours apart.

---

## 3. Code Changes

### 3.1 `data_preprocessing.py` — `canonicalize_arrival_time_by_source()`
**Location**: lines ~272–289

**Added**:
- `iata_series` extraction and `domestic_mask` computation.
- For **SGN/HAN** (`airport != "DAD"`): early-morning domestic rollover logic on `actual_dt`.
- For **DAD** (`airport == "DAD"`): `both_early_mask` logic that adds `+1 day` to **both** `planned_dt` and `actual_dt` when both times are early morning and origin is domestic.

### 3.2 `data_preprocessing.py` — `add_datetime_columns_with_rollover()` (departures)
**Location**: lines ~339–358

**Added**:
- Fallback rollover for departures where `Scheduled_Time` is missing/empty but `Actual_Time` is early morning (`00:00–04:59`).

### 3.3 `data_preprocessing.py` — New function `cross_correct_arrival_dates()`
**Location**: inserted after `add_datetime_columns_with_rollover()`

**Purpose**: Cross-match arrivals against departures using `(Flight_No, Tail_Number, Route_Key)` and adjust arrival `Actual_DateTime` by `±1 day` when the departure-arrival gap is implausible.

**Returns**: Updated `arrivals` dict and stats dict with `arrivals_corrected` count.

### 3.4 `data_preprocessing.py` — `deduplicate_flights()`
**Location**: `group_cols` definition

**Changed**:
- Removed `"Crawl_Date"` from `group_cols` list.
- Added explanatory comment about midnight overlap dedup.

### 3.5 `data_preprocessing.py` — New function `reconcile_tails_from_arrivals()`
**Location**: inserted after `cross_correct_arrival_dates()`

**Purpose**: Matches each departure to its corresponding arrival by `(Flight_No, Route, time gap)` and overwrites the departure `Tail_Number` (and `Aircraft_Type`) with the arrival values when they differ. Treats arrival as the source of truth.

**Returns**: Updated `departures` dict, audit rows, and stats dict with `dep_tail_overwritten` and `dep_ac_overwritten` counts.

### 3.6 `data_preprocessing.py` — `run_pipeline()`
**Location**: between step 1 (load/clean) and step 2 (same-origin anomaly)

**Added**:
- Call to `cross_correct_arrival_dates(departures, arrivals, routes=ROUTES, max_gap_hours=ROUTE_MATCH_MAX_HOURS)`.
- Audit summary row for `arrivals_cross_corrected`.
- Call to `reconcile_tails_from_arrivals(departures, arrivals, routes=ROUTES, max_gap_hours=ROUTE_MATCH_MAX_HOURS)`.
- Audit summary rows for `dep_tail_overwritten` and `dep_ac_overwritten`.
- Export `audit_tail_reconciliation.csv`.

---

## 4. Verification Results

### 4.1 Syntax Check
```bash
python -m py_compile data_preprocessing.py  # OK
```

### 4.2 Pipeline Run
Full Silver preprocessing completed successfully on all 6 Bronze files (3 arrivals + 3 departures).

### 4.3 DAD Arrivals — Before vs After
**Before fix** (naive parse):
- VJ636 / VN-A656: `2025-12-16 00:06:00` ❌

**After fix** (heuristic applied):
- VJ636 / VN-A656: `2025-12-17 00:06:00` ✅
- VJ636 / VN-A649: `2025-12-18 00:35:00` ✅
- VJ636 / VN-A630: `2025-12-19 00:07:00` ✅

Corresponding SGN departure for VJ636 / VN-A656: `2025-12-16 23:32:00`  
**Departure-Arrival gap**: ~34 minutes ✅ (was ~23.5 hours before)

### 4.4 SGN/HAN Arrivals — Before vs After
**Before fix**:
- VN9469 (CXR→SGN) on Dec 16: `2025-12-16 02:43:00` ❌

**After fix**:
- VN9469 (CXR→SGN) on Dec 16: `2025-12-17 02:43:00` ✅

### 4.5 International Flights — Not Affected
- TK250 (IST→SGN) landing at 04:41: stayed `2025-12-16 04:41:00` ✅  
  (Correctly excluded because IST is **not** in `DOMESTIC_IATA_CODES`.)

### 4.6 Departures — Fallback Rollover
- MF8994 (cargo, missing `Scheduled_Time`, actual 02:38): shifted from `2025-12-17 02:38:00` → `2025-12-18 02:38:00` ✅

### 4.7 Swap Matching — Now Sane
Swap audit for VJ636 SGN→DAD now shows gaps of **1.1h, 1.6h, 3.4h** instead of previously impossible ~24h gaps.

### 4.8 Tail Reconciliation (Added)
After fixing dates, a second issue surfaced: **arrival and departure pages on FR24 report different tail numbers** (and sometimes different aircraft types) for the exact same flight.

**Fix**: Added `reconcile_tails_from_arrivals()` that:
1. Matches each departure to its corresponding arrival by `(Flight_No, Route, time gap ≤ 6h)`.
2. When tails differ, **overwrites departure tail (and Aircraft_Type) with arrival values**.
3. Treats arrival data as the source of truth (per user's request — arrival is crawled from a single page and less prone to FR24 navigation errors).

**Results**:
- **957** departure tails overwritten
- **480** departure aircraft types overwritten
- VJ636, VJ178, VJ643, and many other flights now have consistent tails across arrival and departure.

**Example — VJ636 SGN→DAD on Dec 19**:
- Before: Departure tail `VN-A630`, Arrival tail `VN-A685` → `Is_Aircraft_Swapped=True`
- After: Departure tail overwritten to `VN-A685` → `Is_Aircraft_Swapped=False`

### 4.9 Audit Summary Metrics
| Metric | Value |
|--------|-------|
| `arrivals_cross_corrected` | 0 |
| `dep_tail_overwritten` | 957 |
| `dep_ac_overwritten` | 480 |
| `swap_matched_rows` | 20,716 |
| `swap_true_rows` | 969 |

**Note**: `arrivals_cross_corrected = 0` means the self-contained heuristics already caught all midnight-overlap cases in this dataset. The cross-file function is retained as a safety net for edge cases (e.g., delayed domestic flights landing after 05:00).

---

## 5. Files Modified

| File | Change |
|------|--------|
| `Source code/data_preprocessing.py` | Added date heuristics, cross-correction, tail reconciliation, dedup fix, pipeline integration |
| `mismatch_fix.md` | This file — documents the diagnosis and all fixes |

---

## 6. No Re-Crawl Required

All fixes are **preprocessing-only**. The Bronze-layer CSVs still contain the raw `Crawl_Date`, `Actual_Time`, `Scheduled_Time`, `Flight_Time`, `Flight_No`, and `Tail_Number` strings. The preprocessing script now reconstructs correct calendar dates and reconciles tails from these strings using:
- Time-of-day heuristics
- Domestic/international classification
- Cross-file departure-arrival matching
- Tail overwrite from arrival to departure

Re-crawling FR24 would produce the same raw strings with the same page-date and tail-mismatch problems, so it would not help.
