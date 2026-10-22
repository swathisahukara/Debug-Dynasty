"""Retriever: pulls one package's rows as of a cutoff, from Zetaris SQL (live) or CSV (SAMPLE_MODE)."""
import csv, json, os, re, urllib.request, urllib.error, uuid
from datetime import datetime
from . import config as C

PKG_RE = re.compile(r"^[a-z0-9@/._-]+$")


def _ts(s):
    s = s.replace("Z", "").replace("T", " ")
    if "." in s:  # Python 3.9 needs exactly 3 or 6 fractional digits; Zetaris can return 1 to 3
        head, frac = s.split(".", 1)
        s = head + "." + frac.ljust(6, "0")[:6]
    return datetime.fromisoformat(s)


def _zetaris(sql):
    body = json.dumps({"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 20000}).encode()
    req = urllib.request.Request(os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run", data=body, method="POST", headers={
        "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"], "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
        "X-Request-ID": str(uuid.uuid4()), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return [dict(zip(d["headers"], row)) for row in d.get("data", [])]


_CSV = {}


def _csv_by_pkg(name):
    """CSV rows grouped by package, read once per process (replay touches thousands of cells)."""
    if (name, str(C.DATA_DIR)) not in _CSV:
        g = {}
        with (C.DATA_DIR / f"{name}.csv").open() as f:
            for r in csv.DictReader(f): g.setdefault(r["package"], []).append(r)
        _CSV[(name, str(C.DATA_DIR))] = g
    return _CSV[(name, str(C.DATA_DIR))]


def _maintainers(pkg):
    """version -> set of maintainer accounts listed on that release (empty dict if the table is unavailable)."""
    try:
        if C.DATA_SOURCE == "zetaris":
            rows = _zetaris(f"SELECT version, maintainer FROM pkgtrail.maintainers_table WHERE package_name = '{pkg}'")
        else:
            rows = _csv_by_pkg("maintainers").get(pkg, [])
    except (OSError, KeyError, FileNotFoundError, urllib.error.URLError):
        return {}
    out = {}
    for r in rows: out.setdefault(r["version"], set()).add(r["maintainer"])
    return out


def fetch(pkg, as_of):
    """Returns (releases, dependencies) as lists of dicts, only rows published at or before as_of."""
    assert PKG_RE.match(pkg), "bad package name"
    if C.DATA_SOURCE == "zetaris":
        rel = _zetaris("SELECT package_name, version, published_at, publisher, install_scripts, dep_count, source FROM pkgtrail.releases_table "
                       f"WHERE package_name = '{pkg}' AND published_at <= TIMESTAMP '{as_of:%Y-%m-%d %H:%M:%S}' ORDER BY published_at")
        dep = _zetaris(f"SELECT version, dependency FROM pkgtrail.dependencies_table WHERE package_name = '{pkg}'")
        for r in rel: r["package"] = r.pop("package_name")
    else:
        rel = [dict(r) for r in _csv_by_pkg("releases").get(pkg, [])]
        dep = _csv_by_pkg("dependencies").get(pkg, [])
    mn = _maintainers(pkg)
    for r in rel:
        r["t"] = r.get("t") or _ts(r["published_at"])
        r["maintainers"] = mn.get(r["version"])  # None = unknown
    rel = sorted([r for r in rel if r["t"] <= as_of], key=lambda r: r["t"])
    seen = {r["version"] for r in rel}
    return rel, [d for d in dep if d["version"] in seen]


_AGES = {}


def dep_ages():
    """dependency name -> first-publish datetime (empty/missing = unknown). Read once per process."""
    if not _AGES:
        p = C.DATA_DIR / "dep_ages.csv"
        if p.exists():
            with p.open() as f:
                for r in csv.DictReader(f):
                    if r["first_published"]: _AGES[r["dependency"]] = _ts(r["first_published"])
        _AGES["__loaded__"] = None
    return _AGES
