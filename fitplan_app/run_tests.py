"""Minimal runner for environments without pytest: python run_tests.py"""
import importlib, sys, traceback
sys.path.insert(0, ".")
failed = 0
for modname in sys.argv[1:] or ["tests.test_app"]:
    mod = importlib.import_module(modname)
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, name)(); print("PASS", name)
        except Exception:
            failed += 1; print("FAIL", name); traceback.print_exc()
sys.exit(1 if failed else 0)
