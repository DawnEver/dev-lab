"""The agent deny registry, FAMILY-REPO-IS-CHECKED-OUT row -- pure DATA, judged against this machine's declarations.

``when: 'declared-repo'``: the engine matches the pattern (a ``git clone``, bare or through the retry wrapper) and
only then asks ``python -m dev_lab.dev.familyrepos clone-check`` (the command on stdin) whether the url is a family
repo's remote ([family_repos], the config source's family layer) that ``[repos]`` already maps to a checkout. A
clone of any other url passes. The answer is the machine file's, so no repo or path is spelled here.
"""

from __future__ import annotations

from dev_lab.dev.familyrepos import HAZARD, REMEDY, RULE_ID

__all__ = ['FAMILY_REPO_IS_CHECKED_OUT']

FAMILY_REPO_IS_CHECKED_OUT: dict[str, object] = {
    'id': RULE_ID,
    'pattern': r'(?:git(?:\.exe)?(?:\s+-[Cc]\s+\S+)*\s+clone|(?:sh|bash)\s+\S*retry\S*\s+clone)\b',
    'matches': 'command',
    'when': 'declared-repo',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'git clone https://forge.example/o/declared.git',
        'git clone https://forge.example/o/declared ../declared',
        'sh scripts/hooks/with-retry.sh clone git@forge.example:o/declared.git',
    ),
    'permits': ('git log --oneline -1',),
}
