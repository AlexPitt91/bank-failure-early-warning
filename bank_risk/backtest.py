"""Fit earlier years, compare on validation years, and export a later historical replay."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from bank_risk.fdic import OUTCOME_THROUGH
from bank_risk.panel import FEATURES, build_panel

KEYS = list(FEATURES)
NAMES = {"baseline": "Equity rule", "logistic": "Logistic regression", "trees": "Boosted trees"}
BUDGET = 20
MAX_REPLAY_BUDGET = 100


def split_years(panel):
    years = panel["report_year"]
    return panel[years <= 2013], panel[years.between(2014, 2018)], panel[years >= 2019]


def score_models(training, evaluation, models):
    values = evaluation[KEYS]
    # Keep raw ratio ranking comparable across years. Missing ratios receive the training median.
    scores = {"baseline": -values["equity_assets"].fillna(training["equity_assets"].median()).to_numpy()}
    for name, model in models.items():
        scores[name] = model.predict_proba(values)[:, 1]
    return scores


def ranked_by_year(evaluation, scores):
    return evaluation.assign(score=scores).sort_values(
        ["report_year", "score", "cert"], ascending=[True, False, True]
    )


def metrics_at_budget(evaluation, scores, budget=BUDGET):
    ranked = ranked_by_year(evaluation, scores)
    alerts = ranked.groupby("report_year", sort=False).head(budget)
    hits = int(alerts["failed"].sum())
    events = int(evaluation["failed"].sum())
    lead = alerts.loc[alerts["failed"].eq(1), "lead_days"]
    return {
        "average_precision": float(average_precision_score(evaluation["failed"], scores)) if events else None,
        "alerts": len(alerts),
        "caught": hits,
        "failures": events,
        "precision": hits / len(alerts) if len(alerts) else None,
        "recall": hits / events if events else None,
        "median_lead_days": float(lead.median()) if len(lead) else None,
    }


def driver_arrays(model, features, scores, reference):
    """Score impact of replacing one value at a time with its training median."""
    impacts = []
    for key in KEYS:
        modified = features.assign(**{key: reference[key]})
        impacts.append(scores - model.predict_proba(modified)[:, 1])
    return np.stack(impacts, axis=1)


def export_replay(test, scores, models, training, selected, validation):
    reference = training[KEYS].median()
    impacts = {name: driver_arrays(model, test[KEYS], scores[name], reference)
               for name, model in models.items()}
    test = test.reset_index(drop=True)
    rankings = pd.DataFrame({
        name: ranked_by_year(test, values).groupby("report_year").cumcount().add(1)
        for name, values in scores.items()
    })
    eligible = rankings.le(MAX_REPLAY_BUDGET).any(axis=1) | test["failed"].eq(1)
    sizes = test.groupby("score_date").size()
    replay = {date: {"size": int(size), "banks": []} for date, size in sizes.items()}
    for index, row in zip(test.index[eligible], test.loc[eligible].itertuples(index=False)):
        item = {
            "cert": row.cert, "name": row.name, "failure": row.failure_date,
            "ranks": [int(rankings.at[index, name]) for name in NAMES],
            "values": [round(float(getattr(row, key)), 6) if pd.notna(getattr(row, key)) else None
                       for key in KEYS],
        }
        for name, impact in impacts.items():
            ordered = np.argsort(-np.abs(impact[index]), kind="stable")[:2]
            item[name] = [[int(key), round(float(impact[index, key]), 6)] for key in ordered]
        replay[row.score_date]["banks"].append(item)
    return {
        "models": NAMES, "features": FEATURES, "budget": BUDGET,
        "reference": {key: round(float(value), 6) for key, value in reference.items()},
        "selected": selected, "validation": validation,
        "results": {name: metrics_at_budget(test, values) for name, values in scores.items()},
        "cohorts": replay,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("snapshots/fdic.json.gz"))
    parser.add_argument("--output", type=Path, default=Path("dist/replay.json"))
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if args.input.suffix == ".gz":
        raw = gzip.decompress(raw)
    panel = build_panel(json.loads(raw), OUTCOME_THROUGH)
    training, validation, test = split_years(panel)
    for name, frame in (("train", training), ("validation", validation), ("test", test)):
        if frame["failed"].nunique() != 2:
            raise ValueError(f"{name} requires positive and negative observations")
        print(f"{name}: {len(frame):,} observations, {frame.failed.sum():,} failures")
    models = {
        "logistic": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  LogisticRegression(max_iter=1000, random_state=7)),
        "trees": make_pipeline(SimpleImputer(strategy="median"),
                               HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=12,
                                                              min_samples_leaf=50, random_state=7)),
    }
    for model in models.values():
        model.fit(training[KEYS], training["failed"])
    validation_scores = score_models(training, validation, models)
    validation_results = {name: metrics_at_budget(validation, values)
                          for name, values in validation_scores.items()}
    selected = max(models, key=lambda name: validation_results[name]["average_precision"])
    test_scores = score_models(training, test, models)
    report = export_replay(test, test_scores, models, training, selected, validation_results)
    report["input_sha256"] = sha256(raw).hexdigest()
    report["panel_rows"] = len(panel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, allow_nan=False, separators=(",", ":")))
    temporary.replace(args.output)
    print(json.dumps(report["results"], indent=2))


if __name__ == "__main__":
    main()
