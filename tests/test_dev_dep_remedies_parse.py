"""Every printed ``dep`` remedy is a form ``dep`` accepts.

2026-11-26 (v1 #1): ``dep --sync <checkout> --extra X`` was printed by verify and failed with "unrecognized
arguments".

Two halves: the remedies a function builds at run time are parsed as built, and every literal
``-m dev_lab.dev.dep ...`` spelled in ``src/`` is parsed with its placeholders filled.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import _dep_cli, depneeds

_REPO = Path(__file__).resolve().parents[1]
#: ``-m dev_lab.dev.dep`` and the argv after it: flags, and the values a remedy spells -- a ``<placeholder>``, a
#: ``{field}``, a ``$VAR``, ``[ROOT]``, or a path-like word. Prose ends the argv (a word with a comma or a paren).
_VALUE = r'"?(?:<[\w-]+>|\{[\w.]+\}|\$\w+|\[?ROOT\]?|[\w./:~-]+(?<![.,]))"?(?=[\s`\x27")]|$)'
_SPELLED = re.compile(rf'-m dev_lab\.dev\.dep((?:\s+(?:--?[a-z][\w-]*|{_VALUE}))*)')
#: ``{flags}`` is depneeds' remedy; the flags it stands for are ``--extra`` rows.
_FILLED = {'{flags}': '--extra x'}
#: A flag whose value the caller appends after the printed prefix (``DEFAULT_DOOR + ' ' + root``).
_VALUED = frozenset({'--bootstrap', '--root'})
#: Deny-row test commands, not remedies: ``dep --dry-run`` is a hook fixture.
_NOT_REMEDIES = frozenset({'src/dev_lab/dev/_deny_liverun_row.py'})
_FLOOR = 15


def _accepts(tail: str) -> str:
    """Why ``dep`` refuses *tail*, else ``''``."""
    words = [_FILLED.get(w, w).strip('"' + "'") for w in tail.replace('[ROOT]', '').split()]
    argv = ' '.join(words).split()
    if argv and argv[-1] in _VALUED:
        argv.append('x')  # a prefix: the caller appends the tree
    parser = _dep_cli.parser('')
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return f'argparse refused {argv}'
    return _dep_cli.argv_error(args, locking=args.lock_upgrade is not None)


def _spelled_remedies() -> list[tuple[str, str]]:
    listed = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(_REPO), 'grep', '-n', '-e', '-m dev_lab.dev.dep', '--', 'src'],
        capture_output=True, text=True, encoding='utf-8', check=True,
    ).stdout.splitlines()  # fmt: skip
    found = []
    for line in listed:
        path, number, text = line.split(':', 2)
        if path not in _NOT_REMEDIES:
            found += [(f'{path}:{number}', m[1]) for m in _SPELLED.finditer(text) if m[1].strip()]
    return found


def test_every_spelled_dep_remedy_parses() -> None:
    found = _spelled_remedies()
    assert len(found) >= _FLOOR, f'{len(found)} spelled remedies, below the {_FLOOR} floor: the scan went blind'
    bad = [f'{where}: dep{tail} -- {why}' for where, tail in found if (why := _accepts(tail))]
    assert not bad, '\n'.join(bad)


@pytest.mark.parametrize('tail', [' --sync D:/x --extra simba', ' --bootstrap a b', ' --frobnicate', ' --dry-run'])
def test_the_parse_check_refuses_a_form_dep_refuses(tail: str) -> None:
    """PLANTED CONTROL: the exact shape v1 hit, a missing value and an unknown flag are each refused."""
    assert _accepts(tail)


def test_the_missing_extra_remedy_runs_as_printed(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="e"\nversion="0"\n[project.optional-dependencies]\nsimba=["aesim.simba"]\n'
        '[tool.dev_lab.dep]\nextras=[]\nneeds={simba="simba"}\n',
        encoding='utf-8',
    )
    refusal = depneeds.missing_for_part(tmp_path, 'simba', installed=lambda _name: False)
    assert refusal is not None
    tail = refusal.split('-m dev_lab.dev.dep', 1)[1]
    assert not _accepts(tail), tail
