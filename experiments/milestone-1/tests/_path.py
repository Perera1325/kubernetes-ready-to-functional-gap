import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("application", "fault-injector", "transaction-client", "collector", "harness"):
    sys.path.insert(0, os.path.join(ROOT, d))
