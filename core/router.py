"""Free-API router with classified failures, provider failover, health and caching."""
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request

from core.state import ROOT

CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)
HEALTH = CACHE / "health.json"


class ProviderHTTPError(RuntimeError):
    def __init__(self, status, detail, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status}: {detail}")


def _safe_error_body(raw):
    """Keep useful provider diagnostics without dumping arbitrarily large responses."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # OpenAI-compatible APIs usually return {"error": {"message": ...}}.
            err = data.get("error", data)
            if isinstance(err, dict):
                detail = err.get("message") or err.get("code") or json.dumps(err)
            else:
                detail = str(err)
            return str(detail)[:700]
    except (ValueError, TypeError):
        pass
    return (raw or "no error body").strip()[:700]


def _cooldown_seconds(exc):
    """Choose a cooldown based on failure class; do not retry bad credentials every turn."""
    if isinstance(exc, ProviderHTTPError):
        if exc.retry_after:
            try:
                return max(1, min(int(exc.retry_after), 3600))
            except (ValueError, TypeError):
                pass
        detail = str(exc).lower()
        if exc.status == 429 or any(word in detail for word in (
            "quota", "rate limit", "rate_limit", "resource exhausted", "too many requests"
        )):
            return 900
        if exc.status in (401, 403):
            return 3600
        if exc.status == 400:
            return 600
        if exc.status >= 500:
            return 60
        return 300
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return 45
    if isinstance(exc, ValueError):
        return 300
    return 60


class Router:
    def __init__(self):
        config_path = ROOT / "providers.json"
        if not config_path.exists():
            raise FileNotFoundError(
                "providers.json is missing. Restore your local provider config or enable a provider "
                "with 'python run.py providers enable ...'."
            )
        self.providers = json.loads(config_path.read_text(encoding="utf-8"))["providers"]
        self.health = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else {}
        self.mock = os.getenv("AGENT_MOCK") == "1"

    def _h(self, k):
        return self.health.setdefault(k, {"ok": 0, "fail": 0, "cool_until": 0, "lat": 0, "last_error": ""})

    def _save(self):
        HEALTH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH.write_text(json.dumps(self.health, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_key(self, p):
        key_env = p.get("key_env", "")
        # Backward compatibility with old configs that stored a key directly.
        if key_env and (key_env.startswith(("sk-", "gsk_", "xai-")) or
                        (len(key_env) > 40 and not key_env.isupper() and "_" not in key_env[:10])):
            return key_env
        v = os.getenv(key_env) if key_env else None
        if v:
            return v
        name = p.get("name", "").upper().replace("-", "_").replace(" ", "_")
        for cand in (f"{name}_API_KEY", f"{name}_KEY"):
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
            for m in p.get("models", []):
                k = f'{p["name"]}/{m}'
                h = self._h(k)
                provider_health = self._h(f'provider:{p["name"]}')
                if h.get("cool_until", 0) > now or provider_health.get("cool_until", 0) > now:
                    continue
                score = (h.get("ok", 0) + 1) / (h.get("ok", 0) + h.get("fail", 0) + 2)
                score += random.random() * 0.05
                out.append((score, p, m, k, key))
        out.sort(key=lambda x: -x[0])
        return out

    def _call(self, p, m, messages, key):
        body = json.dumps({"model": m, "messages": messages, "temperature": 0.2}).encode()
        req = urllib.request.Request(
            p["base_url"].rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "User-Agent": "selfagent/0.1",
                     "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ProviderHTTPError(
                exc.code, _safe_error_body(raw), exc.headers.get("Retry-After")
            ) from None
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("provider response has no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some compatible endpoints return text as content blocks.
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str):
            raise ValueError("provider response has no text message content")
        return content

    def chat(self, messages, stage="chat", cache=True, validate=None):
        if self.mock:
            from core import mock
            return mock.reply(stage, messages)
        cache_key = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        cache_file = CACHE / f"{cache_key}.txt"
        if cache and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        candidates = self.candidates()
        if not candidates:
            raise RuntimeError(
                "No usable provider is currently available. Check configured API keys and models; "
                "providers in cooldown are skipped automatically."
            )
        errors = []
        # Each candidate receives the exact same message history. A provider switch never resets context.
        for _, provider, model, provider_key, api_key in candidates:
            health, started = self._h(provider_key), time.time()
            try:
                answer = self._call(provider, model, messages, api_key)
                if not answer or not answer.strip():
                    raise ValueError("empty reply")
                if validate:
                    validate(answer)
                health["ok"] = health.get("ok", 0) + 1
                health["lat"] = round(time.time() - started, 2)
                health["cool_until"] = 0
                health["last_error"] = ""
                self._save()
                if cache:
                    cache_file.write_text(answer, encoding="utf-8")
                return answer
            except Exception as exc:
                health["fail"] = health.get("fail", 0) + 1
                cooldown_until = time.time() + _cooldown_seconds(exc)
                health["cool_until"] = cooldown_until
                health["last_error"] = str(exc)[:800]
                detail = str(exc).lower()
                if isinstance(exc, ProviderHTTPError) and (
                    exc.status == 429 or any(word in detail for word in (
                        "quota", "resource exhausted", "billing", "credits exhausted"
                    ))
                ):
                    # Quota/rate limits often apply to the whole provider key, not one model.
                    provider_health = self._h(f'provider:{provider["name"]}')
                    provider_health["cool_until"] = cooldown_until
                    provider_health["last_error"] = str(exc)[:800]
                self._save()
                errors.append(f"{provider_key}: {exc}")
        raise RuntimeError(
            "All configured providers failed for this request. The same conversation context "
            "was sent to each candidate. Failed providers have been put into cooldown. Details:\n"
            + "\n".join(errors[-8:])
        )
