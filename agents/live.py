"""Live registry mode: fetch one packument from registry.npmjs.org, flatten it to the same rows the Zetaris tables hold, and
run the same indicators. Read-only, no API keys, no LLM. Only registry.npmjs.org is ever contacted (package names are validated).
Removed versions keep only their publish time, exactly as in the snapshot dataset."""
import collections, json, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from . import data

REG = "https://registry.npmjs.org/"
MAX_BYTES = 25_000_000
TTL_S = 600
INSTALL_HOOKS = ("preinstall", "install", "postinstall")
_CACHE, _LOCK = {}, threading.Lock()


class LiveError(Exception):
    pass


def _get(pkg, timeout=25):
    if not data.PKG_RE.match(pkg): raise LiveError("bad package name")
    req = urllib.request.Request(REG + urllib.parse.quote(pkg, safe="@"), headers={"User-Agent": "package-trail-hackathon", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise LiveError("package not found on the npm registry" if e.code == 404 else f"registry error {e.code}")
    except OSError as e:
        raise LiveError(f"registry unreachable: {e}")
    if len(raw) > MAX_BYTES: raise LiveError("packument is over 25 MB, too large for the live check")
    try: return json.loads(raw)
    except ValueError: raise LiveError("registry returned invalid JSON")


def packument(pkg):
    with _LOCK:
        hit = _CACHE.get(pkg)
        if hit and time.time() - hit[0] < TTL_S: return hit[1]
    doc = _get(pkg)
    with _LOCK:
        if len(_CACHE) > 40: _CACHE.clear()
        _CACHE[pkg] = (time.time(), doc)
    return doc


def rows(pkg, doc):
    """packument -> (releases, dependencies) in the shape agents.indicators expects."""
    rel, dep, versions = [], [], doc.get("versions") or {}
    for ver, ts in (doc.get("time") or {}).items():
        if ver in ("created", "modified"): continue
        v, t = versions.get(ver), data._ts(ts)
        if v is None:  # unpublished or removed: only the publish time survives
            rel.append(dict(package=pkg, version=ver, t=t, publisher="", install_scripts="", dep_count=0, maintainers=None, source="npm", removed=1))
            continue
        scripts, deps = v.get("scripts") or {}, v.get("dependencies") or {}
        rel.append(dict(package=pkg, version=ver, t=t, publisher=(v.get("_npmUser") or {}).get("name", ""), source="npm", removed=0,
                        install_scripts=",".join(k for k in INSTALL_HOOKS if k in scripts), dep_count=len(deps),
                        maintainers={m.get("name", "") for m in v.get("maintainers") or []} or None))
        dep += [dict(version=ver, dependency=d) for d in deps]
    rel.sort(key=lambda r: r["t"])
    return rel, dep


def dep_ages_for(rel, dep, as_of, days=30, limit=8):
    """First-publish time of dependencies newly added in recent same-major releases (what the new_dependency indicator needs)."""
    deps = collections.defaultdict(set)
    for d in dep: deps[d["version"]].add(d["dependency"])
    need, cut = set(), as_of - timedelta(days=days)
    for i, r in enumerate(rel):
        if i == 0 or r["t"] < cut or "-" in r["version"] or r["version"].split(".")[0] != rel[i - 1]["version"].split(".")[0]: continue
        need |= deps[r["version"]] - deps[rel[i - 1]["version"]]
    def one(n):
        try:
            ts = (packument(n).get("time") or {}).get("created")
            return n, data._ts(ts) if ts else None
        except LiveError:
            return n, None  # unknown age: the indicator treats it as young, and says so
    with ThreadPoolExecutor(4) as ex: got = list(ex.map(one, sorted(need)[:limit]))
    return {n: t for n, t in got if t}


def load(pkg, as_of=None):
    """Returns (releases, dependencies, dep_ages, as_of, meta). as_of=None means now; a past cutoff replays the registry rows seen then."""
    doc = packument(pkg)
    rel, dep = rows(pkg, doc)
    if not rel: raise LiveError("the registry has no published versions for this package")
    total, as_of = len(rel), as_of or datetime.utcnow()
    rel = [r for r in rel if r["t"] <= as_of]
    if not rel: raise LiveError("the package had no releases before that cutoff")
    keep = {r["version"] for r in rel}; dep = [d for d in dep if d["version"] in keep]
    meta = dict(latest=(doc.get("dist-tags") or {}).get("latest"), versions_on_registry=total, versions_used=len(rel),
                first_release=rel[0]["t"].isoformat(timespec="minutes"), last_release=rel[-1]["t"].isoformat(timespec="minutes"))
    return rel, dep, dep_ages_for(rel, dep, as_of), as_of, meta
