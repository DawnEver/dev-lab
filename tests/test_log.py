"""``lab_commons.log`` — named, isolated stdlib logger factory + free-function helpers.

Ported from motronics-studio's ``tests/unit/core/test_mylab_logging.py`` (the ``TestLogger``
class), renamed to this package's import path. The old ``TestReExport`` class (proving
motronics' OLD import paths still resolved to the shared implementation) is dropped here --
that assertion belongs in the CONSUMER's tree (motronics-studio), not this package's.
"""

import io
import logging
import sys

import pytest

from lab_commons.log import emit, get_logger, log


class TestLogger:
    def test_get_logger_is_isolated(self) -> None:
        lg = get_logger('some_app_xyz')
        assert lg is logging.getLogger('some_app_xyz')
        assert lg.propagate is False

    def test_log_does_not_raise_on_critical(self) -> None:
        # CRITICAL is a valid level -> it logs, never raises (only unknown levels raise).
        log('boom', level='CRITICAL')

    def test_log_raises_on_unknown_level(self) -> None:
        with pytest.raises(ValueError, match='NOT_A_LEVEL'):
            log('boom', level='NOT_A_LEVEL')


class TestEmit:
    """``emit`` -- the one-line stdout/stderr writer every family CLI shares.

    T201 is never waived, so ``print`` needs a single, tested home (user directive 2026-08-02).
    """

    def test_emit_writes_one_line_to_stdout(self, capsys) -> None:
        emit('verdict: PASS')
        captured = capsys.readouterr()
        assert captured.out == 'verdict: PASS\n'
        assert captured.err == ''

    def test_emit_default_line_is_blank(self, capsys) -> None:
        emit()
        assert capsys.readouterr().out == '\n'

    def test_emit_err_targets_stderr(self, capsys) -> None:
        emit('refused', err=True)
        captured = capsys.readouterr()
        assert captured.err == 'refused\n'
        assert captured.out == ''

    def test_emit_flush_does_not_raise(self, capsys) -> None:
        emit('progress', flush=True)
        assert capsys.readouterr().out == 'progress\n'

    def test_emit_formats_non_strings_like_print(self, capsys) -> None:
        emit(42)
        assert capsys.readouterr().out == '42\n'


class TestEmitOnAConsoleThatCannotCarryTheCharacter:
    """THE CONSOLE DEGRADES; IT DOES NOT KILL THE RUN -- both directions, planted.

    MEASURED 2026-09-18 on wdg-lab: a test printed U+2713, ``lab_commons.dev.verify._tee`` handed it
    to ``emit``, and a cp1252 stdout -- the Windows DEFAULT whenever nothing overrides it -- raised
    ``UnicodeEncodeError`` out through the verdict runner, which produced an INCONCLUSIVE WITH NO
    LOG. The crash reproduces in four lines, so the fix is controlled in four.

    THE STREAM IS PLANTED, NOT MOCKED. ``capsys`` hands back a stream that encodes anything, so it
    can never see this defect; these two build a real ``TextIOWrapper`` over cp1252 and drive the
    REAL writer through it.

    THE SECOND TEST IS THE HALF THAT IS EASY TO FORGET. Without it, a "fix" that ran every line
    through a lossy re-encode -- mangling every log this family cites -- would pass the first test
    and look green.
    """

    @staticmethod
    def _cp1252_console() -> io.TextIOWrapper:
        return io.TextIOWrapper(io.BytesIO(), encoding='cp1252', newline='')

    def test_a_character_cp1252_cannot_carry_is_replaced_rather_than_raised(self, monkeypatch) -> None:
        console = self._cp1252_console()
        monkeypatch.setattr(sys, 'stdout', console)
        emit('spinner ✓ done', flush=True)
        assert console.buffer.getvalue() == b'spinner ? done\n'

    def test_ordinary_output_reaches_the_same_console_unchanged(self, monkeypatch) -> None:
        console = self._cp1252_console()
        monkeypatch.setattr(sys, 'stdout', console)
        emit('verdict: PASS  ruff=0  pytest=307 passed', flush=True)
        assert console.buffer.getvalue() == b'verdict: PASS  ruff=0  pytest=307 passed\n'
