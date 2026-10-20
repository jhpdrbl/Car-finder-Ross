"""Run the whole search from the Windows laptop or an iPad terminal app (a-Shell) and publish it to the phone page.

    python search.py              # get the latest version, run the search, upload the results
    python search.py --no-update  # skip getting the latest version
    python search.py upload       # only upload results from the last search
    python search.py check        # list what an upload would send, without sending it
    python search.py update       # only get the latest version
(`ipad.py` is the old name and still works.)

On the iPad, apps can't run `git` or start other programs, so this does it all in one Python process: it
downloads the project from GitHub (public, no login), runs `run.py refresh` in-process, and uploads
data/ and output/ through GitHub's API with your token (saved in .github_token, never uploaded).
Keep a-Shell open on screen and the iPad from sleeping (Settings > Display & Brightness > Auto-Lock > Never).
On Windows (LAPTOP.md) the same command works without git: it reads every dealer at full speed with the page
cache on disk, and uses the browser add-on (Playwright) when it's installed.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import runpy
import sys
import zipfile
from pathlib import Path

import requests

OWNER, REPO, BRANCH = "jhpdrbl", "Car-finder-Ross", "claude/la-cpo-suv-scraper-x0pl15"
ROOT = Path(__file__).resolve().parent
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TOKEN_FILE = ROOT / ".github_token"
LAPTOP = os.name == "nt"           # Windows laptop; otherwise the iPad (a-Shell)
DEVICE = "laptop" if LAPTOP else "iPad"
UPLOAD_DIRS = ("data", "output")
NEVER_UPLOAD = ("data/cache/", "data/run_state.json")
KEEP_LOCAL = (".venv/", "data/cache/", "logs/", ".github_token", "data/run_state.json")


def say(msg: str) -> None:
    print(msg, flush=True)


# ---- get the latest version ----

def update() -> None:
    """Download the branch as a zip and unpack it over this folder (like `git pull`, results included)."""
    say("Getting the latest version from GitHub ...")
    url = f"https://codeload.github.com/{OWNER}/{REPO}/zip/refs/heads/{BRANCH}"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    n = 0
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for info in z.infolist():
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            if not rel or info.is_dir() or rel.startswith(KEEP_LOCAL):
                continue
            dest, data = ROOT / rel, z.read(info)
            if dest.exists() and dest.read_bytes() == data:
                continue                 # unchanged (also: never rewrite the running scheduled-refresh.bat)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            n += 1
    say(f"  updated {n} files")


# ---- upload results ----

def _clean(t: str) -> str:
    """A key pasted more than once = the same key repeated: keep one."""
    t = "".join(t.split())
    for prefix in ("github_pat_", "ghp_"):
        if t.count(prefix) > 1:
            t = prefix + t.split(prefix)[-1]
    return t


def _key_works(t: str) -> bool | None:
    """True = GitHub accepts the key and it may write to the project; False = it doesn't; None = couldn't ask."""
    try:
        r = requests.get(API, headers={"Authorization": f"Bearer {t}", "Accept": "application/vnd.github+json"}, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code in (401, 403, 404):
        return False
    return bool(r.ok and r.json().get("permissions", {}).get("push")) if r.ok else None


def token() -> str:
    where = ("LAPTOP.md" if LAPTOP else "IPAD.md") + ", step 3"
    for _ in range(3):
        t = os.environ.get("GITHUB_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")
        if not t:
            say(f"To upload results this needs a GitHub key (one time). See {where}.")
            t = input("Paste your GitHub key once and press return: ")   # shown, not hidden (user's choice, Oct 2026)
        t = _clean(t)
        ok = _key_works(t)
        if ok is False:
            say("That key didn't work (wrong, expired, or missing 'Contents: Read and write'). Let's try again.")
            TOKEN_FILE.unlink(missing_ok=True)
            os.environ.pop("GITHUB_TOKEN", None)
            continue
        TOKEN_FILE.write_text(t)
        if ok:
            say(f"GitHub key OK ({t[:15]}...{t[-4:]}). Saved; it won't ask again.")
        return t
    raise SystemExit(f"The key still didn't work. Make a new one ({where}) and run this again.")


def blob_sha(data: bytes) -> str:
    """Git's id for a file's contents, so unchanged files aren't sent again."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def local_files() -> dict[str, bytes]:
    out = {}
    for d in UPLOAD_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and not rel.startswith(NEVER_UPLOAD) and "__pycache__" not in rel:
                out[rel] = p.read_bytes()       # exact bytes, as git stores them
    return out


def changed_files(session: requests.Session) -> tuple[str, str, dict[str, bytes]]:
    head = session.get(f"{API}/git/ref/heads/{BRANCH}", timeout=60).json()["object"]["sha"]
    tree = session.get(f"{API}/git/commits/{head}", timeout=60).json()["tree"]["sha"]
    remote = {e["path"]: e["sha"] for e in
              session.get(f"{API}/git/trees/{tree}?recursive=1", timeout=60).json()["tree"] if e["type"] == "blob"}
    changed = {p: d for p, d in local_files().items() if remote.get(p) != blob_sha(d)}
    return head, tree, changed


def upload(dry_run: bool = False) -> None:
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if not dry_run:
        s.headers["Authorization"] = f"Bearer {token()}"
    for attempt in range(3):
        head, tree, changed = changed_files(s)
        if not changed:
            say("Nothing new to upload.")
            return
        say(f"{len(changed)} changed files: " + ", ".join(sorted(changed)[:8]) + (" ..." if len(changed) > 8 else ""))
        if dry_run:
            return
        entries = []
        for path, data in changed.items():
            r = s.post(f"{API}/git/blobs", json={"content": base64.b64encode(data).decode(), "encoding": "base64"}, timeout=120)
            r.raise_for_status()
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": r.json()["sha"]})
        new_tree = s.post(f"{API}/git/trees", json={"base_tree": tree, "tree": entries}, timeout=120)
        new_tree.raise_for_status()
        commit = s.post(f"{API}/git/commits", timeout=60, json={
            "message": f"Results from {DEVICE} run", "tree": new_tree.json()["sha"], "parents": [head]})
        commit.raise_for_status()
        ref = s.patch(f"{API}/git/refs/heads/{BRANCH}", json={"sha": commit.json()["sha"]}, timeout=60)
        if ref.ok:
            say("Uploaded. Your phone page updates in about 2 minutes.")
            return
        if ref.status_code == 422 and attempt < 2:      # something else was pushed meanwhile: redo on top of it
            say("  the project changed while uploading; trying again ...")
            continue
        if ref.status_code in (401, 403, 404):
            raise SystemExit("Upload refused: the token is wrong or lacks 'Contents: Read and write'. "
                             "Delete .github_token and run again with a new token (" + ("LAPTOP.md" if LAPTOP else "IPAD.md") + ", step 3).")
        ref.raise_for_status()


# ---- the search ----

def search() -> None:
    sys.argv = ["run.py", "refresh"]
    if not LAPTOP:
        # a-Shell: the SQLite page cache deadlocks with many threads (seen Oct 2026), so keep pages in memory,
        # and read fewer dealers at once (each site is still visited at the same polite pace).
        os.environ["CARFINDER_CACHE"] = "memory"
        sys.argv += ["--workers", "12"]
    try:
        runpy.run_path(str(ROOT / "run.py"), run_name="__main__")
    except SystemExit as e:              # run.py finishing normally shouldn't stop the upload
        if e.code not in (None, 0):
            raise


def main() -> None:
    os.chdir(ROOT)
    args = sys.argv[1:]
    if args[:1] == ["upload"]:
        return upload()
    if args[:1] == ["check"]:
        return upload(dry_run=True)
    if args[:1] == ["update"]:
        return update()
    token()            # ask for the GitHub key now (first run only), not after a 20-minute search
    if "--no-update" not in args:
        update()
        if LAPTOP:         # pick up any new libraries the latest version needs (a-Shell can't start pip from here)
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    search()
    upload()


if __name__ == "__main__":
    main()
