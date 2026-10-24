import subprocess
from core.state import ROOT


def git(*a, check=True):
    r = subprocess.run(["git", "-c", "user.name=selfagent", "-c", "user.email=selfagent@local", *a],
                       cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout.strip()


def commit_all(msg):
    git("add", "-A")
    git("commit", "-m", msg, "--allow-empty")


def ensure():
    """Make sure we are in a repo on a base branch (never on a leftover agent/* branch)."""
    if not (ROOT / ".git").exists():
        git("init")
        git("symbolic-ref", "HEAD", "refs/heads/main")
        commit_all("init")
    br = git("rev-parse", "--abbrev-ref", "HEAD")
    if br.startswith("agent/"):
        git("checkout", "-f", "main")
        br = "main"
    return br


def changed_files(a, b):
    return [x for x in git("diff", "--name-only", f"{a}..{b}").splitlines() if x]
