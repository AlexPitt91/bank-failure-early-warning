"""Download complete, dated snapshots from the public FDIC BankFind API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.fdic.gov/banks"
YEARS = range(2006, 2025)
OUTCOME_THROUGH = "2026-03-01"
FIELDS = "CERT,RISDATE,ASSET,EQ,DEP,DEPDOM,ROA,NAME,NCLNLS,DEPUNINS"
PAGE_SIZE = 5000


def fetch_page(resource, params):
    url = f"{API}/{resource}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "bank-risk-research/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == 2 or (isinstance(error, HTTPError) and error.code < 500 and error.code != 429):
                raise
            time.sleep(2 ** attempt)


def collect(resource, **params):
    rows = []
    total = None
    while total is None or len(rows) < total:
        page = fetch_page(resource, {**params, "limit": PAGE_SIZE, "offset": len(rows)})
        page_total = int(page["meta"]["total"])
        if total is not None and page_total != total:
            raise ValueError(f"{resource} changed during pagination")
        total = page_total
        batch = [item["data"] for item in page["data"]]
        if not batch and len(rows) < total:
            raise ValueError(f"Incomplete {resource} response")
        rows.extend(batch)
    if len(rows) != total or len({row["ID"] for row in rows}) != total:
        raise ValueError(f"Missing or duplicate {resource} records")
    return rows


def download_year(year):
    rows = collect("financials", filters=f"RISDATE:{year}-12-31",
                   fields=FIELDS, sort_by="CERT", sort_order="ASC")
    if not rows or any(str(row["RISDATE"]) != f"{year}1231" for row in rows):
        raise ValueError(f"Unexpected records for {year}")
    print(f"{year}: {len(rows):,} reports", flush=True)
    return str(year), rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/fdic.json"))
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=6) as executor:
        reports = dict(executor.map(download_year, YEARS))
    events = collect("failures", filters=f"FAILDATE:[2006-01-01 TO {OUTCOME_THROUGH}]",
                     fields="CERT,FAILDATE,RESTYPE,NAME", sort_by="FAILDATE", sort_order="ASC")
    if not events or any("FAILDATE" not in event for event in events):
        raise ValueError("FDIC response has no valid failure records")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"financials": reports, "failures": events}, separators=(",", ":")))
    temporary.replace(args.output)
    print(f"Saved {sum(map(len, reports.values())):,} reports and {len(events):,} events")


if __name__ == "__main__":
    main()
