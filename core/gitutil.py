import subprocess
from core.state import ROOT

# Runtime/chat folders are never part of "the code": ignore them for cleanliness checks and commits,
# even if the owner's .gitignore forgot them.
EXCLUDE = (":(exclude)workspace", ":(exclude).selfagent")


class DirtyTree(RuntimeError):
    """The working tree has the owner's uncommitted changes; the agent must wait, not retry-burn."""


def git(*a, check=True):
    r = subprocess.run(["git", "-c", "user.name=selfagent", "-c", "user.email=selfagent@local", *a],
                       cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout.strip()


def commit_all(msg):
    git("add", "-A")
    # Un-stage runtime/chat folders in case the owner's .gitignore does not cover them. (A pathspec
    # exclude on add errors out when the excluded folder is already ignored, so reset afterwards.)
    git("reset", "-q", "--", "workspace", ".selfagent", check=False)
    git("commit", "-m", msg, "--allow-empty")


def base_branch():
    """main if it exists, else master, else whatever is checked out (no hard-coded 'main')."""
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False):
            return name
    return git("rev-parse", "--abbrev-ref", "HEAD")


def abandon_branch(base, branch):
    """Throw away a half-finished agent branch and everything it left in the tree."""
    git("checkout", "-f", base, check=False)
    git("clean", "-fd", "-e", "workspace", "-e", ".selfagent", check=False)
    git("branch", "-D", branch, check=False)


def ensure():
    """Make sure we are in a repo on the base branch; recover from a crashed run's leftovers."""
    if not (ROOT / ".git").exists():
        git("init")
        git("symbolic-ref", "HEAD", "refs/heads/main")
        commit_all("init")
    br = git("rev-parse", "--abbrev-ref", "HEAD")
    if br.startswith("agent/"):
        base = base_branch()
        abandon_branch(base, br)
        br = base
    for stale in git("branch", "--list", "agent/*", "--format=%(refname:short)").splitlines():
        git("branch", "-D", stale.strip(), check=False)
    return br


def ensure_clean():
    """Refuse autonomous work if the repository already contains the owner's local changes."""
    status = git("status", "--porcelain", "--", ".", *EXCLUDE)
    if status:
        preview = "\n".join(status.splitlines()[:12])
        raise DirtyTree(
            "Repository has local changes. Waiting (commit or stash them) before any autonomous upgrade, "
            "to protect your work:\n" + preview
        )


def changed_files(a, b):
    return [x for x in git("diff", "--name-only", f"{a}..{b}").splitlines() if x]
