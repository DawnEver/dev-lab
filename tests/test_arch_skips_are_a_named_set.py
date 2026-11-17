"""XFAIL-NOT-SKIP: a known failure carries its residual; a skip records nothing.

A skip is the one disposition that tells a later reader nothing at all -- work that stopped working
and work that was never reachable produce the identical green dot. In a package four repos depend
on, that is worse than elsewhere: a capability skipped on this box is a capability a consumer
believes it has.

THE PIN IS A NAMED SET AND IT IS CURRENTLY EMPTY, which is a claim rather than an absence: the floor
below proves the scan reached this repo's test modules, so "no skips" is measured and not merely
unobserved. An `xfail` is NOT scanned for -- it is the sanctioned disposition, and pinning it would
make the honest choice the expensive one.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import TEST_FLOOR, assert_floor, parse, rel, suite_modules

from dev_lab.dev.failprint import subject_lines, subjects_of

#: Test modules permitted to skip, each with the reason. EMPTY, measured 2026-09-15.
ALLOWED_SKIPS: dict[str, str] = {}


def skip_sites(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every ``pytest.mark.skip*`` / ``pytest.skip()`` site, as ``path:line`` -- pure over its argument."""
    out: list[str] = []
    for path in paths:
        out.extend(
            f'{_name(path)}:{node.lineno} ({node.attr})'
            for node in ast.walk(parse(path))
            if isinstance(node, ast.Attribute) and node.attr.startswith('skip') and _root_name(node) == 'pytest'
        )
    return tuple(out)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _name(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.name


def skip_refusal(live: set[str], pinned: set[str]) -> str:
    """The red of the skip ratchet: both sides by name, and one subject line per module that moved."""
    return (
        f'modules that skip and are not pinned: {sorted(live - pinned)} -- an xfail carries '
        f'its residual, a skip carries nothing. Pinned but no longer skipping: '
        f'{sorted(pinned - live)} -- delete the entry in the same edit.\n' + subject_lines(live ^ pinned)
    )


def test_no_test_module_skips() -> None:
    """THE CHECK, two-sided: an unpinned skip reds, and so would a pin nothing uses."""
    paths = suite_modules()
    assert_floor(len(paths), TEST_FLOOR, 'skip')
    live = {site.split(':')[0] for site in skip_sites(paths)}
    assert live == set(ALLOWED_SKIPS), skip_refusal(live, set(ALLOWED_SKIPS))


def test_a_planted_skip_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: both spellings, through the REAL scanner, past a clean file."""
    marked = tmp_path / 'marked.py'
    marked.write_text('import pytest\n\n\n@pytest.mark.skipif(True, reason="x")\ndef test_a(): ...\n', encoding='utf-8')
    called = tmp_path / 'called.py'
    called.write_text('import pytest\n\n\ndef test_b():\n    pytest.skip("x")\n', encoding='utf-8')
    clean = tmp_path / 'clean.py'
    clean.write_text(
        'import pytest\n\n\n@pytest.mark.xfail(reason="residual 3e-4")\ndef test_c(): ...\n', encoding='utf-8'
    )
    sites = skip_sites((marked, called, clean))
    assert any('skipif' in s for s in sites)
    assert any('marked.py' in s or 'marked' in s for s in sites)
    assert not any('clean' in s for s in sites), 'an xfail is the sanctioned disposition, not a violation'


def test_the_skip_red_names_each_moved_module_as_a_subject() -> None:
    """THE PLANTED CONTROL for the fingerprint: an unpinned and an orphaned module are each a subject line."""
    said = skip_refusal({'a.py', 'kept.py'}, {'kept.py', 'gone.py'})
    assert subjects_of(said) == {'a.py', 'gone.py'}, said
    assert subjects_of(skip_refusal({'kept.py'}, {'kept.py'})) == frozenset()
