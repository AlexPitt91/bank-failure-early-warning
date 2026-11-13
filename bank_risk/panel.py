"""Build one eligible observation per FDIC certificate and report year."""
import sqlite3

import numpy as np
import pandas as pd

FEATURES = {
    "equity_assets": "Equity / assets",
    "noncurrent_assets": "Noncurrent loans / assets",
    "return_assets": "Return on assets",
    "deposit_growth": "Year-over-year deposit growth",
    "uninsured_share": "Estimated uninsured / domestic deposits",
    "assets_log": "Log assets",
}
REPORT_COLUMNS = ("CERT", "NAME", "ASSET", "EQ", "DEP", "DEPDOM", "ROA", "NCLNLS", "DEPUNINS")
PANEL_SQL = """
WITH dated AS (
    SELECT
        r.*, printf('%04d-03-01', r.report_year + 1) AS score_date,
        printf('%04d-03-01', r.report_year + 2) AS horizon_end
    FROM reports r
)
SELECT d.cert, d.name, d.report_year, d.score_date, f.failure_date,
    1.0 * d.equity / NULLIF(d.assets, 0) AS equity_assets,
    CASE WHEN d.noncurrent >= 0
         THEN 1.0 * d.noncurrent / NULLIF(d.assets, 0) END AS noncurrent_assets,
    d.roa AS return_assets,
    CASE WHEN p.deposits > 0 AND d.deposits >= 0
         THEN 1.0 * d.deposits / p.deposits - 1 END AS deposit_growth,
    CASE WHEN d.uninsured BETWEEN 0 AND d.domestic AND d.domestic > 0
         THEN 1.0 * d.uninsured / d.domestic END AS uninsured_share,
    d.assets
FROM dated d
LEFT JOIN reports p ON p.cert = d.cert AND p.report_year = d.report_year - 1
LEFT JOIN failures f ON f.cert = d.cert AND f.failure_date <= d.horizon_end
WHERE d.report_year >= 2007 AND d.horizon_end <= :outcome_through
  AND d.assets > 0 AND (f.failure_date IS NULL OR f.failure_date > d.score_date)
ORDER BY d.report_year, d.cert
"""


def build_panel(snapshot, outcome_through):
    failures = pd.DataFrame(snapshot["failures"])
    # FDIC resolution type FAILURE identifies failures; assistance transactions have separate codes.
    failures = failures.loc[failures["RESTYPE"].eq("FAILURE"), ["CERT", "FAILDATE"]].copy()
    if failures.empty:
        raise ValueError("No FDIC failure records matched resolution type FAILURE")
    failures["FAILDATE"] = pd.to_datetime(failures["FAILDATE"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")

    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE reports (
                report_year INTEGER, cert INTEGER, name TEXT, assets REAL, equity REAL,
                deposits REAL, domestic REAL, roa REAL, noncurrent REAL, uninsured REAL,
                PRIMARY KEY (cert, report_year)
            );
            CREATE TABLE failures (cert INTEGER PRIMARY KEY, failure_date TEXT);
        """)
        db.executemany("INSERT INTO failures VALUES (?, ?)", failures.itertuples(index=False, name=None))
        for year, records in snapshot["financials"].items():
            rows = ((int(year), *(record.get(column) for column in REPORT_COLUMNS)) for record in records)
            db.executemany("INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        panel = pd.read_sql_query(PANEL_SQL, db, params={"outcome_through": outcome_through})

    panel["assets_log"] = np.log(panel.pop("assets"))
    panel["failed"] = panel["failure_date"].notna().astype(int)
    panel["lead_days"] = (
        pd.to_datetime(panel["failure_date"]) - pd.to_datetime(panel["score_date"])
    ).dt.days.astype("Int64")
    return panel
