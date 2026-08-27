import os
import sys

# Ensure src/ is on sys.path so tests can import the package without installing it.
ROOT = os.path.dirname(os.path.dirname(__file__))
src = os.path.join(ROOT, "src")
if src not in sys.path:
    sys.path.insert(0, src)
