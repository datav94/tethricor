"""Shim entrypoint (container CMD).

Usage:
  python -m tethricor_runtime -- <argv...>     run a task: forward <argv> to the sandbox provider
  python -m tethricor_runtime                  print resolved settings + security posture, exit 0

The shim NEVER executes <argv> locally; it is forwarded to the sandbox session. All logic
lives in the `tethricor` SDK — this module is a thin delegator so there is a single code path.
"""
from __future__ import annotations

import sys

from tethricor.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
