import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The services are independent projects with no shared package. Inside its
# container the stream service has WORKDIR /app, so its modules import each
# other by bare name: `from backoff import ExponentialBackoff`.
#
# Putting stream/ on sys.path lets the tests import those modules under the
# exact same names the container uses, so we test the real import shape.
sys.path.insert(0, str(ROOT / "stream"))