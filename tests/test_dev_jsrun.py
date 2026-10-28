"""``dev_lab.dev.jsrun`` -- the family's one JS test runtime runs from the lock, never the host PATH."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from dev_lab.dev.jsrun import ENGINE_PACKAGE, JsFailed, node_path, run_js


def test_the_engine_is_the_locked_one_inside_this_venv() -> None:
    """The binary lives in the installed wheel, not wherever the host PATH points."""
    assert node_path().is_file()
    spec = importlib.util.find_spec(ENGINE_PACKAGE)
    assert spec is not None
    assert spec.origin is not None
    assert Path(spec.origin).parent in node_path().parents


def test_a_program_on_stdin_returns_its_stdout() -> None:
    """The web/Node APIs the family's client JS uses are present: the reason the engine is Node."""
    program = (
        "(async()=>{const raw=Uint8Array.from(atob('H4sIAAAAAAAC/8tIzcnJBwCGphA2BQAAAA=='),c=>c.charCodeAt(0));"
        "const out=new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip')));"
        'await new Promise(r=>setTimeout(r,1));'
        'process.stdout.write(new TextDecoder().decode(await out.arrayBuffer()));})()'
    )
    assert run_js(program) == 'hello'


def test_a_failing_program_raises_with_its_stderr() -> None:
    """PLANTED: a thrown error and a nonzero exitCode both raise, carrying stderr and the code."""
    with pytest.raises(JsFailed, match='planted failure'):
        run_js("throw Error('planted failure')")
    with pytest.raises(JsFailed, match='exit 3'):
        run_js('process.exitCode=3')


def test_flags_reach_the_engine() -> None:
    """``--check`` parses without running; a syntax error raises."""
    assert run_js("throw Error('never runs')", '--check') == ''
    with pytest.raises(JsFailed):
        run_js('function (', '--check')
