"""The uv that writes a lock is the pinned release, installed beside any other; its digests move with its version."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import lockcheck, uvrelease

PIN = Path(lockcheck.__file__).with_name('uv.toml')


def test_the_pin_carries_a_sha256_for_every_platform() -> None:
    release = uvrelease.release(PIN, lockcheck.uv_version())
    assert set(release.assets) == set(uvrelease.ASSETS)
    assert all(len(digest) == 64 for _asset, digest in release.assets.values())


def test_a_moving_pin_reads_its_digests_from_the_release() -> None:
    asked: list[str] = []

    def read(url: str) -> str:
        asked.append(url)
        return f'{"a" * 64}  {url.rsplit("/", 1)[-1].removesuffix(".sha256")}\n'

    release = uvrelease.release(PIN, '9.9.9', read=read)
    assert release.version == '9.9.9'
    assert len(asked) == len(uvrelease.ASSETS)
    assert all('/9.9.9/' in url for url in asked)


def test_a_release_without_a_digest_is_refused() -> None:
    """Planted control: a .sha256 file that carries no digest never yields a pin."""
    with pytest.raises(ValueError, match='carries no sha256'):
        uvrelease.release(PIN, '9.9.9', read=lambda _url: 'not found\n')


def test_pin_uv_moves_the_version_and_every_digest_together(tmp_path: Path) -> None:
    pin = tmp_path / lockcheck.UV_PIN
    pin.parent.mkdir(parents=True)
    pin.write_text(PIN.read_text(encoding='utf-8'), encoding='utf-8')
    lockcheck.pin_uv(tmp_path, '9.9.9', dict.fromkeys(uvrelease.ASSETS, 'b' * 64))
    moved = uvrelease.release(pin, '9.9.9', read=lambda _url: pytest.fail('a pinned version is never re-read'))
    assert all(digest == 'b' * 64 for _asset, digest in moved.assets.values())


def test_the_pinned_version_already_on_path_is_used_as_is(tmp_path: Path) -> None:
    release = uvrelease.release(PIN, lockcheck.uv_version())
    chosen = uvrelease.writer(release, '/usr/bin/uv', version_of=lambda _uv: release.version, base=tmp_path)
    assert chosen == '/usr/bin/uv'


def test_another_version_installs_the_pinned_one_beside_it(tmp_path: Path) -> None:
    release = uvrelease.release(PIN, lockcheck.uv_version())
    placed: list[Path] = []

    def install(wanted, *, directory: Path, key: str) -> Path:
        exe = directory / wanted.exe(windows=key.startswith('windows-'))
        placed.append(exe)
        return exe

    chosen = uvrelease.writer(
        release, '/usr/bin/uv', version_of=lambda _uv: '0.0.1', key='linux-amd64', base=tmp_path, install=install
    )
    assert Path(chosen) == tmp_path / 'uv' / release.version / 'uv'
    assert placed == [Path(chosen)]
