"""Per-file Python facts: read once, journaled by stat in the checkout's git dir, re-read when the file changes."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import pyfacts

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
FORWARD = 'from pkg.alpha import core\n\n\ndef run(a):\n    return core.run(a)\n'


def _never(_root: Path, rel: str) -> pyfacts.Facts:
    msg = f'{rel} was re-read although the journal holds it unchanged'
    raise AssertionError(msg)


def test_a_journaled_file_is_not_reread_and_a_changed_one_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'src/pkg/beta').mkdir(parents=True)
    (tmp_path / 'src/pkg/beta/hop.py').write_text(FORWARD, encoding='utf-8')
    first = pyfacts.facts(tmp_path, ['src/pkg/beta/hop.py'])['src/pkg/beta/hop.py']
    assert first.forwards == (('run', 'pkg.alpha.core.run'),)
    assert 'pkg.alpha.core.run' in first.uses
    assert (tmp_path / '.git/dev-lab/pyfacts.json').is_file()
    monkeypatch.setattr(pyfacts, '_read', _never)
    assert pyfacts.facts(tmp_path, ['src/pkg/beta/hop.py'])['src/pkg/beta/hop.py'] == first
    (tmp_path / 'src/pkg/beta/hop.py').write_text(FORWARD + '\nLIMIT = 3\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='re-read'):  # THE PLANTED CONTROL: a changed file is read again
        pyfacts.facts(tmp_path, ['src/pkg/beta/hop.py'])


def test_without_a_checkout_root_nothing_is_journaled(tmp_path: Path) -> None:
    (tmp_path / 'm.py').write_text('import os\n', encoding='utf-8')
    assert pyfacts.facts(tmp_path, ['m.py'])['m.py'].uses == frozenset({'os'})
    assert not any(tmp_path.rglob('pyfacts.json'))


def test_a_file_that_does_not_parse_is_a_fact_never_a_clean_one(tmp_path: Path) -> None:
    (tmp_path / 'bad.py').write_text('def (:\n', encoding='utf-8')
    got = pyfacts.facts(tmp_path, ['bad.py'])['bad.py']
    assert got.error is not None
    assert got.error.startswith('SyntaxError')
    assert got.forwards is None
