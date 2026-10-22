"""Merge real npm rows (data/raw) with labeled synthetic overrides -> data/build, plus data/sample.
Every output row has source = npm | synthetic. Synthetic rows replace the registry row for versions the
registry removed (removed versions keep only a publish time). Usage: python3 snapshot/build_dataset.py
"""
import csv, collections
from pathlib import Path

RAW, SYN, OUT, SAMPLE = Path("data/raw"), Path("data/synthetic/release_overrides.csv"), Path("data/build"), Path("data/sample")
rd = lambda n: list(csv.DictReader((RAW / n).open()))


def write(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)


rel, mnt, dep = rd("releases.csv"), rd("maintainers.csv"), rd("dependencies.csv")
for r in rel + mnt + dep: r["source"] = "npm"
by_pkg = collections.defaultdict(list)
for r in rel: by_pkg[r["package"]].append(r)
idx = {(r["package"], r["version"]): r for r in rel}
overrides = list(csv.DictReader(SYN.open()))
new_dep, new_mnt = [], []
for o in overrides:
    p, v = o["package"], o["version"]
    row = idx[(p, v)]
    assert row["removed"] == "1", f"{p}@{v} exists in registry; synthetic override not needed"
    prior = sorted([r for r in by_pkg[p] if r["published_at"] < row["published_at"] and r["removed"] == "0"], key=lambda r: r["published_at"])
    prev = prior[-1] if prior else None
    src = prev if o["inherit_from"] == "@prev" else idx[(p, o["inherit_from"])]
    row["publisher"] = prev["publisher"] if o["publisher"] == "@prev" else o["publisher"]
    row["install_scripts"] = o["install_scripts"]
    row["source"] = "synthetic"
    row["git_head"] = ""
    inherited = [d for d in dep if d["package"] == p and d["version"] == src["version"]]
    for d in inherited: new_dep.append(dict(package=p, version=v, dependency=d["dependency"], range=d["range"], source="synthetic"))
    if o["extra_dependency"]:
        new_dep.append(dict(package=p, version=v, dependency=o["extra_dependency"], range=o["extra_dependency_range"], source="synthetic"))
    row["dep_count"] = sum(1 for d in new_dep if d["package"] == p and d["version"] == v)
    row["removed"] = "1"  # still removed in the registry; kept for scoring only
    for m in [m for m in mnt if m["package"] == p and m["version"] == src["version"]]:
        new_mnt.append(dict(package=p, version=v, maintainer=m["maintainer"], source="synthetic"))
dep += new_dep; mnt += new_mnt
rc = ["package", "version", "published_at", "publisher", "removed", "install_scripts", "dep_count", "git_head", "role", "source"]
mc, dc = ["package", "version", "maintainer", "source"], ["package", "version", "dependency", "range", "source"]
write(OUT / "releases.csv", rel, rc); write(OUT / "maintainers.csv", mnt, mc); write(OUT / "dependencies.csv", dep, dc)
keep = {"event-stream", "ua-parser-js", "node-ipc", "lodash", "express", "uuid"}
write(SAMPLE / "releases.csv", [x for x in rel if x["package"] in keep], rc)
write(SAMPLE / "maintainers.csv", [x for x in mnt if x["package"] in keep], mc)
write(SAMPLE / "dependencies.csv", [x for x in dep if x["package"] in keep], dc)
ages = list(csv.DictReader((RAW / "dep_ages.csv").open()))
ov = {r["dependency"]: r for r in csv.DictReader(open("data/synthetic/dep_age_overrides.csv"))}
for a in ages:
    if a["dependency"] in ov: a["first_published"], a["source"] = ov[a["dependency"]]["first_published"], "synthetic"
known = {a["dependency"] for a in ages}
ages += [dict(dependency=k, first_published=v["first_published"], source="synthetic") for k, v in ov.items() if k not in known]
write(OUT / "dep_ages.csv", ages, ["dependency", "first_published", "source"]); write(SAMPLE / "dep_ages.csv", ages, ["dependency", "first_published", "source"])
print(f"releases={len(rel)} (synthetic {sum(r['source']=='synthetic' for r in rel)}) maintainers={len(mnt)} dependencies={len(dep)} (synthetic {len(new_dep)})")
