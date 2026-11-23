"""A FAILED STEP CLEANS ITS OWN HALF-BUILT OUTPUT (user ruling 2026-11-22).

Measured that day: a deploy that died at the file quota left ``cache/uv/.tmp*`` directories, a half-checked-out clone,
and a corrupt git checkout INSIDE the uv cache (``<cache>/git-v0/checkouts/<repo>/<sha>``) that failed every later
venv build of that repo with ``Git operation failed`` / ``git reset --hard <sha>`` (exit status: 128). Each of these
is the failed step's own output, so the failed step removes it -- never anything it did not make:

* :func:`uv_temporaries` -- the uv cache's ``.tmp*`` entries, after a failed uv run (a finished one holds none);
* :func:`damaged_git` -- the cache's checkouts of the ONE commit a build named as failing; the build retries once;
* a failed fresh clone's directory and a failed venv build's own directory are removed by their steps
  (:func:`dev_lab.dev.hpcaccount.steps.update`, :func:`dev_lab.dev.venvcurrent.abandon`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from dev_lab.dev.diskusage import remove_tree

#: The shortest commit prefix uv names a checkout by; a shorter name is never taken for one.
_SHORTEST: Final = 7

__all__ = ['GIT_FAILURE', 'damaged_git', 'uv_temporaries']

#: uv's words when a build failed on its git cache: the package and the commit it could not check out.
GIT_FAILURE: Final = re.compile(
    r'Failed to download and build `(?P<package>[^`@ ]+) @ git\+[^`]*@(?P<sha>[0-9a-f]{7,40})`'
    r'(?=.*Git operation failed)',
    re.DOTALL,
)


def uv_temporaries(cache: Path) -> list[Path]:
    """Remove the uv cache's top-level ``.tmp*`` entries; the paths removed."""
    gone = sorted(path for path in Path(cache).glob('.tmp*')) if Path(cache).is_dir() else []
    for path in gone:
        remove_tree(path) if path.is_dir() and not path.is_symlink() else path.unlink(missing_ok=True)
    return gone


def damaged_git(cache: Path, output: str) -> list[Path]:
    """Remove the cache's checkouts of the commit a failed build's *output* names; the paths removed (none: no match).

    uv keeps one checkout per commit under ``git-v0/checkouts/<repository digest>/<commit prefix>``; only entries
    whose name is a prefix of the failing commit go, so every other repository and commit is untouched.
    """
    failed = GIT_FAILURE.search(output)
    checkouts = Path(cache) / 'git-v0' / 'checkouts'
    if failed is None or not checkouts.is_dir():
        return []
    sha = failed['sha']
    gone = sorted(
        entry
        for repository in checkouts.iterdir()
        if repository.is_dir()
        for entry in repository.iterdir()
        if len(entry.name) >= _SHORTEST and (sha.startswith(entry.name) or entry.name.startswith(sha))
    )
    for entry in gone:
        remove_tree(entry)
    return gone
