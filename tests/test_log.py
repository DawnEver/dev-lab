"""``lab_commons.log`` — named, isolated stdlib logger factory + free-function helpers.

Ported from motronics-studio's ``tests/unit/core/test_mylab_logging.py`` (the ``TestLogger``
class), renamed to this package's import path. The old ``TestReExport`` class (proving
motronics' OLD import paths still resolved to the shared implementation) is dropped here --
that assertion belongs in the CONSUMER's tree (motronics-studio), not this package's.
"""

import logging

from lab_commons.log import get_logger, log


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
