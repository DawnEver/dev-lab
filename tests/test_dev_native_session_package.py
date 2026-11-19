"""The real wheel, not an editable checkout, carries the native identity facts into installed hooks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from dev_lab.dev import native_session


def test_the_built_wheel_installs_the_same_identity_catalog_beside_its_launcher(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which('uv')
    assert uv is not None, 'the official build executable must be available'
    built = subprocess.run(
        [uv, 'build', '--wheel', '--out-dir', str(tmp_path / 'wheel')],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert built.returncode == 0, built.stderr
    [wheel] = (tmp_path / 'wheel').glob('*.whl')
    expected = Path(native_session.__file__).with_suffix('.json').read_bytes()
    unpacked = tmp_path / 'installed'
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read('dev_lab/dev/native_session.json') == expected
        assert 'dev_lab/dev/native_session.py' in archive.namelist()
        assert 'dev_lab/dev/agent_launcher.js' in archive.namelist()
        archive.extractall(unpacked)
    code = (
        'import pathlib, sys\n'
        'from dev_lab.dev import native_session, agent_guard, agent_wiring\n'
        'installed, checkout = map(pathlib.Path, sys.argv[1:])\n'
        'assert pathlib.Path(native_session.__file__).is_relative_to(installed)\n'
        "assert native_session.session_of({'CODEX_THREAD_ID': 'wheel-native'}) == 'wheel-native'\n"
        'agent_guard.install_guard(checkout)\n'
        "catalog = (checkout / agent_wiring.LAUNCHER_REL).with_name('native_session.json')\n"
        "assert catalog.read_bytes() == pathlib.Path(native_session.__file__).with_suffix('.json').read_bytes()\n"
    )
    done = subprocess.run(
        [sys.executable, '-c', code, str(unpacked), str(tmp_path / 'consumer')],
        cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': str(unpacked)},
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert done.returncode == 0, done.stderr
