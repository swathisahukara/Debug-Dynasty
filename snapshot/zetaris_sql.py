"""Run one Lightning SQL statement through the Zetaris REST API (reads .env).
Usage: python3 snapshot/zetaris_sql.py "SELECT 1"     or     python3 snapshot/zetaris_sql.py -f file.sql
With -f, statements are split on ';' and run one at a time.
"""
import json, os, sys, urllib.request, uuid
from pathlib import Path


def load_env():
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def run(sql, limit=1000):
    body = json.dumps({"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit}).encode()
    req = urllib.request.Request(os.environ["ZETARIS_REST_URL"] + "/sql-editor/sqls/run", data=body, method="POST", headers={
        "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"], "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
        "X-Request-ID": str(uuid.uuid4()), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:2000]}


if __name__ == "__main__":
    load_env()
    if sys.argv[1] == "-f":
        stmts = [s.strip() for s in Path(sys.argv[2]).read_text().split(";") if s.strip()]
    else:
        stmts = [sys.argv[1]]
    for s in stmts:
        print(">>", s[:120].replace("\n", " "))
        res = run(s)
        if "headers" in res:
            print("\t".join(res["headers"]))
            for row in res.get("data", []):
                print("\t".join("" if c is None else str(c) for c in row))
            print(f"({res.get('total', len(res.get('data', [])))} rows, {res.get('timeUsed')} ms)")
        else:
            print(json.dumps(res, indent=1)[:2000])
