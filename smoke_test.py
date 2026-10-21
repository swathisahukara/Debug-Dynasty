import os, uuid, requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
results = []

def check(name, fn):
    try:
        fn(); results.append(("PASS", name, ""))
    except Exception as e:
        results.append(("FAIL", name, str(e)[:150]))

def zetaris_web():
    requests.get("http://localhost:3000", timeout=10).raise_for_status()

def zetaris_sql():
    r = requests.post(
        os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
        headers={"Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"],
                 "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
                 "X-Request-ID": str(uuid.uuid4())},
        json={"queryId": str(uuid.uuid4()), "sql": "SELECT 1", "source": "SqlEditor", "limit": 1},
        timeout=60)
    r.raise_for_status()
    data = r.json().get("data")
    assert data and str(data[0][0]) == "1", "unexpected reply: " + r.text[:80]

def nemotron():
    client = OpenAI(base_url=os.environ["METERLESS_BASE_URL"],
                    api_key=os.environ["METERLESS_RUNTIME_TOKEN"],
                    default_headers={"meterless-app": "paper-trail", "meterless-scope": "user"})
    reply = client.chat.completions.create(
        model=os.environ["NEMOTRON_MODEL"],
        messages=[{"role": "user", "content": "Reply with the single word: ready"}])
    assert reply.choices, "no reply from the model"

check("Data: Zetaris web interface", zetaris_web)
check("Data: Zetaris runs SQL over REST", zetaris_sql)
check("Power: Nemotron via Nightshift", nemotron)
for s, n, d in results:
    print(s, n, d)