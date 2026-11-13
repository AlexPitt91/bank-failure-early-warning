# Bank Failure Early Warning

An interactive replay of annual U.S. bank screening using FDIC financial reports and resolution records. Choose a historical review date, model, and alert budget, then reveal which banks failed in the following year. Inspect the financial inputs behind an alert or a missed failure.

## Try the replay

From the repository root, run `python3 -m http.server 8000 --directory dist` and open [http://localhost:8000](http://localhost:8000). The demo reads the checked-in replay snapshot and needs no Python dependencies or API key to display.

Start with March 2023, boosted trees, and 20 alerts. Reveal outcomes and inspect Silicon Valley Bank under **Failures outside the alert budget**. It ranked 906th under boosted trees and 154th under logistic regression. This is a useful example of a genuine miss, even though its deposits had fallen 8.4% year over year.

## Held-out results

The 2020–2025 March review dates contain 29,205 bank observations and 13 eligible failure events. Each model receives 20 alerts per annual review, or 120 total.

| Model | Failures caught | Alert precision | Average precision | Median lead time among caught failures |
| --- | ---: | ---: | ---: | ---: |
| Low equity-to-assets rule | 3 / 13 | 2.5% | 0.98% | 229 days |
| Logistic regression | 5 / 13 | 4.2% | 5.05% | 229 days |
| Boosted trees | 6 / 13 | 5.0% | 21.31% | 232.5 days |

Boosted trees had the highest average precision among the candidate ML models on the earlier validation period. At the chosen budget it generated 114 alerts without a recorded failure inside the held-out windows. The table distinguishes alert precision at a fixed budget from average precision across score thresholds.

## Code map

| File | Responsibility |
| --- | --- |
| `bank_risk/fdic.py` | Downloads complete, sorted API pages and detects missing or duplicate records. |
| `bank_risk/panel.py` | Joins reports in SQLite by bank certificate and calendar year, applies eligibility and outcome rules, and derives model features. |
| `bank_risk/backtest.py` | Fits preprocessing and models on earlier years, selects on validation, evaluates later years, and exports the replay. |
| `dist/app.mjs` | Renders historical review dates, alert budgets, outcome reveal, and bank details in the browser. |
| `tests/test_backtest.py` | Tests cutoff inclusivity, eligibility, prior-year joins, chronological splits, budget rankings, and snapshot totals. |

The source snapshot contains 122,404 year-end financial reports for 2006–2024 and 562 resolution records through March 1, 2026. Only FDIC resolution type `FAILURE` contributes positive outcomes. One bank can appear in several annual reviews. Each review uses the prior December report and a fixed March 1 scoring date. Banks that failed on or before that date are excluded. The label window is the following day through March 1 of the next year, inclusive. Data from 2006 supplies lagged features for 2007.

Model fitting uses reports from 2007–2013, model selection uses 2014–2018, and final evaluation uses 2019–2024. Preprocessing medians and the logistic scaler are learned from training only. The exported demo stores ranks for the top 100 banks per model and date plus every eligible failure. Backtest metrics use the full held-out dataset.

## Reproduce locally

Use Python 3.12 and Node.js 22 or later.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m bank_risk.backtest
python -m unittest discover -s tests -v
node --check dist/app.mjs
```

The backtest reads `snapshots/fdic.json.gz` by default. The replay includes the uncompressed input's SHA-256. To fetch new copies of the same historical source records, run `python -m bank_risk.fdic` and then `python -m bank_risk.backtest --input data/fdic.json`. The shipped result tests deliberately pin the included snapshot. Review differences before updating them for a refreshed dataset.

For GitHub Pages, upload this repository, set **Settings → Pages → Source** to **GitHub Actions**, then manually run **Test and publish replay** on `main`. Pushes run checks automatically. The manual step enables you to decide when to publish.

## Limits and source

- The FDIC data is retrospective. March 1 is an assumed availability lag. Archived as-filed versions and revision timestamps would be needed for a strict point-in-time backtest.
- The annual schedule can miss fast-moving changes. The outcome includes only FDIC failures among eligible scored banks. An institution that exits for another reason has no recorded failure outcome in that window.
- With 13 eligible held-out events, results are sensitive to a few banks and may shift substantially in another period.
- The UI ranks banks using uncalibrated model scores. The feature score changes compare an input against the training median one at a time. They can be sensitive to correlated inputs and do not establish causes of failure.

Data source: [FDIC BankFind Suite API](https://api.fdic.gov/banks/docs/).
