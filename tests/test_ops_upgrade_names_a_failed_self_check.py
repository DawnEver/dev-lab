"""A failed ``ops upgrade`` self-check names the line its load refused, never ``loads FAILED`` alone.

forge-a1, 2026-11-10: the self-check of an upgrade to the tip refused the host's live file, and ``self-check loads
FAILED`` hid WHICH key; the check's last line is the refusal, so it is named.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.ops import upgrade
from dev_lab.ops.config import load

_HOST = """
[ops]
home = "{home}"
python = "/opt/dev-lab/.venv/bin/python"
repos = ["https://forge.example/team/alpha.git"]
[ops.forge]
api = "http://127.0.0.1:9000"
admin = "admin"
[ops.forge.accounts.reader]
role = "read"
repos = ["team/alpha"]
"""


def test_a_failed_self_check_names_what_its_load_refused(tmp_path: Path) -> None:
    path = tmp_path / 'host.toml'
    path.write_text(_HOST.format(home=(tmp_path / 'home').as_posix()), encoding='utf-8')
    host = load(path, environ={})
    said = 'Traceback ...\nValueError: [ops.forge] read_only is retired: declare each login as ...\n'
    assert upgrade.failed_check(host, lambda _argv: (1, said)) == f'loads ({said.strip().splitlines()[-1]})'
    assert upgrade.failed_check(host, lambda _argv: (1, '')) == 'loads', 'a silent failure is still named'
    assert not upgrade.failed_check(host, lambda _argv: (0, 'ok'))
