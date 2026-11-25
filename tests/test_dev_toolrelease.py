"""``toolrelease``: a pinned release is installed only after its sha256 matches, and an absent tool names its door."""

from __future__ import annotations

import hashlib
import io
import re
import urllib.error
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from dev_lab.dev import toolrelease
from dev_lab.dev.toolrelease import RCLONE, ChecksumMismatch, ToolAbsent, UnsupportedPlatform

_BODY = b'#!/bin/sh\necho rclone v1.76.0\n'


def _archive(stem: str, member: str, body: bytes = _BODY) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        bundle.writestr(f'{stem}/{member}', body)
        bundle.writestr(f'{stem}/README.txt', b'not the tool')
    return buffer.getvalue()


def _pinned_to(monkeypatch: pytest.MonkeyPatch, key: str, data: bytes) -> None:
    """Pin *key*'s asset to *data*'s digest, as a real pin is read from the release's SHA256SUMS."""
    asset = RCLONE.assets[key][0]
    pinned = replace(RCLONE, assets={**RCLONE.assets, key: (asset, hashlib.sha256(data).hexdigest())})
    monkeypatch.setitem(toolrelease.RELEASES, 'rclone', pinned)


def _fetching(data: bytes, seen: list[str]) -> Callable[[str, Path], None]:
    def fetch(url: str, to: Path) -> None:
        seen.append(url)
        to.write_bytes(data)

    return fetch


def test_a_pinned_archive_is_verified_then_its_one_member_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _archive('rclone-v1.76.0-linux-amd64', 'rclone')
    _pinned_to(monkeypatch, 'linux-amd64', data)
    seen: list[str] = []
    placed = toolrelease.install('rclone', directory=tmp_path / 'bin', key='linux-amd64', fetch=_fetching(data, seen))
    assert seen == ['https://downloads.rclone.org/v1.76.0/rclone-v1.76.0-linux-amd64.zip']
    assert placed == tmp_path / 'bin' / 'rclone'
    assert placed.read_bytes() == _BODY
    assert sorted(p.name for p in (tmp_path / 'bin').iterdir()) == ['rclone'], 'only the declared member'


def test_a_windows_install_places_the_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive('rclone-v1.76.0-windows-amd64', 'rclone.exe')
    _pinned_to(monkeypatch, 'windows-amd64', data)
    placed = toolrelease.install('rclone', directory=tmp_path, key='windows-amd64', fetch=_fetching(data, []))
    assert placed.name == 'rclone.exe'
    assert placed.read_bytes() == _BODY


def test_a_checksum_mismatch_is_refused_and_nothing_is_placed(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same archive shape with a digest that is not the pin never reaches the directory."""
    data = _archive('rclone-v1.76.0-linux-amd64', 'rclone', b'tampered')
    with pytest.raises(ChecksumMismatch, match='not the pinned'):
        toolrelease.install('rclone', directory=tmp_path / 'bin', key='linux-amd64', fetch=_fetching(data, []))
    assert not (tmp_path / 'bin').exists()


def test_the_pins_are_sha256_digests_for_every_published_platform() -> None:
    assert RCLONE.version == '1.76.0'
    for key, (asset, digest) in RCLONE.assets.items():
        assert asset == f'rclone-v{RCLONE.version}-{key}.zip'
        assert len(digest) == 64
        assert int(digest, 16) >= 0


def test_a_platform_without_an_archive_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedPlatform, match='no archive for freebsd-riscv64'):
        toolrelease.install('rclone', directory=tmp_path, key='freebsd-riscv64', fetch=_fetching(b'', []))


def test_platform_keys_follow_the_release_names() -> None:
    assert toolrelease.platform_key('Windows', 'AMD64') == 'windows-amd64'
    assert toolrelease.platform_key('Linux', 'x86_64') == 'linux-amd64'
    assert toolrelease.platform_key('Darwin', 'arm64') == 'osx-arm64'


def test_the_install_directory_is_user_space() -> None:
    assert toolrelease.tool_dir(windows=False, environ={'HOME': '/h/u'}) == Path('/h/u/.local/bin')
    assert toolrelease.tool_dir(windows=True, environ={'LOCALAPPDATA': 'C:/L'}) == Path('C:/L/dev-lab/bin')


def test_resolve_prefers_the_install_directory_then_path(tmp_path: Path) -> None:
    (tmp_path / 'rclone').write_bytes(_BODY)
    assert (
        toolrelease.resolve('rclone', directory=tmp_path, which=lambda _n: None, windows=False) == tmp_path / 'rclone'
    )
    found = toolrelease.resolve(
        'rclone', directory=tmp_path / 'none', which=lambda _n: '/usr/bin/rclone', windows=False
    )
    assert found == Path('/usr/bin/rclone')


def test_an_absent_tool_names_its_install_door(tmp_path: Path) -> None:
    """PLANTED CONTROL for the resolve test: neither place holds it, so the refusal carries the door."""
    with pytest.raises(ToolAbsent, match=r'python -m dev_lab\.dev\.toolrelease install rclone'):
        toolrelease.resolve('rclone', directory=tmp_path, which=lambda _n: None, windows=False)


def test_a_download_sends_the_generic_client_name_not_urllibs(tmp_path: Path) -> None:
    """downloads.rclone.org refuses urllib's default ``Python-urllib`` client with 403; the request carries ours."""
    seen: list[str] = []

    def opener(req: object, **_: object) -> io.BytesIO:
        seen.append(req.get_header('User-agent'))  # type: ignore[attr-defined]
        return io.BytesIO(b'body')

    toolrelease._download('https://downloads.rclone.org/v1.76.0/x.zip', tmp_path / 'x.zip', opener=opener)
    assert seen == [toolrelease.USER_AGENT]
    assert 'python-urllib' not in seen[0].lower()
    assert (tmp_path / 'x.zip').read_bytes() == b'body'


def test_an_http_refusal_names_its_status_and_its_door(tmp_path: Path) -> None:
    def opener(*_: object, **__: object) -> object:
        url, reason = 'u', 'Forbidden'
        raise urllib.error.HTTPError(url, 403, reason, None, None)  # type: ignore[arg-type]

    with pytest.raises(toolrelease.DownloadRefused) as caught:
        toolrelease._download('https://downloads.rclone.org/v1.76.0/x.zip', tmp_path / 'x.zip', opener=opener)
    text = str(caught.value)
    assert 'HTTP 403' in text
    assert 'python -m dev_lab.dev.toolrelease install rclone' in text
    assert not (tmp_path / 'x.zip').exists()


def _source_pin_problems(pin: toolrelease.SourceRelease) -> list[str]:
    """What makes *pin* not a pin: a commit that is not a full sha, a tag not naming its version, a non-https remote."""
    found = []
    if not re.fullmatch(r'[0-9a-f]{40}', pin.commit):
        found.append(f'commit {pin.commit!r} is not a full sha')
    if pin.version not in pin.tag:
        found.append(f'tag {pin.tag!r} does not name version {pin.version!r}')
    if not pin.url.startswith('https://'):
        found.append(f'url {pin.url!r} is not https')
    return found


def test_the_femm_source_pin_is_one_tagged_release_at_a_full_commit() -> None:
    assert toolrelease.FEMM_QT.name == 'femm', 'the capability it provides: [capabilities.femm]'
    assert _source_pin_problems(toolrelease.FEMM_QT) == []
    moved = replace(toolrelease.FEMM_QT, tag='v5.0.20261021', commit='31ee4bf6')
    assert len(_source_pin_problems(moved)) == 2, 'PLANTED CONTROL: a short commit and a foreign tag are both caught'
