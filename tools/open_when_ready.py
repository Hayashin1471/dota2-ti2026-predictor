"""Open the browser once the server actually answers.

run.bat starts this alongside uvicorn.  Opening the browser immediately would
land on a "can't connect" page, because uvicorn needs a second or two to bind.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
import webbrowser

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 90


def main() -> int:
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as resp:
                if resp.status < 500:
                    webbrowser.open(URL)
                    return 0
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)

    print(f"Server khong phan hoi sau {TIMEOUT_SECONDS}s - hay mo {URL} thu cong.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
