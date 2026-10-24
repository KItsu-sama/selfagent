"""Built-in tools + plugin loader. NOTE: shell/pip run on your machine: use a VM/container for real 24/7."""
import subprocess, sys, re, html, importlib.util, urllib.request, urllib.parse
from core import state
from core.state import ROOT

DEPS = ROOT / ".deps"
DEPS.mkdir(exist_ok=True)
if str(DEPS) not in sys.path:
    sys.path.insert(0, str(DEPS))
UA = {"User-Agent": "Mozilla/5.0 selfagent/0.1"}


def _path(p):
    full = (ROOT / p).resolve()
    if full != ROOT and ROOT not in full.parents:
        raise ValueError("path outside project")
    return full


def protected_paths():
    return [x.strip().strip("/") for x in state.criteria().get("protected", "").split(",") if x.strip()]


def _writable(p):
    full = _path(p)
    rel = full.relative_to(ROOT).as_posix()
    for x in protected_paths():
        if rel == x or rel.startswith(x + "/"):
            raise ValueError(f"'{x}' is protected (edit 'protected:' in CRITERIA.md to change)")
    return full


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


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
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=180)
    return f"exit={r.returncode}\n{(r.stdout + r.stderr)[-3000:]}"


def read_file(path):
    return _path(path).read_text(encoding="utf-8", errors="replace")[:8000]


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
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in _path(path).iterdir()
                            if x.name not in (".git", ".cache", ".deps", "__pycache__")))


def pip_install(package):
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\]=<>~]+", package):
        raise ValueError("bad package spec")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(DEPS), package],
                       capture_output=True, text=True, timeout=600)
    return f"exit={r.returncode}\n{(r.stdout + r.stderr)[-1500:]}"


BUILTIN = {
    "web_search": (web_search, "web_search(query) - search the web, returns titles+links"),
    "fetch": (fetch, "fetch(url) - page text (first 6000 chars)"),
    "shell": (shell, "shell(cmd) - run a shell command in the project dir"),
    "read_file": (read_file, "read_file(path)"),
    "write_file": (write_file, "write_file(path, content) - create/overwrite a file"),
    "str_replace": (str_replace, "str_replace(path, old, new) - change one exact, unique piece of a file (prefer over write_file for edits)"),
    "list_dir": (list_dir, "list_dir(path='.')"),
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
