"""Container liveness probe: no traceback, URL or payload is written on failure."""

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main():
    try:
        with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            healthy = response.status == 200 and json.load(response) == {"status": "ok"}
    except (URLError, OSError, ValueError):
        return 1
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
