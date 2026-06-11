# Gold Flight Feature EDA Addendum

## Scope

This addendum reviews flight-only Gold-layer features: delay, turnaround, tail rotation, airport load, congestion, binary flags, categorical operation fields, and feature correlations. Weather columns are excluded.

## Delay Validation

0/74,722 departure Gold rows have `Departure_Delay` differing by more than 1 minute from the delay recomputed from `Scheduled_Time` and `Actual_Time`. Any non-zero value here should trigger a feature/export mapping audit before regression modeling.

## Turnaround Long-Ground Handling

`Is_Long_Ground_Turnaround` flags 1,235 departure rows. Example: SGN VJ260 tail VN-A663 has capped raw buffer 4,320 minutes; use `Turnaround_Buffer_Model` and `Tail_Stagnation_Duration_Model`, not raw long-ground values, for short-horizon delay propagation.

## Correlation Insight

Top Spearman correlations with the regression target among flight-only predictor candidates: Number_of_Flights_in_Last_Hour=0.443, Airport_Load_Factor=0.362, Rolling_Departure_Delay_Tail_3=0.340, Prev_Departure_Delay_Tail_1=0.325, Ground_Handling_Pressure=0.320, Is_Airport_Congested=0.306, Standard_Turnaround=0.287, Taxi_Out_Congestion=0.276. Raw `Departure_Delay` is label source, not a predictor. `Runway_Swap_Event`, `Matched_Actual_Tail`, and `Swap_Match_Gap_Minutes` are excluded from Gold training exports because they are linkage/leakage-risk fields.

## Leakage Review

`A_CDM_TOBT_Deficit` uses previous actual arrival plus standard turnaround against current scheduled departure, so it is acceptable when previous arrival is already known. `Ground_Handling_Pressure` uses previous arrivals before scheduled departure. `Taxi_Out_Congestion` now uses scheduled departures before STD, avoiding current-flight Actual_Time leakage.
