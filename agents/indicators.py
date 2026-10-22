"""Deterministic risk indicators over a package timeline. Uses only rows at or before as_of; never the removed flag."""
import collections

line = lambda v: ".".join(v.split("-")[0].split(".")[:2])


def compute(rel, dep, dep_ages=None, young_days=90):
    if dep_ages is None:
        from . import data; dep_ages = data.dep_ages()
    deps = collections.defaultdict(set)
    for d in dep: deps[d["version"]].add(d["dependency"])
    hits, seen = [], {}
    for i, r in enumerate(rel):
        prev = rel[i - 1] if i else None
        pub = r.get("publisher") or ""
        if pub and pub not in seen and prev and (r["t"] - prev["t"]).days > 180:
            hits.append(dict(indicator="new_publisher_gap", version=r["version"], detail=f"publisher first seen after {(r['t'] - prev['t']).days} days without a release"))
        if pub: seen.setdefault(pub, r["t"])
        win = [x for x in rel if 0 <= (x["t"] - r["t"]).total_seconds() <= 600]
        if len({line(x["version"]) for x in win}) >= 3 and (not prev or (r["t"] - prev["t"]).total_seconds() > 600):
            hits.append(dict(indicator="release_burst", version=r["version"], detail=f"{len(win)} releases across {len({line(x['version']) for x in win})} release lines within 10 minutes"))
        if prev and r.get("install_scripts") and not prev.get("install_scripts"):
            hits.append(dict(indicator="install_script_added", version=r["version"], detail=f"install-time script appears: {r['install_scripts']}"))
        if prev and "-" not in r["version"] and r["version"].split(".")[0] == prev["version"].split(".")[0]:
            new = deps[r["version"]] - deps[prev["version"]]
            if new and deps[r["version"]]:
                age = lambda n: (r["t"] - dep_ages[n]).days if n in dep_ages else None  # None = unknown age
                young = sorted(n for n in new if age(n) is None or age(n) < young_days)
                if young:
                    ages = [age(n) for n in young]
                    known = [x for x in ages if x is not None]
                    hits.append(dict(indicator="new_dependency", version=r["version"], new_deps=young, dep_age_days=ages,
                                     detail=f"{len(young)} new dependencies in a same-major release, newest dependency package is {min(known)} days old" if known else f"{len(young)} new dependencies of unknown age in a same-major release"))
    return hits


def recent(hits, rel, as_of, days):
    t = {r["version"]: r["t"] for r in rel}
    return [h for h in hits if (as_of - t[h["version"]]).total_seconds() <= days * 86400]
