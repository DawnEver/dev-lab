"""The docs driver, and the two properties two of its three predecessors did not have.

TWO-SIDED THROUGHOUT. Every arm here has a partner: the driver must still REFUSE what the good copy
refused (a failed subprocess, a build that wrote no entry page) and still ACCEPT what it accepted (a
clean build, a genuinely absent toolchain). A one-sided test of a refusal is satisfied by a driver
that refuses everything.

NO TEST MAY OPEN A BROWSER. The browser branch is COVERED and MOCKED -- patched at
``lab_commons.dev.docsite.webbrowser.open``, i.e. where this module LOOKS THE NAME UP, not at the
definition site, which would not affect the reference this module already holds. The user of this
family reported a browser popping open during a test run twice; the branch stays, the window does
not, and the assertion is stronger than before because it pins the exact URL.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev import docsite


def _writes(name: str = 'index.html', body: str = 'ok'):
    def build(_root: Path, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / name).write_text(body, encoding='utf-8')

    return build


def _raises(_root: Path, _out_dir: Path) -> None:
    msg = 'the builder failed'
    raise RuntimeError(msg)


PRESENT = docsite.Exe(sys.executable)
ABSENT = docsite.Exe('no-such-tool-anywhere-on-this-box')


def _site(slug: str, *, requires=PRESENT, build=None, **kw) -> docsite.SubSite:
    return docsite.SubSite(
        slug=slug,
        title=slug.title(),
        requires=requires,
        absent_means=f'the {slug} reference',
        build=build or _writes(),
        **kw,
    )


# --------------------------------------------------------------------------- the check=True half


def test_a_failed_command_RAISES_rather_than_reporting_success(tmp_path: Path) -> None:
    """THE defect this module was extracted to end: optimi-lab ran pdoc with ``check=False``.

    An errored build produced an empty output directory and exit 0 -- indistinguishable from a real
    build at every downstream point.
    """
    with pytest.raises(subprocess.CalledProcessError):
        docsite.run([sys.executable, '-c', 'raise SystemExit(3)'], cwd=tmp_path)


def test_a_succeeding_command_is_ACCEPTED(tmp_path: Path) -> None:
    """The accepting side: a driver that raised on everything would pass the arm above."""
    docsite.run([sys.executable, '-c', 'pass'], cwd=tmp_path)


def test_every_command_carries_a_bound(tmp_path: Path) -> None:
    """An unbounded subprocess in a pre-push hook is a hang with no exit code and no diagnosis."""
    with pytest.raises(subprocess.TimeoutExpired):
        docsite.run([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=tmp_path, timeout=1)


# ------------------------------------------------------------------- the skip-and-say-so half


def test_an_absent_tool_SKIPS_and_the_report_NAMES_what_is_lost(tmp_path: Path) -> None:
    report = docsite.build_all([_site('rust', requires=ABSENT)], tmp_path, tmp_path / 'out', title='T', version='1.0')
    assert report.built == []
    assert 'rust' in report.skipped
    reason = report.skipped['rust']
    assert 'not on PATH' in reason and 'the rust reference' in reason, reason
    assert 'SKIPPED rust' in report.summary(), 'a count would let a permanently-broken toolchain look routine'


def test_a_skipped_subsite_is_RENDERED_on_the_portal_with_its_reason(tmp_path: Path) -> None:
    """Omission would make "not built here" and "does not exist" read identically."""
    sites = [_site('python'), _site('rust', requires=ABSENT)]
    docsite.build_all(sites, tmp_path, tmp_path / 'out', title='T', version='1.0')
    portal = (tmp_path / 'out' / 'index.html').read_text(encoding='utf-8')
    assert 'href="python/index.html"' in portal
    assert 'not built here' in portal and 'the rust reference' in portal
    assert 'href="rust/index.html"' not in portal, 'the portal must not link a sub-site that was not built'


def test_a_present_tool_is_BUILT_not_skipped(tmp_path: Path) -> None:
    """The accepting side of the skip: a driver that skipped everything would pass the arm above."""
    report = docsite.build_all([_site('python')], tmp_path, tmp_path / 'out', title='T', version='1.0')
    assert report.built == ['python'] and report.skipped == {}


def test_a_builder_that_raises_is_NOT_swallowed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        docsite.build_all([_site('python', build=_raises)], tmp_path, tmp_path / 'out', title='T', version='1.0')


def test_a_build_that_writes_no_entry_page_is_REFUSED(tmp_path: Path) -> None:
    """The portal links ``<slug>/<entry>``; a build that does not write it ships a dead link.

    MEASURED in motronics-studio 2026-07-29: ``cargo doc -p <crate>`` writes no root index, unlike
    ``--workspace``, so the front page's first link 404'd.
    """
    with pytest.raises(FileNotFoundError, match=r'wrote no index\.html'):
        docsite.build_all(
            [_site('rust', build=_writes('other.html'))], tmp_path, tmp_path / 'out', title='T', version='1.0'
        )


def test_prose_in_a_reason_is_ESCAPED() -> None:
    """A reason is written by a person; an unescaped ``<`` or ``&`` breaks the page it explains."""
    site = docsite.SubSite(slug='x', title='X & <Y>', requires=ABSENT, absent_means='a <tag> & more', build=_writes())
    portal = docsite.render_portal(docsite.BuildReport(skipped={'x': 'a <tag> & more'}), [site], title='T', version='1')
    assert '<tag>' not in portal and '&lt;tag&gt;' in portal


# ----------------------------------------------------------------------- the pdoc invocation


def test_pdoc_runs_through_THIS_interpreter_and_never_a_bare_name() -> None:
    """``pdoc`` as ``argv[0]`` resolves only in an ACTIVATED venv; ``-m`` cannot disagree with us."""
    argv = docsite.pdoc_argv(['pkg'], 'out')
    assert argv[:3] == [sys.executable, '-m', 'pdoc']


def test_pdoc_is_never_asked_for_two_mutually_exclusive_modes() -> None:
    """``-o`` writes files and exits; ``-h``/``-p`` serve. optimi-lab passed both, under check=False."""
    argv = docsite.pdoc_argv(['pkg'], 'out')
    assert '-o' in argv
    assert '-h' not in argv and '-p' not in argv


def test_an_unset_pdoc_option_contributes_no_flag() -> None:
    """A flag with an empty value is a flag pdoc parses as its next argument's name."""
    argv = docsite.pdoc_argv(['pkg'], 'out')
    assert '--logo' not in argv
    assert '--logo' in docsite.pdoc_argv(['pkg'], 'out', logo='http://example.invalid/l.svg')


# ------------------------------------------------------------------------ the browser branch


def test_open_site_opens_EXACTLY_the_page_it_was_given(tmp_path: Path, mocker) -> None:
    """Mocked, so no window opens; and the URL is pinned, which no predecessor's test did."""
    page = tmp_path / 'index.html'
    page.write_text('x', encoding='utf-8')
    mock_open = mocker.patch('lab_commons.dev.docsite.webbrowser.open')
    docsite.open_site(page)
    mock_open.assert_called_once_with(page.resolve().as_uri())


def test_building_a_site_opens_NOTHING(tmp_path: Path, mocker) -> None:
    """The other side of the same ratchet: no build path may default a browser open to on."""
    mock_open = mocker.patch('lab_commons.dev.docsite.webbrowser.open')
    docsite.build_all([_site('python')], tmp_path, tmp_path / 'out', title='T', version='1.0')
    mock_open.assert_not_called()


# ------------------------------------------------------------------- composite requirements


def test_a_composite_requirement_NAMES_the_missing_part(tmp_path: Path) -> None:
    """A composite that reports only its own absence sends the reader to check every part."""
    every = docsite.Every((PRESENT, docsite.Tree(str(tmp_path / 'never-cloned'))))
    assert not every.present()
    assert 'never-cloned' in every.absent_kind and 'not present' in every.absent_kind
    assert PRESENT.name not in every.absent_kind, 'a satisfied part must not be reported as missing'


def test_a_composite_whose_parts_are_ALL_present_is_present(tmp_path: Path) -> None:
    """The accepting side: a composite that was never satisfiable would pass the arm above."""
    assert docsite.Every((PRESENT, docsite.Tree(str(tmp_path)))).present()
