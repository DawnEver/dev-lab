"""NEVER-LOG-SECRETS as a body a consumer adopts with ONE test, before it has any other test code.

WHAT THE CONSUMER'S FILE ASSERTS. No tracked ``*.py`` in the checkout writes a credential's value to an output
sink: the reading is :func:`dev_lab.dev.secretlog.secret_interpolations`, and nothing of it is restated here.

WHY A ROOT AND NO FLOOR. The corpus is git's tracked list, so a renamed directory cannot hide from the walk, and a
repo with no Python yet holds an honest empty corpus -- a floor would refuse exactly the adopter this exists for.
What a floor would otherwise guard -- a scanner that stopped convicting -- is guarded by the PLANTED CONTROL every
call runs first: a known offender must be convicted and its hashed twin must not, or the body refuses itself.

WHAT THIS DOES NOT PROVE. A secret passed under an innocent name is not seen (the scan is syntactic); the rule
also lives in review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.privatemarkers import tracked_files
from dev_lab.dev.secretlog import secret_interpolations

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['LoggedSecret', 'assert_no_secret_is_logged', 'assert_the_scanner_still_convicts']

RULE: Final = 'NEVER-LOG-SECRETS'
_PLANTED: Final = "emit(f'login with {token}')"
_HONEST: Final = "emit(f'login with {sha256(token)}')"


class LoggedSecret(AssertionError):
    """A tracked module writes a credential's value to an output sink."""


def assert_the_scanner_still_convicts() -> None:
    """PLANTED CONTROL, both directions: the offender is convicted and its hashed form is not."""
    if not secret_interpolations(_PLANTED):
        msg = f'{RULE}: the scanner no longer convicts the planted `{_PLANTED}`, so a green would read a constant'
        raise AssertionError(msg)
    if secret_interpolations(_HONEST):
        msg = f'{RULE}: the scanner convicts the hashed `{_HONEST}`; a lint convicting everything is not obeyed'
        raise AssertionError(msg)


def assert_no_secret_is_logged(*, root: Path) -> None:
    """Refuse every tracked ``*.py`` under *root* that interpolates a secret-named value into a sink."""
    assert_the_scanner_still_convicts()
    found = [
        f'{path.relative_to(root).as_posix()}:{line} `{name}`'
        for path in tracked_files(root)
        if path.suffix == '.py' and path.is_file()
        for line, name in secret_interpolations(path.read_text(encoding='utf-8'))
    ]
    if found:
        msg = (
            f'{RULE}: a sink writes a credential value: {", ".join(found)}. Door: write its hash '
            f'(`sha256(<value>)`) or nothing; details: docs-src/dev/refusals.md (dev-lab).'
        )
        raise LoggedSecret(msg)
