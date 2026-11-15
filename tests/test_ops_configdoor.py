"""``config apply`` admits routine changes, guards the boundary behind consent to exactly the file, rolls back."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from dev_lab.ops.configdoor import ConfigRefused, apply, boundary, changes, digest
from dev_lab.ops.consent.credential import ConsentRefused

LIVE = """\
[cycle]
interval_s = 60

[ops]
home = "/var/lib/ops"
python = "/opt/dev-lab/.venv/bin/python"
repos = ["https://forge.example/o/a.git"]

[ops.access]
account = "ops"
commands = ["/usr/bin/systemctl --no-pager status *"]
"""


def _ok(_path: Path) -> object:
    return None


def _green(_argv: list[str]) -> tuple[int, str]:
    return 0, 'ok'


def _live(tmp_path: Path) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(LIVE, encoding='utf-8')
    return path


def test_a_routine_change_applies_without_consent_and_leaves_a_backup(tmp_path: Path) -> None:
    live = _live(tmp_path)
    candidate = LIVE.replace('interval_s = 60', 'interval_s = 120')
    done = apply(live, candidate, loads=_ok, checks={'loads': ['true']}, run=_green)
    assert done.changed == ('cycle.interval_s',)
    assert done.boundary == ()
    assert live.read_text(encoding='utf-8') == candidate
    assert done.backup is not None
    assert done.backup.read_text(encoding='utf-8') == LIVE


def test_a_sudo_list_change_is_refused_without_consent(tmp_path: Path) -> None:
    live = _live(tmp_path)
    candidate = LIVE.replace('status *"]', 'status *", "/bin/sh"]')
    with pytest.raises(ConfigRefused, match=r'ops\.access\.commands'):
        apply(live, candidate, loads=_ok, checks={}, run=_green)
    assert live.read_text(encoding='utf-8') == LIVE


def test_an_unlisted_key_is_boundary_by_default() -> None:
    assert boundary(('ops.python', 'components.shell_probe.commands', 'ops.repos')) == (
        'ops.python',
        'components.shell_probe.commands',
    )


def test_a_boundary_change_applies_only_with_consent_to_exactly_that_file(tmp_path: Path) -> None:
    live = _live(tmp_path)
    candidate = LIVE.replace('status *"]', 'status *", "/usr/bin/journalctl --no-pager -u gitea"]')

    def redeem_for(subject: str) -> Callable[[Mapping[str, Any], str], None]:
        def redeem(_credential: Mapping[str, Any], asked: str) -> None:
            if asked != subject:
                msg = 'the credential consents to another request'
                raise ConsentRefused(msg)

        return redeem

    with pytest.raises(ConsentRefused, match='another request'):
        apply(live, candidate, loads=_ok, checks={}, run=_green, redeem=redeem_for('0' * 64), credential={})
    assert live.read_text(encoding='utf-8') == LIVE
    done = apply(live, candidate, loads=_ok, checks={}, run=_green, redeem=redeem_for(digest(candidate)),
                 credential={})  # fmt: skip
    assert done.boundary == ('ops.access.commands',)
    assert live.read_text(encoding='utf-8') == candidate


def test_a_candidate_the_current_code_refuses_is_never_written(tmp_path: Path) -> None:
    live = _live(tmp_path)

    def refuses(_path: Path) -> object:
        msg = '[ops.breakglass] has unknown keys'
        raise ValueError(msg)

    with pytest.raises(ConfigRefused, match='current code refuses'):
        apply(live, LIVE.replace('60', '90'), loads=refuses, checks={}, run=_green)
    assert live.read_text(encoding='utf-8') == LIVE


def test_a_failed_self_check_restores_the_previous_file(tmp_path: Path) -> None:
    live = _live(tmp_path)

    def red(_argv: list[str]) -> tuple[int, str]:
        return 1, 'breakglass --help exploded'

    with pytest.raises(ConfigRefused, match='restored'):
        apply(live, LIVE.replace('60', '90'), loads=_ok, checks={'breakglass': ['x']}, run=red)
    assert live.read_text(encoding='utf-8') == LIVE


def test_changes_names_keys_added_removed_and_changed() -> None:
    assert changes({'a': {'b': 1, 'c': 2}}, {'a': {'b': 1, 'd': 3}}) == ('a.c', 'a.d')


def test_a_candidate_the_current_code_refuses_spends_no_credential(tmp_path: Path) -> None:
    """#555: the load check runs BEFORE the credential is redeemed, so a code is never spent on a refusal."""
    live = _live(tmp_path)
    candidate = LIVE.replace('status *"]', 'status *", "/usr/bin/journalctl --no-pager -u gitea"]')
    spent: list[str] = []

    def refuses(_path: Path) -> object:
        msg = "[ops] has unknown keys ['status']"
        raise ValueError(msg)

    with pytest.raises(ConfigRefused, match='upgrade first'):
        apply(live, candidate, loads=refuses, checks={}, run=_green,
              redeem=lambda _c, asked: spent.append(asked), credential={})  # fmt: skip
    assert spent == []
    assert live.read_text(encoding='utf-8') == LIVE
    # the control: a candidate the code loads redeems exactly once
    apply(live, candidate, loads=_ok, checks={}, run=_green,
          redeem=lambda _c, asked: spent.append(asked), credential={})  # fmt: skip
    assert spent == [digest(candidate)]
