import os, sys
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
for d in ("application", "."):
    sys.path.insert(0, os.path.normpath(os.path.join(ROOT, d)))
