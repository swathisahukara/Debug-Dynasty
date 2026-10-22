"""python3 -m agents.run_one <package> [--as-of 2018-09-09T09:28:59]
Default as-of: one hour after the first answer-key version of that package, else the last release."""
import argparse, csv, json
from datetime import datetime, timedelta
from . import config as C, data, pipeline

ap = argparse.ArgumentParser(); ap.add_argument("package"); ap.add_argument("--as-of")
a = ap.parse_args()
if a.as_of: as_of = datetime.fromisoformat(a.as_of)
else:
    keys = [r for r in csv.DictReader((C.ROOT / "eval/answer_key.csv").open()) if r["package"] == a.package]
    if keys:
        times = [r for r in csv.DictReader((C.DATA_DIR / "releases.csv").open()) if r["package"] == a.package and r["version"] in {k["version"] for k in keys}]
        as_of = min(data._ts(t["published_at"]) for t in times) + timedelta(hours=1)
    else:
        as_of = datetime(2100, 1, 1)
res = pipeline.investigate(a.package, as_of)
res.pop("hits")
print(json.dumps(res, indent=1, default=str)); print("log:", pipeline.LOG)
