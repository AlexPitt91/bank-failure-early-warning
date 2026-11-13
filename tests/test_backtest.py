"""Regression tests for temporal eligibility, rankings, and the shipped replay."""
import json
from pathlib import Path
import unittest

import pandas as pd

from bank_risk.backtest import NAMES, metrics_at_budget, split_years
from bank_risk.panel import build_panel


def report(cert, deposits):
    return {"CERT": cert, "NAME": f"Bank {cert}", "ASSET": 1000, "EQ": 50,
            "DEP": deposits, "DEPDOM": deposits, "ROA": 1.2, "NCLNLS": 10, "DEPUNINS": 20}


def failure(cert, date, resolution="FAILURE"):
    return {"CERT": cert, "FAILDATE": date, "RESTYPE": resolution}


class TestPanel(unittest.TestCase):
    def test_label_window_censoring_and_prior_year_join(self):
        snapshot = {
            "financials": {
                "2020": [report(1, 100), report(2, 100), report(3, 100),
                         report(4, 100), report(5, 100), report(6, 100)],
                "2021": [report(1, 80), report(2, 100), report(3, 100),
                         report(4, 100), report(5, 100), report(6, 100), report(7, 100)],
                "2022": [report(1, 70)],
            },
            "failures": [
                failure(1, "3/2/2022"), failure(2, "3/1/2022"),
                failure(3, "3/1/2023"), failure(4, "3/2/2023"),
                failure(5, "9/1/2022", "ASSISTANCE"), failure(6, "2/28/2022"),
            ],
        }
        panel = build_panel(snapshot, "2023-03-01")
        eligible = panel.loc[panel["report_year"].eq(2021)].set_index("cert")
        self.assertEqual(eligible.index.tolist(), [1, 3, 4, 5, 7])
        self.assertEqual(eligible["failed"].tolist(), [1, 1, 0, 0, 0])
        self.assertEqual(eligible.loc[1, "lead_days"], 1)
        self.assertAlmostEqual(eligible.loc[1, "deposit_growth"], -0.2)
        self.assertTrue(pd.isna(eligible.loc[7, "deposit_growth"]))
        self.assertEqual(panel["report_year"].max(), 2021)

    def test_splits_are_ordered(self):
        train, validation, test = split_years(pd.DataFrame({"report_year": range(2007, 2025)}))
        self.assertEqual((train.report_year.max(), validation.report_year.min()), (2013, 2014))
        self.assertEqual((validation.report_year.max(), test.report_year.min()), (2018, 2019))


class TestReplay(unittest.TestCase):
    def test_budget_applies_per_review_and_ties_use_certificate(self):
        panel = pd.DataFrame({"report_year": [2020, 2020, 2021, 2021], "cert": [2, 1, 4, 3],
                              "failed": [0, 1, 1, 0], "lead_days": [None, 20, 30, None]})
        result = metrics_at_budget(panel, [0.7, 0.7, 0.2, 0.3], budget=1)
        self.assertEqual((result["alerts"], result["caught"], result["failures"]), (2, 1, 2))
        self.assertEqual(result["median_lead_days"], 20)

    def test_snapshot_matches_reported_results(self):
        path = Path(__file__).resolve().parents[1] / "dist" / "replay.json"
        report = json.loads(path.read_text())
        self.assertEqual(len(report["cohorts"]), 6)
        self.assertEqual(sum(cohort["size"] for cohort in report["cohorts"].values()), 29205)
        for index, model in enumerate(NAMES):
            caught = 0
            failures = 0
            for cohort in report["cohorts"].values():
                banks = cohort["banks"]
                ranks = {bank["ranks"][index] for bank in banks}
                self.assertTrue(set(range(1, 101)) <= ranks)
                self.assertEqual(len(ranks), len(banks))
                caught += sum(bool(bank["failure"]) and bank["ranks"][index] <= report["budget"]
                              for bank in banks)
                failures += sum(bool(bank["failure"]) for bank in banks)
            self.assertEqual((caught, failures),
                             (report["results"][model]["caught"], report["results"][model]["failures"]))
