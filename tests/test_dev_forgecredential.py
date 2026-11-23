"""``forgecredential``: a declared forge login is stored and read through the store helper -- presence only."""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.forgecredential import STORE_ONLY, drift, stored_logins

_MINTED = 'tok3n-SECRET-value'
_DEV = {'forges': {'forge.example': ['dev-user']}, 'helpers': {'forge.example': 'store'}}


def _store(tmp_path: Path, *lines: str) -> Path:
    store = tmp_path / '.git-credentials'
    store.write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8')
    return store


def _drift(tmp_path: Path, *lines: str, helpers: list[str] = STORE_ONLY, dev: dict | None = None) -> list[str]:
    return drift(_DEV if dev is None else dev, helpers_for=lambda _host: list(helpers), store=_store(tmp_path, *lines))


def test_a_stored_login_read_through_the_store_is_no_drift(tmp_path: Path) -> None:
    assert _drift(tmp_path, f'https://dev-user:{_MINTED}@forge.example') == []


def test_a_missing_login_is_drift_naming_the_place_door_and_never_the_secret(tmp_path: Path) -> None:
    found = _drift(tmp_path, f'https://other:{_MINTED}@forge.example', f'https://dev-user:{_MINTED}@github.com')
    assert len(found) == 1
    assert "'dev-user'" in found[0]
    assert 'dev_lab.dev.devcredential --login dev-user' in found[0]
    assert '-m dev_lab.dev.forge auth login --host forge.example' in found[0], 'the exact login line for THAT forge'
    assert _MINTED not in found[0]


def test_a_helper_other_than_the_store_is_drift_naming_use_store(tmp_path: Path) -> None:
    found = _drift(tmp_path, f'https://dev-user:{_MINTED}@forge.example', helpers=['manager'])
    assert len(found) == 1
    assert 'devhost use-store --host forge.example' in found[0]


def test_an_undeclared_store_helper_is_drift_and_an_empty_login_list_is_silent(tmp_path: Path) -> None:
    assert 'no store helper declared' in _drift(tmp_path, dev={'forges': {'forge.example': ['dev-user']}})[0]
    assert _drift(tmp_path, dev={'forges': {'forge.example': []}}) == []


def test_a_missing_store_file_is_every_login_missing(tmp_path: Path) -> None:
    found = drift(_DEV, helpers_for=lambda _host: list(STORE_ONLY), store=tmp_path / 'absent')
    assert len(found) == 1


def test_store_lines_yield_users_by_host_only_never_secrets() -> None:
    lines = [
        f'https://dev-user:{_MINTED}@forge.example',
        f'https://b%40x:{_MINTED}@Forge.Example:443/path',
        f'http://plain:{_MINTED}@forge.example',  # not https: git would not send it for https://
        f'https://c:{_MINTED}@forge.example.evil',  # a different host
        'garbage',
    ]
    assert stored_logins('forge.example', lines) == {'dev-user', 'b%40x'}


def test_an_empty_store_never_offers_use_store_only_the_mint(tmp_path: Path) -> None:
    """PLANTED CONTROL (2026-11-21): use-store before any token reset the working helper and cut the forge off."""
    found = _drift(tmp_path, helpers=['manager'])
    assert len(found) == 1
    assert 'forge token mint' in found[0]
    assert 'use-store' not in found[0]
