"""Archive the finished v1 results, then drop the entries that the v2 fixes affect so run_eval re-runs only those:
all 'agent' runs (risk-consistency check) and 'single' runs that ended 'unknown' (JSON parser fix)."""
import json, shutil
from pathlib import Path
R = Path("eval/results")
shutil.copy(R / "cache.jsonl", R / "cache_v1.jsonl"); shutil.copy(R / "scoreboard.json", R / "scoreboard_v1.json")
keep = []
for l in (R / "cache.jsonl").read_text().splitlines():
    r = json.loads(l)
    if r["system"] == "agent" or (r["system"] == "single" and r["risk_level"] == "unknown"): continue
    keep.append(l)
(R / "cache.jsonl").write_text("\n".join(keep) + "\n")
print(f"kept {len(keep)} cached runs; archived v1 to cache_v1.jsonl and scoreboard_v1.json")
