"""``python -m dev_lab.supervise`` -- the runnable entry point.

Ten lines, the same shape as ``dev_lab.dev.githooks.__main__``: the package is reached by name
rather than re-exported, so this file exists only to give that name something to run.
"""

from __future__ import annotations

import sys

from dev_lab.supervise.cli import main

if __name__ == '__main__':
    sys.exit(main())
