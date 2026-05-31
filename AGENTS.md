# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python data pipeline for AeroDelay flight-delay analysis. Core scripts live in `Source code/`; crawler scripts are named `crawl_*.py`, preprocessing scripts include `data_preprocessing.py` and `weather_preprocessing.py`, streaming logic is in `kafka_stream.py`, and model code is in `feature_training.py` and `model_training.py`. Data artifacts live under `Data crawl/`, organized into `Bronze_layer/`, `Silver_layer/`, and audit/report subfolders. Project notes and preprocessing plans are kept in root Markdown files such as `silver_layer_preprocessing_plan.md` and `weather_preprocessing.md`.

## Build, Test, and Development Commands

Create an isolated environment before running scripts:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run individual pipeline stages from the repository root:

```bash
python "Source code/crawl_latest.py"
python "Source code/weather_preprocessing.py" --project-root "."
python "Source code/data_preprocessing.py" --project-root "."
python "Source code/model_training.py"
```

Some crawlers require browser drivers, network access, and stable upstream pages. Spark and Kafka scripts require local Spark/Kafka services configured outside the repo.

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, standard imports first, then third-party imports, then local imports. Prefer `pathlib.Path` for file paths because this repo has paths with spaces. Keep constants in uppercase (`AIRPORTS`, `VIS_LOW_M`) and functions in `snake_case`. Match existing airport codes and layer names exactly: `SGN`, `HAN`, `DAD`, `Bronze_layer`, `Silver_layer`.

## Testing Guidelines

No formal test suite is currently present. For changes to preprocessing, add focused checks where possible using `pytest` under a future `tests/` directory, with names like `test_weather_preprocessing.py`. At minimum, run the affected script against the existing CSV inputs and inspect generated audit files in `Data crawl/Silver_layer/Audit/`. Avoid committing generated cache files such as `__pycache__/`.

## Commit & Pull Request Guidelines

Recent commits use short, lowercase summaries such as `weather`, `silver`, and `update crawling missing flights code`. Keep messages concise but more descriptive when possible, for example `fix weather visibility thresholds`. Pull requests should describe the pipeline stage changed, list commands run, mention any data files regenerated, and include screenshots only for notebook plots or report figures.

## Security & Configuration Tips

Do not commit credentials, proxy lists, browser profiles, or API tokens. Put local settings in environment variables or an untracked `.env` file loaded with `python-dotenv`. Treat crawler outputs as reproducible data artifacts and document any manual data patches in the relevant `Audit/` CSV or Markdown plan.
