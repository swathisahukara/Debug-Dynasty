"""OpenAI-compatible chat client for NVIDIA Nemotron via Meterless Nightshift (stdlib only) + cost meter + run log."""
import json, os, re, time, urllib.request, urllib.error
from . import config as C

METER = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "seconds": 0.0}


def reset_meter():
    for k in METER: METER[k] = 0 if k != "seconds" else 0.0


def meter_snapshot():
    m = dict(METER)
    m["est_usd"] = round(m["tokens_in"] / 1e6 * C.USD_PER_MTOK_IN + m["tokens_out"] / 1e6 * C.USD_PER_MTOK_OUT, 6)
    return m


def extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a = text.find("{")
    if a < 0: raise ValueError("no JSON object in model output: " + text[:200])
    obj, _ = json.JSONDecoder().raw_decode(text[a:])  # tolerates trailing text after the JSON object
    return obj


def _mock(role, messages):
    user = messages[-1]["content"]
    ev = json.loads(user.split("EVIDENCE:", 1)[1].split("\nENDEVIDENCE", 1)[0]) if "EVIDENCE:" in user else {}
    hits = ev.get("indicator_hits", [])
    if role == "planner": return {"focus": [h["id"] for h in hits], "hypotheses": ["mock hypothesis"]}
    if role == "skeptic":
        return {"assessments": [{"hit": h["id"], "benign_explanations": ["mock"], "keep": True, "citations": [h["row"]]} for h in hits]}
    return {"risk_level": "medium" if hits else "low", "summary": "mock report",
            "indicators": [{"hit": h["id"], "why": "mock", "rows": [h["row"]]} for h in hits]}


def chat_json(role, system, user, max_tokens=int(os.environ.get('LLM_MAX_TOKENS', '3500'))):
    """Returns (parsed_json, raw_text). Retries once on transport or JSON failure."""
    prefix = "/no_think\n" if os.environ.get("LLM_NO_THINK", "1") == "1" else ""
    msgs = [{"role": "system", "content": prefix + system}, {"role": "user", "content": user}]
    if C.LLM_MOCK:
        out = _mock(role, msgs); METER["calls"] += 1; METER["tokens_in"] += len(user) // 4; METER["tokens_out"] += 100
        return out, json.dumps(out)
    body = json.dumps({"model": os.environ["NEMOTRON_MODEL"], "messages": msgs, "temperature": 0.2, "max_tokens": max_tokens, **json.loads(os.environ.get("LLM_EXTRA", "{}"))}).encode()
    headers = {"Authorization": "Bearer " + os.environ["METERLESS_RUNTIME_TOKEN"], "Content-Type": "application/json",
               "meterless-app": os.environ.get("METERLESS_APP", "package-trail"), "meterless-scope": "user"}
    url = os.environ["METERLESS_BASE_URL"].rstrip("/") + "/chat/completions"
    last = None
    for attempt in range(4):
        t0 = time.time(); print(f'  [{role}] calling model (attempt {attempt + 1})...', flush=True)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method="POST"), timeout=int(os.environ.get('LLM_TIMEOUT','150'))) as r:
                d = json.load(r)
            METER["calls"] += 1; METER["seconds"] += time.time() - t0
            u = d.get("usage") or {}
            METER["tokens_in"] += u.get("prompt_tokens", 0); METER["tokens_out"] += u.get("completion_tokens", 0)
            m = d["choices"][0]["message"]; raw = m.get("content") or ""
            if "{" not in raw: raw = raw + (m.get("reasoning_content") or "")
            print(f'  [{role}] done in {time.time() - t0:.1f}s, tokens in/out {u.get("prompt_tokens")}/{u.get("completion_tokens")}', flush=True)
            return extract_json(raw), raw
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:300]}"
            if e.code < 500 and e.code != 429: break
            wait = 20 if e.code == 429 else 2
            print(f"  [{role}] provider error {e.code}, retrying in {wait}s", flush=True); time.sleep(wait)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:  # includes timeouts
            last = repr(e)
    raise RuntimeError(f"LLM call failed for {role}: {last}")
