"""``lab_commons.log`` — named, isolated stdlib logger factory + free-function helpers.

Ported from motronics-studio's ``tests/unit/core/test_mylab_logging.py`` (the ``TestLogger``
class), renamed to this package's import path. The old ``TestReExport`` class (proving
motronics' OLD import paths still resolved to the shared implementation) is dropped here --
that assertion belongs in the CONSUMER's tree (motronics-studio), not this package's.
"""

import logging

from lab_commons.log import emit, get_logger, log


class TestLogger:
    def test_get_logger_is_isolated(self):
        lg = get_logger('some_app_xyz')
        assert lg is logging.getLogger('some_app_xyz')
        assert lg.propagate is False

    def test_log_does_not_raise_on_critical(self):
        # CRITICAL is a valid level -> it logs, never raises (only unknown levels raise).
        log('boom', level='CRITICAL')

    def test_log_raises_on_unknown_level(self):
        try:
            log('boom', level='NOT_A_LEVEL')
        except ValueError as e:
            assert 'NOT_A_LEVEL' in str(e)
        else:
            raise AssertionError('expected ValueError for an unknown log level')


class TestEmit:
    """``emit`` -- the one-line stdout/stderr writer every family CLI shares (T201 is
    never waived, so ``print`` needs a single, tested home; user directive 2026-08-02)."""

    def test_emit_writes_one_line_to_stdout(self, capsys):
        emit('verdict: PASS')
        captured = capsys.readouterr()
        assert captured.out == 'verdict: PASS\n'
        assert captured.err == ''

    def test_emit_default_line_is_blank(self, capsys):
        emit()
        assert capsys.readouterr().out == '\n'

    def test_emit_err_targets_stderr(self, capsys):
        emit('refused', err=True)
        captured = capsys.readouterr()
        assert captured.err == 'refused\n'
        assert captured.out == ''

    def test_emit_flush_does_not_raise(self, capsys):
        emit('progress', flush=True)
        assert capsys.readouterr().out == 'progress\n'

    def test_emit_formats_non_strings_like_print(self, capsys):
        emit(42)
        assert capsys.readouterr().out == '42\n'
