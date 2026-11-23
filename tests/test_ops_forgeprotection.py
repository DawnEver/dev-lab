"""``ops forge protect plan|apply``: a host's site admin writes a repo's DECLARED branch protection.

The declaration is read at the ref through the forge (``manifest_at``) and rendered by the client's own renderer
(:func:`dev_lab.dev.forgeprotect.targets`); every test drives the in-memory Gitea of :mod:`_protect_fakes`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from _protect_fakes import GITEA_TEXT, FakeGitea

from dev_lab.dev import forgeprotect
from dev_lab.dev.forge import Forge as Remote
from dev_lab.dev.forgefailure import Answer
from dev_lab.dev.roles import ROLES, ROLES_ENV
from dev_lab.ops import forgeaccounts, forgeprotection, redeemverbs
from dev_lab.ops.config import ConfigSource, Forge
from dev_lab.ops.consent.actions import ACTIONS, SINGLE
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.giteaadmin import ForgeRefused, local_api

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


def _scripted(*answers: Answer | OSError) -> tuple[Callable[..., Answer], list[float], list[int]]:
    queue, sleeps, made = list(answers), [], []

    def exchange(*_: object) -> Answer:
        made.append(1)
        step = queue.pop(0)
        if isinstance(step, OSError):
            raise step
        return step

    return exchange, sleeps, made


def test_the_local_api_retries_a_transient_through_the_one_forge_loop() -> None:
    exchange, sleeps, made = _scripted(Answer(502, b''), OSError('reset'), Answer(200, b'{"id": 3}'))
    assert local_api('GET', 'http://g/api/v1/x', 't', None, exchange=exchange, sleep=sleeps.append) == (200, {'id': 3})
    assert len(made) == 3
    assert len(sleeps) == 2


def test_the_local_api_returns_a_refusal_at_once_and_an_unreached_forge_as_0() -> None:
    """PLANTED CONTROL: a 404 or a refused admin token is one attempt; a forge never reached reads 0 after the bound."""
    for status in (401, 404):
        exchange, sleeps, made = _scripted(Answer(status, b''))
        assert local_api('GET', 'http://g/api/v1/x', 't', None, exchange=exchange, sleep=sleeps.append) == (
            status,
            None,
        )
        assert (len(made), sleeps) == (1, [])
    exchange, sleeps, made = _scripted(*[OSError('down')] * 5)
    assert local_api('GET', 'http://g/api/v1/x', 't', None, exchange=exchange, sleep=sleeps.append) == (0, None)
    assert len(made) == 3


def test_the_local_subject_is_the_one_the_host_prints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A workstation reading the same declaration at the same ref derives the host's ``apply --subject``.

    PLANTED: another ref (whose declaration differs) or another declaration at the same ref changes it.
    """
    other = GITEA_TEXT.replace('promote-bot', 'other-bot')
    gitea = FakeGitea(repo='/repos/owner/alpha', manifest={REF: GITEA_TEXT, 'main': other})
    assert forgeprotection.run(_role(tmp_path), _args('apply', subject=True), _never, api_for=lambda _r: gitea) == 0
    on_host = capsys.readouterr().out.strip()
    texts = {REF: GITEA_TEXT, 'main': other}
    here = forgeprotection.local_subject('owner/alpha', REF, 'gitea.example', texts.__getitem__)
    assert here == on_host
    assert forgeprotection.local_subject('owner/alpha', 'main', 'gitea.example', texts.__getitem__) != on_host
    assert forgeprotection.local_subject('owner/alpha', REF, 'gitea.example', lambda _ref: other) != on_host
    assert forgeprotection.local_subject('owner/alpha', 'main', 'gitea.example', lambda _ref: GITEA_TEXT) != on_host


# -- the roles a host renders under: the family file its own config places --------------------------------------------

#: A family file binding every role of a Gitea repo to the forge's CI: the kinds every test here carries.
FAMILY = '[roles.gitea]\n' + ''.join(f'{role} = "ci"\n' for role in ROLES)


def _source(tmp_path: Path, *, family: bool = True) -> ConfigSource:
    """A host's ``[ops.config]``; its family ``to`` lies under *tmp_path* (a stand-in: this box's path has a drive)."""
    if not family:
        return ConfigSource('https://gitea.example/owner/hosts.git', 'hosts/h.toml', '/etc/token')
    placed = {'file': 'family.toml', 'to': str(tmp_path / 'etc' / 'family.toml')}
    return cast('ConfigSource', SimpleNamespace(family=placed))


def _placed(tmp_path: Path, text: str = FAMILY) -> ConfigSource:
    source = _source(tmp_path)
    Path(source.family['to']).parent.mkdir(parents=True)
    Path(source.family['to']).write_text(text, encoding='utf-8')
    return source


def test_the_host_renders_under_the_family_file_its_config_places_not_the_logins_machine_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Measured 2026-11-22: ``sudo ... forge protect apply`` ran as root, whose machine file holds no family layer.

    The granted step was refused ("no family layer on this machine") though ``[ops.config] family`` had placed the
    family file. PLANTED CONTROL: with no layer handed in, the same login (no roles carried) is still refused.
    """
    carried = forgeprotection.rendered(_role(tmp_path), _gitea(), 'owner/alpha', REF).subject()
    monkeypatch.delenv(ROLES_ENV)  # root under sudo: an empty machine file, no render's kinds
    monkeypatch.delenv('CI', raising=False)  # sudo is no CI job; under a runner's CI the stale-workflow door speaks
    with pytest.raises(ForgeRefused, match='no family layer on this machine'):
        forgeprotection.rendered(_role(tmp_path), _gitea(), 'owner/alpha', REF)
    layer = forgeprotection.family_layer(_placed(tmp_path))
    assert forgeprotection.rendered(_role(tmp_path), _gitea(), 'owner/alpha', REF, layer=layer).subject() == carried
    gitea = _gitea()
    args = _args('apply', subject=True)
    assert forgeprotection.run(_role(tmp_path), args, _never, api_for=lambda _repo: gitea, layer=layer) == 0
    assert capsys.readouterr().out.strip() == carried  # the subject a workstation derives is unchanged


def test_a_host_declaring_no_family_file_is_refused_naming_the_declaration(tmp_path: Path) -> None:
    """PLANTED CONTROL: the declared, placed file is read; a declared file not yet placed names its path."""
    for undeclared in (None, _source(tmp_path, family=False)):
        with pytest.raises(ForgeRefused, match=r'declares no \[ops.config\] family'):
            forgeprotection.family_layer(undeclared)
    with pytest.raises(ForgeRefused, match=r'family.toml \(\[ops.config\] family.to\) cannot be read'):
        forgeprotection.family_layer(_source(tmp_path))
    assert set(forgeprotection.family_layer(_placed(tmp_path))['roles']['gitea']) == set(ROLES)


def test_the_ops_door_hands_the_verb_the_placed_family_and_refuses_the_subject_read_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--subject`` (what a preflight asks) takes the same door as ``apply``: no family, no subject, exit 2."""
    seen: list[object] = []

    def ran(_role: object, _args: object, _redeem: object, *, layer: object) -> int:
        seen.append(layer)
        return 0

    monkeypatch.setattr(forgeprotection, 'run', ran)
    args = _args('apply', subject=True)
    bare = SimpleNamespace(forge=_role(tmp_path), config_source=_source(tmp_path, family=False), path='h.toml')
    assert redeemverbs.forge_verb(bare, args) == 2
    assert 'refused: this host declares no [ops.config] family' in capsys.readouterr().err
    assert seen == []
    host = SimpleNamespace(forge=_role(tmp_path), config_source=_placed(tmp_path), path='h.toml')
    assert redeemverbs.forge_verb(host, args) == 0  # the control
    assert seen == [forgeprotection.family_layer(host.config_source)]


def test_a_placed_family_file_binding_no_role_for_the_forge_names_itself_and_config_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A host ALREADY running the fix but holding stale placed data says so, by the placed path and its door.

    Measured 2026-11-22: it still said the workstation's "no family layer on this machine and no DEV_LAB_ROLES
    carried". Empty, role-less or bound for another forge, the placed file is named -- never a machine file.

    PLANTED CONTROL: the placed file that binds the forge's roles is handed to the verb.
    """
    monkeypatch.delenv(ROLES_ENV)
    monkeypatch.delenv('CI', raising=False)
    role = _role(tmp_path)
    for stale in ('', '[storage]\nkind = "x"\n', FAMILY.replace('[roles.gitea]', '[roles.github]')):
        source = _placed(tmp_path / str(len(stale)), stale)
        with pytest.raises(ForgeRefused) as refused:
            forgeprotection.bound_layer(source, role, 'owner/alpha')
        said = str(refused.value)
        assert 'binds no role for gitea/owner/alpha' in said
        assert source.family['to'] in said
        assert '`ops config apply`' in said
        assert 'on this machine' not in said
        assert ROLES_ENV not in said
    host = SimpleNamespace(forge=role, config_source=_placed(tmp_path / 'empty', ''), path='h.toml')
    assert redeemverbs.forge_verb(host, _args('apply', subject=True)) == 2  # what a preflight asks: told with no code
    assert 'binds no role for gitea/owner/alpha' in capsys.readouterr().err
    bound = forgeprotection.bound_layer(_placed(tmp_path / 'good'), role, 'owner/alpha')  # the control
    assert set(bound['roles']['gitea']) == set(ROLES)
    by_repo = '[roles.repos."owner/alpha"]\n' + ''.join(f'{name} = "ci"\n' for name in ROLES)
    assert forgeprotection.bound_layer(_placed(tmp_path / 'repo', by_repo), role, 'owner/alpha')
