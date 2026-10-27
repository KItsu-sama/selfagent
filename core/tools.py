"""Built-in tools + plugin loader. NOTE: shell/pip run on your machine: use a VM/container for real 24/7."""
import subprocess, sys, re, html, os, socket, ipaddress, importlib.util, urllib.request, urllib.parse
from core import state, memory
from core.state import ROOT

DEPS = ROOT / ".deps"
DEPS.mkdir(exist_ok=True)
if str(DEPS) not in sys.path:
    sys.path.insert(0, str(DEPS))
UA = {"User-Agent": "Mozilla/5.0 selfagent/0.1"}


WORKSPACE = ROOT / "workspace"  # the only place the chat UI may write; git-ignored, never executed

# Secrets and runtime state: no agent tool may read or write these (not configurable on purpose).
SENSITIVE = (".git", ".env", ".selfagent", ".cache", ".deps", "providers.json")
# The code that enforces the limits below. Merged with 'protected:' from CRITERIA.md, so the agent
# cannot loosen its own sandbox. Edit this tuple (by hand) if you really want it to modify them.
DEFAULT_PROTECTED = (".git", "bench", "CRITERIA.md", "core/improve.py", "core/tools.py",
                     "core/router.py", "core/gitutil.py")


def _path(p, base=None):
    base = base or ROOT
    full = (base / p).resolve()
    if full != base and base not in full.parents:
        raise ValueError("path outside allowed folder")
    return full


def _is_sensitive(rel):
    first = rel.split("/")[0]
    return first in SENSITIVE or (first.startswith(".env") and first != ".env.example")


def protected_paths():
    cfg = [x.strip().strip("/") for x in state.criteria().get("protected", "").split(",") if x.strip()]
    return sorted(set(cfg) | set(DEFAULT_PROTECTED) | set(SENSITIVE))


def _readable(p):
    full = _path(p)
    rel = full.relative_to(ROOT).as_posix()
    if rel != "." and _is_sensitive(rel):
        raise ValueError(f"'{rel.split('/')[0]}' holds secrets or runtime state and cannot be read by agent tools")
    return full


def _writable(p):
    full = _path(p)
    rel = full.relative_to(ROOT).as_posix()
    if _is_sensitive(rel):
        raise ValueError(f"'{rel.split('/')[0]}' holds secrets or runtime state and cannot be written by agent tools")
    for x in protected_paths():
        if rel == x or rel.startswith(x + "/"):
            raise ValueError(f"'{x}' is protected (edit 'protected:' in CRITERIA.md to change)")
    return full


def _check_url(url):
    """http(s) only, and only public addresses (blocks file://, localhost, LAN, cloud-metadata IPs)."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are allowed")
    if not u.hostname:
        raise ValueError("URL has no host")
    if os.getenv("SELFAGENT_ALLOW_PRIVATE_URLS") == "1":
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {exc}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError(f"blocked non-public address {ip}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)  # a public page must not bounce us to an internal one
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url):
    _check_url(url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.build_opener(_SafeRedirect).open(req, timeout=30) as r:
        return r.read(2_000_000).decode("utf-8", "replace")


def _strip(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def web_search(query):
    page = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query))
    out = []
    for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href, title = m.groups()
        link = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        out.append(f"{_strip(title)} - {link}")
        if len(out) >= 6:
            break
    return "\n".join(out) or "no results"


def fetch(url):
    return _strip(_get(url))[:6000]


def shell(cmd):
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=180,
                       stdin=subprocess.DEVNULL)  # no stdin: interactive prompts fail fast instead of hanging
    return f"exit={r.returncode}\n{(r.stdout + r.stderr)[-3000:]}"


def read_file(path):
    return _readable(path).read_text(encoding="utf-8", errors="replace")[:8000]


def write_file(path, content):
    p = _writable(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {path} ({len(content)} chars)"


def str_replace(path, old, new):
    p = _writable(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"old text must appear exactly once (found {text.count(old)})")
    p.write_text(text.replace(old, new), encoding="utf-8")
    return f"edited {path}"


def list_dir(path="."):
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in _readable(path).iterdir()
                            if not _is_sensitive(x.name) and x.name != "__pycache__"))


def pip_install(package):
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\]=<>~]+", package):
        raise ValueError("bad package spec")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(DEPS), package],
                       capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    return f"exit={r.returncode}\n{(r.stdout + r.stderr)[-1500:]}"


def remember(key, content, tags=""):
    """remember(key, content, tags='') - explicitly save a durable fact or project note locally"""
    return memory.remember(key, content, tags)


def search_memory(query="", limit=5):
    """search_memory(query, limit=5) - retrieve relevant saved local memories"""
    matches = memory.search(query, limit)
    if not matches:
        return "No matching saved memories."
    return "\n".join(
        f"- {m['memory_key']}: {m['content']}" + (f" [tags: {m['tags']}]" if m["tags"] else "")
        for m in matches
    )


def forget_memory(key):
    """forget_memory(key) - delete a saved memory by its exact key"""
    return memory.forget(key)


# ---- chat-only variants: read the project (minus secrets) but write ONLY inside workspace/ ----
def _ws(p):
    WORKSPACE.mkdir(exist_ok=True)
    return _path(p, WORKSPACE)


def ws_write_file(path, content):
    p = _ws(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote workspace/{p.relative_to(WORKSPACE).as_posix()} ({len(content)} chars)"


def ws_str_replace(path, old, new):
    p = _ws(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"old text must appear exactly once (found {text.count(old)})")
    p.write_text(text.replace(old, new), encoding="utf-8")
    return f"edited workspace/{p.relative_to(WORKSPACE).as_posix()}"


def ws_read_file(path):
    try:
        p = _ws(path)
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except ValueError:
        pass
    return read_file(path)  # falls back to project files; secrets stay blocked


def ws_list_dir(path="."):
    p = _ws(path)
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) or "(empty)"


CHAT_TOOLS = {
    "read_file": (ws_read_file, "read_file(path) - read a file from workspace/ (or a project file, secrets excluded)"),
    "write_file": (ws_write_file, "write_file(path, content) - create/overwrite a file inside workspace/ (paths are relative to workspace/)"),
    "str_replace": (ws_str_replace, "str_replace(path, old, new) - edit one exact, unique piece of a file inside workspace/"),
    "list_dir": (ws_list_dir, "list_dir(path='.') - list a folder inside workspace/"),
}


BUILTIN = {
    "web_search": (web_search, "web_search(query) - search the web, returns titles+links"),
    "fetch": (fetch, "fetch(url) - page text (first 6000 chars)"),
    "shell": (shell, "shell(cmd) - run a shell command in the project dir"),
    "read_file": (read_file, "read_file(path)"),
    "write_file": (write_file, "write_file(path, content) - create/overwrite a file"),
    "str_replace": (str_replace, "str_replace(path, old, new) - change one exact, unique piece of a file (prefer over write_file for edits)"),
    "list_dir": (list_dir, "list_dir(path='.')"),
    "remember": (remember, "remember(key, content, tags='') - save a durable memory"),
    "search_memory": (search_memory, "search_memory(query, limit=5) - retrieve saved memories"),
    "forget_memory": (forget_memory, "forget_memory(key) - delete a saved memory by exact key"),
    "pip_install": (pip_install, "pip_install(package) - install into .deps/"),
}


def load_plugins(errors=None):
    out = {}
    for f in sorted((ROOT / "plugins").glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location("plugin_" + f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            out[mod.NAME] = {"fn": mod.run, "desc": mod.DESCRIPTION, "mod": mod, "file": f.name}
        except Exception as e:
            if errors is not None:
                errors.append((f.name, e))
            else:
                print(f"[plugin {f.name} skipped: {e}]", file=sys.stderr)
    return out


def all_tools():
    tools = {k: v[0] for k, v in BUILTIN.items()}
    docs = {k: v[1] for k, v in BUILTIN.items()}
    for n, p in load_plugins().items():
        tools[n], docs[n] = p["fn"], p["desc"]
    return tools, docs
