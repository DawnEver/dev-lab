"""``ops forge protect plan|apply``: a host's site admin writes a repo's DECLARED branch protection.

The declaration is read at the ref through the forge (``manifest_at``) and rendered by the client's own renderer
(:func:`dev_lab.dev.forgeprotect.targets`); every test drives the in-memory Gitea of :mod:`_protect_fakes`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from _protect_fakes import GITEA_TEXT, FakeGitea

from dev_lab.dev import forgeprotect
from dev_lab.dev.forge import Forge as Remote
from dev_lab.ops import forgeaccounts, forgeprotection
from dev_lab.ops.config import Forge
from dev_lab.ops.consent.actions import ACTIONS, SINGLE
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.giteaadmin import ForgeRefused

REF = 'integrate/main'


def _role(tmp_path: Path) -> Forge:
    ini = tmp_path / 'app.ini'
    ini.write_text('APP_NAME = g\n[server]\nROOT_URL = https://gitea.example/\nDOMAIN = other\n', encoding='utf-8')
    return Forge(api='http://127.0.0.1:3000', admin='site-admin', config=str(ini), log=str(tmp_path / 'forge.jsonl'),
                 accounts={'forge-breakglass': {'role': 'breakglass', 'repos': ['owner/alpha']}})  # fmt: skip


def _gitea(text: str = GITEA_TEXT) -> FakeGitea:
    return FakeGitea(repo='/repos/owner/alpha', manifest={REF: text})


def _consent(subject: str) -> Callable[[object, str], None]:
    def redeem(_credential: object, asked: str) -> None:
        if asked != subject:
            msg = 'the credential names another subject'
            raise ConsentRefused(msg)

    return redeem


def test_the_action_is_a_single_use_registry_row() -> None:
    assert ACTIONS[forgeprotection.ACTION].scope == SINGLE


def test_the_host_is_the_one_its_app_ini_root_url_names(tmp_path: Path) -> None:
    assert forgeprotection.public_host(_role(tmp_path)) == 'gitea.example'


def test_plan_is_the_clients_rendering_of_the_declaration_at_the_ref(tmp_path: Path) -> None:
    """One renderer: the targets and steps are exactly what the client's door makes of the same text and forge."""
    gitea = _gitea()
    found = forgeprotection.rendered(_role(tmp_path), gitea, 'owner/alpha', REF)
    remote = Remote('gitea.example', 'owner', 'alpha')
    assert found.wanted == forgeprotect.targets(GITEA_TEXT, 'p', remote)
    steps = forgeprotection.plan(gitea, found)
    assert [step.subject for step in steps] == [step.subject for step in forgeprotect.plan(gitea, remote, found.wanted)]
    assert len(steps) == 2
    assert gitea.writes == []


def test_an_undeclared_repo_is_refused_before_the_forge_is_asked(tmp_path: Path) -> None:
    """PLANTED beside its control: on the same unreachable forge a declared repo gets PAST the check to the read."""
    with pytest.raises(ForgeRefused, match=r'owner/beta is not declared'):
        forgeprotection.rendered(_role(tmp_path), FakeGitea(repo='/repos/owner/beta', down=True), 'owner/beta', REF)
    with pytest.raises(ForgeRefused, match='cannot be read'):
        forgeprotection.rendered(_role(tmp_path), FakeGitea(repo='/repos/owner/alpha', down=True), 'owner/alpha', REF)


def test_apply_writes_the_consented_protection_and_audits_it(tmp_path: Path) -> None:
    role, gitea = _role(tmp_path), _gitea()
    found = forgeprotection.rendered(role, gitea, 'owner/alpha', REF)
    left = forgeprotection.apply(gitea, found, redeem=_consent(found.subject()), credential={}, log=role.log, by='root')
    assert left == []
    assert set(gitea.protections) == {'integrate/main', 'main'}
    audit = [json.loads(line) for line in Path(role.log).read_text(encoding='utf-8').splitlines()]
    assert audit[-1] | {'at': ''} == {'at': '', 'by': 'root', 'action': forgeprotection.ACTION, 'repo': 'owner/alpha',
                                      'ref': REF, 'protection': found.digest(), 'wrote': 2, 'left': 0}  # fmt: skip


def test_a_grant_for_another_protection_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    role = _role(tmp_path)
    granted = forgeprotection.rendered(role, _gitea(), 'owner/alpha', REF).subject()
    gitea = _gitea(GITEA_TEXT.replace('promote-bot', 'other-bot'))
    widened = forgeprotection.rendered(role, gitea, 'owner/alpha', REF)
    with pytest.raises(ConsentRefused):
        forgeprotection.apply(gitea, widened, redeem=_consent(granted), credential={}, log=role.log, by='root')
    assert gitea.protections == {}


def test_the_subject_binds_repo_ref_and_rendered_protection(tmp_path: Path) -> None:
    base = forgeprotection.rendered(_role(tmp_path), _gitea(), 'owner/alpha', REF)
    others = {
        forgeprotection.Protection('owner/other', base.ref, base.remote, base.wanted).subject(),
        forgeprotection.Protection(base.repo, 'main', base.remote, base.wanted).subject(),
        forgeprotection.Protection(base.repo, base.ref, base.remote, base.wanted[:1]).subject(),
    }
    assert len(others) == 3
    assert base.subject() not in others


def _args(verb: str, *, credential: str = '', subject: bool = False) -> argparse.Namespace:
    return argparse.Namespace(kind='protect', action=verb, repo='owner/alpha', ref=REF, credential=credential,
                              subject=subject)  # fmt: skip


def _never() -> Callable[[str], Callable[[object, str], None]]:
    pytest.fail('no consent is read')


def test_plan_needs_no_consent_and_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gitea = _gitea()
    assert forgeprotection.run(_role(tmp_path), _args('plan'), _never, api_for=lambda _repo: gitea) == 0
    assert '2 difference(s)' in capsys.readouterr().out
    assert gitea.writes == []


def test_apply_without_a_credential_is_refused_naming_its_subject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gitea = _gitea()
    found = forgeprotection.rendered(_role(tmp_path), gitea, 'owner/alpha', REF)
    assert forgeprotection.run(_role(tmp_path), _args('apply'), _never, api_for=lambda _repo: gitea) == 2
    assert found.subject() in capsys.readouterr().err
    assert forgeprotection.run(_role(tmp_path), _args('apply', subject=True), _never, api_for=lambda _repo: gitea) == 0
    assert capsys.readouterr().out.strip() == found.subject()
    assert gitea.writes == []


def test_apply_with_its_credential_writes_and_exits_clean(tmp_path: Path) -> None:
    gitea, role = _gitea(), _role(tmp_path)
    found = forgeprotection.rendered(role, gitea, 'owner/alpha', REF)
    granted = tmp_path / 'grant.json'
    granted.write_text('{}', encoding='utf-8')
    asked: list[str] = []

    def redeem_for() -> Callable[[str], Callable[[object, str], None]]:
        return lambda action: asked.append(action) or _consent(found.subject())

    assert forgeprotection.run(role, _args('apply', credential=str(granted)), redeem_for,
                               api_for=lambda _repo: gitea) == 0  # fmt: skip
    assert asked == [forgeprotection.ACTION]
    assert set(gitea.protections) == {'integrate/main', 'main'}


def test_the_ops_parser_takes_the_verb_with_its_default_ref() -> None:
    parser = argparse.ArgumentParser()
    forgeaccounts.add_parser(parser.add_subparsers(dest='verb'))
    args = parser.parse_args(['forge', 'protect', 'apply', '--repo', 'owner/alpha', '--subject'])
    assert (args.kind, args.action, args.repo, args.ref, args.subject) == ('protect', 'apply', 'owner/alpha', REF, True)


def test_the_local_api_door_raises_on_a_refused_status() -> None:
    calls: list[tuple[str, str]] = []

    def api(method: str, path: str, *, body: dict[str, object] | None = None) -> tuple[int, object]:
        calls.append((method, path))
        assert body is None or method != 'GET'
        return (403, None) if method == 'PATCH' else (200, [])

    door = forgeprotection.LocalRepo('owner/alpha', api)
    assert door.call('GET', f'{door.repo}/branch_protections') == []
    with pytest.raises(ForgeRefused, match='HTTP 403'):
        door.call('PATCH', f'{door.repo}/branch_protections/main', {})
    assert calls[0] == ('GET', '/repos/owner/alpha/branch_protections')
