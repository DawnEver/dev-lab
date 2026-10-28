"""REPO-AUTOMODE: ``.claude/automode.json`` is machine-local, derived, gitignored, and never committed.

PLANTED CONTROLS: a checkout without the family ignore line DOES track the file; the leak scan DOES see a planted
host; a machine file with no registry writes nothing and says why.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.hpc.grants import Grant

from dev_lab.dev._famconfig_rows import GITIGNORE_CLAUDE_SECTION
from dev_lab.dev.autodoors import claude_rows, codex_rules, doors
from dev_lab.dev.automode import (
    AUTOMODE_REL,
    ENVIRONMENT,
    INTENTS,
    OPTIONAL_INTENTS,
    Fleet,
    SourcesUnavailable,
    automode,
    leaks,
    main,
    read_fleet,
    refresh,
    spelled_commands,
)
from dev_lab.dev.dep import _refresh_automode
from dev_lab.dev.famtests.visibility import plant_checkout

_GIT = shutil.which('git') or 'git'

_FLEET = Fleet(
    workstations=(
        {'name': 'G', 'computer': 'G', 'address': '192.0.2.1', 'roles': ['client', 'node', 'forge']},
        {'name': 'WS1', 'computer': 'BOXONE', 'address': 'boxone.example.ac.uk', 'roles': ['client', 'node']},
    ),
    grants=(
        Grant(user='alice9', hosts=('login1.example.ac.uk', 'login2.example.ac.uk'), slurm_account='acct'),
        Grant(user='alice9', hosts=('login1.example.ac.uk',), slurm_account='other'),
        Grant(user='bob7', hosts=('login2.example.ac.uk',), slurm_account='acct'),
    ),
)

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.dev_lab.branchset]
trunk = "main"
sessions = ["integrate/main"]
{extra}"""


def _repo(tmp_path: Path, extra: str = '', *, ignore: tuple[str, ...] = GITIGNORE_CLAUDE_SECTION) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = plant_checkout(tmp_path, trunk='main').work
    (work / 'pyproject.toml').write_text(_MANIFEST.format(extra=extra), encoding='utf-8')
    (work / '.gitignore').write_text('\n'.join(ignore) + '\n', encoding='utf-8')
    subprocess.run(
        [_GIT, '-C', str(work), 'remote', 'set-url', 'origin', 'https://forge.example/Team/planted.git'], check=True
    )
    return work


def _tracked_after_add(work: Path) -> list[str]:
    subprocess.run([_GIT, '-C', str(work), 'add', '.'], check=True)
    return subprocess.run(
        [_GIT, '-C', str(work), 'ls-files'], check=True, capture_output=True, text=True, encoding='utf-8'
    ).stdout.splitlines()


def test_the_rendered_file_is_gitignored_and_never_listed(tmp_path: Path) -> None:
    work = _repo(tmp_path / 'family')
    assert refresh(work, say=lambda _l: None, fleet=_FLEET)
    assert (work / AUTOMODE_REL).is_file()
    assert subprocess.run([_GIT, '-C', str(work), 'check-ignore', '-q', AUTOMODE_REL], check=False).returncode == 0
    assert AUTOMODE_REL not in _tracked_after_add(work)


def test_planted_without_the_family_ignore_the_file_would_be_tracked(tmp_path: Path) -> None:
    """PLANTED CONTROL: the ls-files check above can see the file when nothing ignores it."""
    work = _repo(tmp_path / 'bare', ignore=('# nothing',))
    refresh(work, say=lambda _l: None, fleet=_FLEET)
    assert AUTOMODE_REL in _tracked_after_add(work)


def test_the_render_equals_its_sources(tmp_path: Path) -> None:
    rendered = automode(_repo(tmp_path), _FLEET)['autoMode']
    for key in ('environment', 'allow'):
        assert rendered[key][0] == '$defaults', key
        assert spelled_commands(rendered[key][1:]) == (), key
    environment = ' '.join(rendered['environment'])
    for fact in ('G (computer G; address 192.0.2.1', 'serves the forge', 'WS1 (computer BOXONE'):
        assert fact in environment
    assert (
        'account alice9 at login hosts login1.example.ac.uk, login2.example.ac.uk (Slurm account acct)' in environment
    )
    assert 'account bob7 at login hosts login2.example.ac.uk' in environment
    assert environment.count('account alice9') == 1, 'one line per account, its first grant'
    assert rendered['allow'][1:] == list(INTENTS.values())


def test_an_optional_intent_renders_only_where_declared_and_an_unknown_one_is_refused(tmp_path: Path) -> None:
    plain = automode(_repo(tmp_path / 'a'), _FLEET)['autoMode']['allow']
    jmag = '\n[tool.dev_lab.automode]\ndeclares = ["jmag-material-card"]\n'
    declared = automode(_repo(tmp_path / 'b', jmag), _FLEET)['autoMode']['allow']
    assert OPTIONAL_INTENTS['jmag-material-card'] not in plain
    assert OPTIONAL_INTENTS['jmag-material-card'] in declared
    with pytest.raises(ValueError, match='anything-goes'):
        automode(_repo(tmp_path / 'c', '\n[tool.dev_lab.automode]\ndeclares = ["anything-goes"]\n'), _FLEET)


def _committed() -> list[str]:
    """Every committed text the kit renders into a repo or ships: categories, toolchain facts, the door table."""
    return [
        *INTENTS.values(),
        *OPTIONAL_INTENTS.values(),
        *ENVIRONMENT,
        *doors().values(),
        *claude_rows(),
        codex_rules(),
    ]


def test_no_committed_kit_text_carries_a_fleet_fact() -> None:
    assert leaks(_committed(), _FLEET) == ()
    try:
        here = read_fleet()
    except SourcesUnavailable:
        return  # no fleet on this box: the host SHAPES above were still scanned
    assert leaks(_committed(), here) == ()


def test_the_leak_scan_sees_a_planted_fleet_fact() -> None:
    """PLANTED CONTROL: a category carrying a host, an address or an account is caught."""
    assert leaks(['restart WS1 nightly'], _FLEET) == ('WS1',)
    assert leaks(['deploy alice9 there'], _FLEET) == ('alice9',)
    assert '192.0.2.9' in leaks(['reach 192.0.2.9'])
    assert 'login1.cluster.example.ac.uk' in leaks(['on login1.cluster.example.ac.uk'])


def test_an_unreadable_source_writes_nothing_and_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a machine file with no registry -- a cluster login node -- is inconclusive, by name."""
    work = _repo(tmp_path)
    machine = tmp_path / 'config.toml'
    machine.write_text('[hpc]\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    with pytest.raises(SourcesUnavailable, match='registry'):
        read_fleet()
    said: list[str] = []
    assert refresh(work, say=said.append) is False
    assert not (work / AUTOMODE_REL).exists()
    assert len(said) == 1
    assert 'not written' in said[0]
    assert 'registry' in said[0]
    payload = io.StringIO(json.dumps({'cwd': str(work)}))
    assert main(['session-start'], stdin=payload) == 0, 'a session never fails to start over it'
    assert not (work / AUTOMODE_REL).exists()


def test_the_dependency_door_renders_it_in_its_own_process(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    _refresh_automode(tmp_path, run=lambda argv, **_kw: calls.append(list(argv)))
    ((*_, module, verb, flag, repo),) = calls
    assert (module, verb, flag, repo) == ('dev_lab.dev.automode', 'write', '--repo', str(tmp_path))


#: The SHAPES a real fleet fact takes in this family: a private (RFC 1918) address, a university AD or Ada host.
_TREE_SHAPES = re.compile(
    r'\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b'
    r'|\b[\w-]+(?:\.[\w-]+)*\.(?:ada|ad)\.nottingham\.ac\.uk\b',
    re.IGNORECASE,
)


def _tree_leaks(texts: dict[str, str], fleet: Fleet | None) -> list[str]:
    """``path: fact`` for every fleet SHAPE, and every fleet name of 4+ characters as a whole word, in *texts*."""
    names: set[str] = set()
    for entry in fleet.workstations if fleet else ():
        names |= {str(entry.get(key)) for key in ('name', 'computer', 'address') if entry.get(key)}
    for grant in fleet.grants if fleet else ():
        names |= {grant.user, *grant.hosts}
    words = [re.compile(rf'(?<![\w.-]){re.escape(n)}(?![\w-])', re.IGNORECASE) for n in names if len(n) >= 4]
    found = []
    for path, text in texts.items():
        found += [f'{path}: {m.group(0)}' for m in _TREE_SHAPES.finditer(text)]
        found += [f'{path}: {w.pattern}' for w in words if w.search(text)]
    return found


def _tracked_texts() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    listed = (
        subprocess.run(
            [_GIT, 'ls-files', '-z', '--', 'src', 'tests', 'docs-src'], cwd=root, capture_output=True, check=True
        )
        .stdout.decode('utf-8')
        .split('\0')
    )
    texts = {}
    for rel in filter(None, listed):
        try:
            texts[rel] = (root / rel).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
    return texts


def test_no_tracked_file_carries_a_fleet_fact() -> None:
    """FLEET-FACTS-UNCOMMITTED: hosts.json and the machine file are the one source; a tracked copy is a second."""
    texts = _tracked_texts()
    assert len(texts) > 100, 'FLOOR: the scan read the tree'
    try:
        here: Fleet | None = read_fleet()
    except SourcesUnavailable:
        here = None  # no fleet on this box: the SHAPES are still scanned
    assert _tree_leaks(texts, here) == []


def test_the_tree_scan_sees_a_planted_fleet_fact() -> None:
    """PLANTED CONTROL: each shape, and a fleet name, is caught; a TEST-NET address and an example host are not."""
    planted = {
        'a': 'reach 10.' + '1.2.3',
        'b': 'reach 172.' + '20.0.1',
        'c': 'reach 192.' + '168.4.5',
        'd': 'ssh login1.' + 'ada.nottingham.ac.uk',
        'e': 'box ws.' + 'ad.nottingham.ac.uk',
        'f': 'deploy alice9 there',
    }
    assert len(_tree_leaks(planted, _FLEET)) == 6
    assert _tree_leaks({'g': 'reach 192.0.2.7 on login1.example'}, _FLEET) == []


def test_write_outside_a_checkout_says_why_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['write', '--repo', str(tmp_path)]) == 1
    assert 'not inside a git checkout' in capsys.readouterr().err


def test_a_host_name_is_a_leak_whatever_its_case() -> None:
    assert leaks(['ssh WS1.Example.AC.UK']) == ('WS1.Example.AC.UK',)
