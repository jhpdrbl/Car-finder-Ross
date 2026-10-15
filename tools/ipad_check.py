"""Quick check of what works in this terminal (made for a-Shell on the iPad). Takes about a minute.

    python tools/ipad_check.py

Each test runs with a time limit, so a test that hangs is reported as HUNG instead of freezing.
Screenshot the results for Claude.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

URL = "https://www.mckennaaudi.com/robots.txt"     # a dealer site that answers quickly
URL2 = "https://www.subaru.com/robots.txt"
LIMIT = 45


def run(name: str, fn, in_thread: bool) -> None:
    out: dict = {}

    def body():
        t = time.monotonic()
        try:
            out["ok"] = f"{fn()} in {time.monotonic() - t:.1f}s"
        except Exception as e:  # report and keep going
            out["err"] = f"{type(e).__name__}: {str(e)[:120]}"

    if in_thread:
        th = threading.Thread(target=body, daemon=True)
        th.start()
        th.join(LIMIT)
    else:
        body()
    res = out.get("ok") and f"OK   {out['ok']}" or (f"ERROR {out['err']}" if "err" in out else f"HUNG (no answer in {LIMIT}s)")
    print(f"{name:52} {res}", flush=True)


def main() -> None:
    import requests
    print(f"Python {sys.version.split()[0]} on {sys.platform}", flush=True)

    run("1. plain web request", lambda: requests.get(URL, timeout=30).status_code, False)
    run("2. plain web request in a background thread", lambda: requests.get(URL, timeout=30).status_code, True)

    import requests_cache
    folder = Path(__file__).resolve().parent.parent / ".cache"
    folder.mkdir(exist_ok=True)

    def cached(backend: str):
        s = requests_cache.CachedSession(str(folder / f"check_{backend}"), backend=backend, expire_after=60)
        return lambda: s.get(URL2, timeout=30).status_code

    run("3. page memory (sqlite)", cached("sqlite"), False)
    run("4. page memory (sqlite) in a background thread", cached("sqlite"), True)

    s = requests_cache.CachedSession(str(folder / "check_many"), backend="sqlite", expire_after=60)

    def many():
        errs, threads = [], []
        for u in (URL, URL2, "https://www.genesis.com/robots.txt", "https://www.lexus.com/robots.txt"):
            def one(u=u):
                try:
                    s.get(u, timeout=30)
                except Exception as e:
                    errs.append(type(e).__name__)
            threads.append(threading.Thread(target=one, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(LIMIT)
        alive = sum(t.is_alive() for t in threads)
        if alive:
            raise RuntimeError(f"{alive} of 4 still stuck")
        return f"4 at once, errors: {errs or 'none'}"

    run("5. page memory (sqlite), 4 threads at once", many, True)
    run("6. page memory (filesystem) in a background thread", cached("filesystem"), True)
    run("7. page memory (in memory) in a background thread", cached("memory"), True)
    print("Done. Screenshot this for Claude.", flush=True)


if __name__ == "__main__":
    main()
