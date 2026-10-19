"""Old name of search.py, kept so `python ipad.py` still works on devices set up before Oct 19 2026."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "search.py"), run_name="__main__")
