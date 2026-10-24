"""Free-API router: tries providers in health order, cools down failures, caches answers."""
import json, os, time, hashlib, random, urllib.request
from core.state import ROOT

CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)
HEALTH = CACHE / "health.json"


class Router:
    def __init__(self):
        self.providers = json.loads((ROOT / "providers.json").read_text())["providers"]
        self.health = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
        self.mock = os.getenv("AGENT_MOCK") == "1"

    def _h(self, k):
        return self.health.setdefault(k, {"ok": 0, "fail": 0, "cool_until": 0, "lat": 0})

    def _save(self):
        HEALTH.write_text(json.dumps(self.health))

    def _get_key(self, p):
        key_env = p["key_env"]
        # If it's directly a key (not just env var name), use it
        if key_env and (key_env.startswith("sk-") or key_env.startswith("gsk_") or 
                        key_env.startswith("xai-") or len(key_env) > 40 and not key_env.isupper() and "_" not in key_env[:10]):
            return key_env
        # Otherwise look up as env var
        v = os.getenv(key_env)
        if v:
            return v
        # Also try common env var names
        name = p["name"].upper()
        for cand in [f"{name}_API_KEY", f"{name}_KEY"]:
            v = os.getenv(cand)
            if v:
                return v
        return None

    def candidates(self):
        now, out = time.time(), []
        for p in self.providers:
            key = self._get_key(p)
            if not key:
                continue
            for m in p["models"]:
                k = f'{p["name"]}/{m}'
                h = self._h(k)
                if h["cool_until"] > now:
                    continue
                score = (h["ok"] + 1) / (h["ok"] + h["fail"] + 2) + random.random() * 0.05
                out.append((score, p, m, k, key))
        out.sort(key=lambda x: -x[0])
        return out

    def _call(self, p, m, messages, key):
        body = json.dumps({"model": m, "messages": messages, "temperature": 0.2}).encode()
        req = urllib.request.Request(
            p["base_url"].rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "User-Agent": "selfagent/0.1",
                     "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    def chat(self, messages, stage="chat", cache=True, validate=None):
        if self.mock:
            from core import mock
            return mock.reply(stage, messages)
        key = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        cf = CACHE / f"{key}.txt"
        if cache and cf.exists():
            return cf.read_text(encoding="utf-8")
        cands = self.candidates()
        if not cands:
            raise RuntimeError("No usable provider: set at least one API key (see .env.example) "
                               "or all providers are cooling down.")
        errors = []
        for _, p, m, k, key in cands:
            h, t = self._h(k), time.time()
            try:
                text = self._call(p, m, messages, key)
                if not text or not text.strip():
                    raise ValueError("empty reply")
                if validate:
                    validate(text)
                h["ok"] += 1
                h["lat"] = round(time.time() - t, 2)
                self._save()
                if cache:
                    cf.write_text(text, encoding="utf-8")
                return text
            except Exception as e:
                h["fail"] += 1
                h["cool_until"] = time.time() + (300 if "429" in str(e) else 60)
                self._save()
                errors.append(f"{k}: {e}")
        raise RuntimeError("all providers failed:\n" + "\n".join(errors[-5:]))
