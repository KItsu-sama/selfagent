"""Replaceable upstream provider catalog adapter.

The upstream list is discovery metadata only. Nothing is downloaded at import time,
and provider credentials are always read from environment variables by Router.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

from core.state import ROOT

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/mnfst/awesome-free-llm-apis/main/README.md"
)
CATALOG_PATH = ROOT / ".selfagent" / "providers.catalog.json"
CONFIG_PATH = ROOT / "providers.json"  # intentionally local/ignored; preserve user config


def parse_catalog(markdown):
    """Parse provider headings, Base URL lines, and model tables from the upstream README."""
    providers = []
    current = None
    in_model_table = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            name = heading.group(1).strip()
            if name.lower() in {"provider apis", "inference providers", "glossary"}:
                current = None
                in_model_table = False
                continue
            current = {"name": name, "base_url": "", "models": []}
            providers.append(current)
            in_model_table = False
            continue

        if current is None:
            continue

        base = re.match(r"^Base URL:\s*(\S+)", line, flags=re.IGNORECASE)
        if base:
            current["base_url"] = base.group(1).strip().rstrip("/")
            continue

        if re.search(r"\|\s*Model Name\s*\|", line, flags=re.IGNORECASE):
            in_model_table = True
            continue

        if in_model_table:
            if not line.startswith("|"):
                in_model_table = False
                continue
            if re.match(r"^\|\s*:?-{2,}", line):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells:
                continue
            model_cell = cells[0]
            if not model_cell or model_cell.lower() == "model name":
                continue
            if model_cell.startswith("+") or "more models" in model_cell.lower():
                continue
            # Model names may be code-formatted or plain text.
            names = re.findall(r"\x60([^\x60]+)\x60", model_cell)
            model = names[0].strip() if names else model_cell.strip()
            if model and model not in current["models"]:
                current["models"].append(model)

    return [
        p for p in providers
        if p["name"] and p["base_url"] and p["models"]
    ]


def _source_url():
    return os.getenv("SELFAGENT_PROVIDER_CATALOG_URL", DEFAULT_SOURCE).strip()


def pull_catalog(timeout=20):
    """Fetch the upstream README and save parsed metadata locally."""
    source = _source_url()
    request = urllib.request.Request(
        source,
        headers={"User-Agent": "selfagent-provider-catalog/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        markdown = response.read().decode("utf-8", errors="replace")
    providers = parse_catalog(markdown)
    if not providers:
        raise RuntimeError(
            "No providers parsed from the catalog. The upstream README format may have changed."
        )
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
    }
    CATALOG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def load_catalog():
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(
            "Provider catalog not found. Run: python run.py providers pull"
        )
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _normalise_base_url(provider):
    """Adapt known OpenAI-compatible base URL variants to Router's /chat/completions path."""
    url = provider["base_url"].rstrip("/")
    name = provider["name"].lower()
    # Google's OpenAI-compatible endpoint lives below the /openai path.
    if "generativelanguage.googleapis.com" in url and not url.endswith("/openai"):
        url += "/openai"
    # These APIs need provider-specific request formats; Router intentionally does not emulate them.
    if "api.cohere.com/v2" in url:
        raise ValueError("Cohere v2 uses a different request format and is not enabled by this adapter.")
    if "/client/v4/accounts/" in url and "cloudflare" in name:
        raise ValueError("Cloudflare Workers AI uses a different endpoint shape and is not enabled by this adapter.")
    return url


def enable_provider(name, model, key_env):
    """Add one selected catalog model to local providers.json; never copies an API key."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env or ""):
        raise ValueError("key_env must be an environment-variable name, e.g. GROQ_API_KEY")
    catalog = load_catalog()
    provider = next(
        (p for p in catalog["providers"] if p["name"].casefold() == name.casefold()),
        None,
    )
    if provider is None:
        raise ValueError(f"Provider '{name}' not found. Run 'python run.py providers list'.")
    if model not in provider["models"]:
        raise ValueError(
            f"Model '{model}' is not listed for {provider['name']}. "
            "Choose an exact model name from 'python run.py providers list --provider ...'."
        )

    base_url = _normalise_base_url(provider)
    config = {"providers": []}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("providers"), list):
            raise ValueError("providers.json must contain a top-level 'providers' list.")
    entries = config["providers"]
    # A provider entry is replaceable by name, while unrelated local entries are preserved.
    entries[:] = [p for p in entries if p.get("name", "").casefold() != provider["name"].casefold()]
    entries.append({
        "name": provider["name"],
        "base_url": base_url,
        "key_env": key_env,
        "models": [model],
    })
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return f"Enabled {provider['name']} / {model} in local providers.json using {key_env}."


def disable_provider(name):
    if not CONFIG_PATH.exists():
        return "No local providers.json found; nothing to remove."
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    entries = config.get("providers", [])
    kept = [p for p in entries if p.get("name", "").casefold() != name.casefold()]
    if len(kept) == len(entries):
        return f"Provider '{name}' was not enabled."
    config["providers"] = kept
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return f"Removed {name} from local providers.json."


def list_catalog(provider_filter=None):
    catalog = load_catalog()
    providers = catalog["providers"]
    if provider_filter:
        providers = [
            p for p in providers
            if provider_filter.casefold() in p["name"].casefold()
        ]
    lines = [f"Catalog source: {catalog.get('source', DEFAULT_SOURCE)}",
             f"Updated: {catalog.get('updated_at', 'unknown')}", ""]
    for provider in providers:
        lines.append(f"{provider['name']} — {provider['base_url']}")
        lines.extend(f"  - {model}" for model in provider["models"])
    if not providers:
        lines.append("No matching providers.")
    return "\n".join(lines)
