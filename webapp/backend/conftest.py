"""Make the backend package importable from tests without packaging it."""

import os
import sys
from pathlib import Path

# The injection/recovery run route is registered only when an operator exports
# ASTRONOMY_ENABLE_RUNNER=1 (app.py computes RUNNER_ENABLED at import time).
# Tests exercise that route, so the suite opts in here — a plain `pytest`
# invocation must not depend on the caller's shell environment. The unset
# default (read-only API) is a deployment property and is documented in
# README §12; test_research_experiment.py covers the route's behavior once
# enabled.
os.environ.setdefault("ASTRONOMY_ENABLE_RUNNER", "1")

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
