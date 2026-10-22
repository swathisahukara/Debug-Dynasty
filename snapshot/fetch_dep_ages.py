"""First-publish date of every dependency in the snapshot (earliest version time in the registry). -> data/raw/dep_ages.csv
Usage: python3 snapshot/fetch_dep_ages.py"""
import csv, json, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def first_published(name):
    try:
        req = urllib.request.Request("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"), headers={"User-Agent": "package-trail-hackathon"})
        with urllib.request.urlopen(req, timeout=60) as r: t = json.load(r).get("time", {})
        times = [v for k, v in t.items() if k not in ("created", "modified")]
        return name, (min(times) if times else t.get("created", ""))
    except Exception:
        return name, ""


if __name__ == "__main__":
    names = sorted({r["dependency"] for r in csv.DictReader(open("data/raw/dependencies.csv"))})
    with ThreadPoolExecutor(12) as ex: rows = list(ex.map(first_published, names))
    Path("data/raw").mkdir(parents=True, exist_ok=True)
    with open("data/raw/dep_ages.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["dependency", "first_published", "source"]); [w.writerow([n, t, "npm"]) for n, t in rows]
    print(f"{len(rows)} dependencies, {sum(1 for _, t in rows if not t)} without a date")
