"""Fetch npm packuments and flatten them to per-version row files.

Output (CSV): releases, maintainers, dependencies.
Per-version snapshots matter: top-level `maintainers` is current-only, and removed
versions appear in `time` but not in `versions` (flagged removed=1).
Usage: python snapshot/fetch_packuments.py [--out data/raw] [--sample data/sample]
"""
import argparse, csv, json, sys, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

INCIDENTS = ["event-stream", "ua-parser-js", "coa", "rc", "colors", "faker", "node-ipc", "chalk", "debug"]
CONTROLS = ["lodash", "express", "moment", "axios", "async", "underscore", "commander", "uuid", "minimist",
            "glob", "yargs", "semver", "mkdirp", "rimraf", "bluebird", "through2", "inherits",
            "readable-stream", "qs", "ms", "cookie", "body-parser", "chokidar", "cheerio", "dotenv",
            "jsonwebtoken", "mime", "ws", "yaml", "nanoid"]
INSTALL_HOOKS = ("preinstall", "install", "postinstall")
REG = "https://registry.npmjs.org/"


def fetch(pkg):
    url = REG + urllib.parse.quote(pkg, safe="@")
    req = urllib.request.Request(url, headers={"User-Agent": "package-trail-hackathon"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return pkg, json.load(r)


def flatten(pkg, doc, role):
    rel, mnt, dep = [], [], []
    times = doc.get("time", {})
    versions = doc.get("versions", {})
    for ver, ts in times.items():
        if ver in ("created", "modified"):
            continue
        v = versions.get(ver)
        if v is None:
            rel.append(dict(package=pkg, version=ver, published_at=ts, publisher="", removed=1,
                            install_scripts="", dep_count=0, git_head="", role=role))
            continue
        scripts = v.get("scripts") or {}
        hooks = ",".join(k for k in INSTALL_HOOKS if k in scripts)
        pub = (v.get("_npmUser") or {}).get("name", "")
        deps = v.get("dependencies") or {}
        rel.append(dict(package=pkg, version=ver, published_at=ts, publisher=pub, removed=0,
                        install_scripts=hooks, dep_count=len(deps), git_head=v.get("gitHead", ""), role=role))
        for m in v.get("maintainers") or []:
            mnt.append(dict(package=pkg, version=ver, maintainer=m.get("name", "")))
        for d, rng in deps.items():
            dep.append(dict(package=pkg, version=ver, dependency=d, range=rng))
    return rel, mnt, dep


def write(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--sample", default="data/sample")
    a = ap.parse_args()
    roles = {p: "incident" for p in INCIDENTS} | {p: "control" for p in CONTROLS}
    with ThreadPoolExecutor(8) as ex:
        docs = list(ex.map(fetch, roles))
    R, M, D = [], [], []
    for pkg, doc in docs:
        r, m, d = flatten(pkg, doc, roles[pkg])
        R += r; M += m; D += d
    rc = ["package", "version", "published_at", "publisher", "removed", "install_scripts", "dep_count", "git_head", "role"]
    out = Path(a.out)
    write(out / "releases.csv", R, rc)
    write(out / "maintainers.csv", M, ["package", "version", "maintainer"])
    write(out / "dependencies.csv", D, ["package", "version", "dependency", "range"])
    # small committed sample for SAMPLE_MODE: 3 incident + 3 control packages
    keep = {"event-stream", "ua-parser-js", "node-ipc", "lodash", "express", "uuid"}
    s = Path(a.sample)
    write(s / "releases.csv", [x for x in R if x["package"] in keep], rc)
    write(s / "maintainers.csv", [x for x in M if x["package"] in keep], ["package", "version", "maintainer"])
    write(s / "dependencies.csv", [x for x in D if x["package"] in keep], ["package", "version", "dependency", "range"])
    print(f"packages={len(docs)} releases={len(R)} maintainer_rows={len(M)} dep_rows={len(D)}")


if __name__ == "__main__":
    sys.exit(main())
