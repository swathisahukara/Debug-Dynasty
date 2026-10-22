"""Builds the pseudonymized evidence packet the LLM sees. Package, account and dependency names are replaced and
timestamps become hours before the cutoff T0, so the model must judge the data signals, not recall famous incidents."""
import hashlib


def build(pkg, rel, dep, hits, window=25, max_hits=6):
    pk = "pkg-" + hashlib.sha1(pkg.encode()).hexdigest()[:4]
    t0 = rel[-1]["t"]
    hits = sorted(hits, key=lambda h: next(r['t'] for r in rel if r['version'] == h['version']), reverse=True)[:max_hits]  # most recent only
    need = {h["version"] for h in hits}
    shown = [r for i, r in enumerate(rel) if i >= len(rel) - window or r["version"] in need]
    acct, dmap = {}, {}
    a = lambda p: "" if not p else acct.setdefault(p, f"acct-{len(acct) + 1}")
    d_ = lambda n: dmap.setdefault(n, f"dep-{len(dmap) + 1}")
    rowid = {r["version"]: f"R{i + 1}" for i, r in enumerate(shown)}
    deps_by_v = {}
    for d in dep: deps_by_v.setdefault(d["version"], set()).add(d["dependency"])
    pos = {r["version"]: i for i, r in enumerate(rel)}
    def newdeps(r):
        i = pos[r["version"]]
        return sorted(d_(x) for x in (deps_by_v.get(r["version"], set()) - (deps_by_v.get(rel[i - 1]["version"], set()) if i else set())))
    releases = [dict(row=rowid[r["version"]], version=r["version"], hours_before_T0=round((t0 - r["t"]).total_seconds() / 3600, 1),
                     publisher=a(r.get("publisher")), install_scripts=r.get("install_scripts") or "", dep_count=int(r.get("dep_count") or 0),
                     **({"new_dependencies": nd} if (nd := newdeps(r)) and len(deps_by_v.get(r["version"], ())) else {}))
                for r in shown]
    out_hits, rowmap = [], {}
    for n, h in enumerate(sorted(hits, key=lambda h: next(r['t'] for r in rel if r['version'] == h['version']), reverse=True), 1):
        hid = f"H{n}"
        ht = next(r["t"] for r in rel if r["version"] == h["version"])
        item = dict(id=hid, indicator=h["indicator"], row=rowid[h["version"]], hours_before_T0=round((t0 - ht).total_seconds() / 3600, 1), detail=h["detail"])
        if h.get("facts"): item["facts"] = h["facts"]
        if h.get("new_deps"):
            item["new_dependencies"] = [d_(x) for x in h["new_deps"]]
            item["new_dependency_package_age_days"] = h.get("dep_age_days")
        out_hits.append(item)
        rowmap[hid] = (pkg, h["version"])
    row_versions = {x['row']: x['version'] for x in releases}
    return dict(package=pk, T0="cutoff", total_releases_before_T0=len(rel), releases=releases, indicator_hits=out_hits), rowmap
