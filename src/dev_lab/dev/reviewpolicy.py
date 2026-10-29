"""REVIEW-POLICY: the family review policy, resolved for one repo, exported for every trigger (user ruling D83).

ONE engine (ai-lab review), ONE policy (here), TWO triggers: the session's pre-push self check (the sharp-review
plugin, another repo, JavaScript) and the forge PR review (the merge gate). The policy is not restated here: it is
READ from the values the forge review itself runs on -- :func:`dev_lab.dev.forgereview.load_review` (family
defaults overlaid by the repo's ``[tool.dev_lab.review]``), :data:`~dev_lab.dev.forgereview_findings.BLOCKING`,
:data:`~dev_lab.dev.forgereview_rounds.SUMMARY_CITES` and :func:`dev_lab.dev.principles.payload` -- so the export
and the gate cannot disagree.

``python -m dev_lab.dev.reviewpolicy --json [--repo <path>]`` prints :func:`policy`; ``max_file_bytes`` is the
review's ``max_diff_bytes`` (one file alone past a slice is held).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.forgereview import load_review
from dev_lab.dev.forgereview_findings import BLOCKING
from dev_lab.dev.forgereview_rounds import SUMMARY_CITES
from dev_lab.dev.principles import payload

__all__ = ['EXPORT_VERSION', 'main', 'policy']

#: The export's version, written as ``schema``: a consumer refuses one it does not know. Printed for another
#: process to read and never persisted or read back here, so it is not a stored format with an upgrade table.
EXPORT_VERSION: Final = 1


def policy(repo: Path) -> dict[str, Any]:
    """The review policy for *repo*: the family's, overlaid by its ``[tool.dev_lab.review]``."""
    review = load_review(repo)
    budget = review.budget
    return {
        'schema': EXPORT_VERSION,
        'principles': payload()['principles'],
        'code': list(budget.code),
        'not_code': list(budget.not_code),
        'max_total_bytes': budget.total_bytes,
        'max_file_bytes': budget.slice_bytes,
        'blocking': list(BLOCKING),
        'summary': {'cite': list(SUMMARY_CITES)},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--json [--repo <path>]`` prints :func:`policy` for that repo (default: the current directory)."""
    parser = argparse.ArgumentParser(description='The family review policy, resolved for one repo.')
    parser.add_argument('--json', action='store_true', required=True, help='print the policy as JSON')
    parser.add_argument('--repo', type=Path, default=Path(), help='the repo whose policy (default: cwd)')
    args = parser.parse_args(argv)
    emit(json.dumps(policy(args.repo), indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
