"""RFC 6238 vectors, and the planted controls: wrong, replayed, out-of-window, missing secret."""

from __future__ import annotations

from pathlib import Path

import pytest
from _ops_fixtures import NOW, RFC_KEY, code

from dev_lab.ops.totp import STEP, TotpRefused, accept, code_at, enrol, uri


def test_rfc6238_sha1_vectors() -> None:
    # RFC 6238 appendix B, SHA1, truncated to six digits.
    assert code_at(RFC_KEY, 59 // STEP) == '287082'
    assert code_at(RFC_KEY, 1111111109 // STEP) == '081804'


def _files(tmp_path: Path) -> tuple[Path, Path]:
    secret = tmp_path / 'totp'
    secret.write_text(RFC_KEY, encoding='utf-8')
    return secret, tmp_path / 'state'


def test_a_current_code_is_accepted_once(tmp_path: Path) -> None:
    secret, state = _files(tmp_path)
    assert accept(secret, state, code(), NOW) == int(NOW // STEP)
    with pytest.raises(TotpRefused, match='already used'):
        accept(secret, state, code(), NOW)


def test_an_older_step_after_a_newer_is_a_replay(tmp_path: Path) -> None:
    secret, state = _files(tmp_path)
    accept(secret, state, code(1), NOW)
    with pytest.raises(TotpRefused, match='already used'):
        accept(secret, state, code(0), NOW)


def test_skew_of_one_step_is_accepted_two_is_not(tmp_path: Path) -> None:
    secret, state = _files(tmp_path)
    accept(secret, state, code(-1), NOW)
    with pytest.raises(TotpRefused, match='wrong or outside'):
        accept(secret, state, code(-2), NOW)
    with pytest.raises(TotpRefused, match='wrong or outside'):
        accept(secret, state, code(2), NOW)


def test_a_wrong_or_malformed_code_is_refused(tmp_path: Path) -> None:
    secret, state = _files(tmp_path)
    wrong = str((int(code()) + 1) % 10**6).zfill(6)
    with pytest.raises(TotpRefused, match='wrong'):
        accept(secret, state, wrong, NOW)
    with pytest.raises(TotpRefused, match='6 digits'):
        accept(secret, state, '12a456', NOW)
    assert not state.exists()


def test_no_secret_refuses_naming_enrol(tmp_path: Path) -> None:
    with pytest.raises(TotpRefused, match='enrol'):
        accept(tmp_path / 'absent', tmp_path / 'state', code(), NOW)


def test_enrol_writes_a_secret_once_and_its_uri_names_the_issuer(tmp_path: Path) -> None:
    target = tmp_path / 'etc' / 'totp'
    secret = enrol(target)
    assert len(secret) == 32
    assert target.read_text(encoding='utf-8').strip() == secret
    with pytest.raises(TotpRefused, match='already holds'):
        enrol(target)
    assert enrol(target, force=True) != secret
    assert uri(secret, issuer='forge break-glass', account='bg').startswith('otpauth://totp/forge%20break-glass%3Abg?')
