"""WRITE-OUTSIDE-ROOTS: every rule with one allowed and one refused (planted) case."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import writeroots
from dev_lab.dev.writeroots import Policy, refusal


@pytest.fixture
def world(tmp_path: Path) -> tuple[Policy, Path, Path]:
    """A machine with one repo, one agent repo, Claude's home and a OneDrive tree."""
    repo, home, user = tmp_path / 'repo', tmp_path / 'home', tmp_path / 'user'
    tracked = {repo / 'src' / 'kept.py'}

    def repo_of(path: Path) -> Path | None:
        return repo if path == repo or repo in path.parents else None

    def allowed(path: Path) -> bool:
        return any(path == root or root in path.parents for root in (home, repo / 'output', repo / 'scratch'))

    def exempt(path: Path) -> bool:
        return any(root in path.parents for root in (user / '.claude', tmp_path / 'cc-config'))

    policy = Policy(
        allowed=allowed,
        exempt=exempt,
        repo_of=repo_of,
        tracked=lambda path: path in tracked,
        consent=(user / 'OneDrive - Uni',),
    )
    return policy, repo, user


def _write(path: Path) -> dict[str, object]:
    return {'tool_name': 'Write', 'tool_input': {'file_path': str(path)}}


def _shell(command: str, cwd: Path) -> dict[str, object]:
    return {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(cwd)}


def test_a_write_into_output_passes_and_one_outside_every_root_is_refused(world) -> None:
    policy, repo, user = world
    assert refusal(_write(repo / 'output' / 'logs' / '26' / 'r.json'), policy) is None
    assert 'WRITE-OUTSIDE-ROOTS' in refusal(_write(user / 'tmp' / 'r.json'), policy)


def test_development_inside_a_repo_passes_and_a_tracked_edit_passes(world) -> None:
    policy, repo, _ = world
    assert refusal({'tool_name': 'Edit', 'tool_input': {'file_path': str(repo / 'src' / 'kept.py')}}, policy) is None
    assert refusal(_write(repo / 'src' / 'new_module.py'), policy) is None


def test_scratch_takes_a_dated_script_and_refuses_anything_else(world) -> None:
    policy, repo, _ = world
    assert refusal(_write(repo / 'scratch' / '26' / '11' / '03' / 'probe' / 'leak.py'), policy) is None
    assert 'SCRATCH' in refusal(_write(repo / 'scratch' / 'leak.py'), policy)  # planted: undated
    assert 'SCRATCH' in refusal(_write(repo / 'scratch' / '26' / '11' / '03' / 'probe' / 'rows.json'), policy)


def test_output_refuses_a_script(world) -> None:
    policy, repo, _ = world
    assert refusal(_write(repo / 'output' / 'logs' / 'run.log'), policy) is None
    assert 'OUTPUT' in refusal(_write(repo / 'output' / 'tmp' / 'probe.py'), policy)


def test_onedrive_needs_consent_and_names_it(world) -> None:
    policy, _, user = world
    message = refusal(_write(user / 'OneDrive - Uni' / 'Sync' / 'x.json'), policy)
    assert 'consent' in message


def test_claude_homes_and_agent_repos_are_outside_the_policy(world, tmp_path: Path) -> None:
    policy, _, user = world
    assert refusal(_write(user / '.claude' / 'settings.json'), policy) is None
    assert refusal(_write(tmp_path / 'cc-config' / 'hooks' / 'a.js'), policy) is None


def test_a_notebook_edit_is_judged_by_its_path(world) -> None:
    policy, repo, user = world
    assert (
        refusal(
            {'tool_name': 'NotebookEdit', 'tool_input': {'notebook_path': str(repo / 'output' / 'a.ipynb')}}, policy
        )
        is None
    )
    assert refusal({'tool_name': 'NotebookEdit', 'tool_input': {'notebook_path': str(user / 'a.ipynb')}}, policy)


@pytest.mark.parametrize(
    'command',
    [
        'echo x > {out}/a.log',
        'python probe.py >> {out}/b.log',
        'tee {out}/c.log',
        'Out-File -FilePath {out}/d.log',
        'mkdir -p {out}/runs',
        'cp a.txt {out}/e.txt',
        'echo x > /dev/null',
        'ls {away} > {out}/listing.txt',
    ],
)
def test_a_shell_write_inside_the_roots_passes(world, command: str) -> None:
    policy, repo, user = world
    text = command.format(out=(repo / 'output').as_posix(), away=user.as_posix())
    assert refusal(_shell(text, repo), policy) is None


@pytest.mark.parametrize(
    'command',
    [
        'echo x > {away}/a.log',
        'python probe.py >> {away}/b.log',
        'cat a | tee -a {away}/c.log',
        'Set-Content -Path {away}/d.txt -Value 1',
        'mkdir -p {away}/runs',
        'mv a.txt {away}/e.txt',
        'Copy-Item a.txt -Destination {away}/f.txt',
        "python -c \"open('{away}/g.json', 'w').write('1')\"",
        'echo x > rel.log',
    ],
)
def test_a_shell_write_outside_the_roots_is_refused(world, command: str) -> None:
    policy, repo, user = world
    text = command.format(away=user.as_posix())
    cwd = repo / 'src' if 'rel.log' not in command else user
    assert 'WRITE-OUTSIDE-ROOTS' in refusal(_shell(text, cwd), policy)


def test_main_exits_2_with_the_refusal_and_0_when_allowed(world, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    policy, repo, user = world
    monkeypatch.setattr(writeroots, 'machine_policy', lambda: policy)
    assert writeroots.main(stdin=io.StringIO(json.dumps(_write(user / 'x.txt')))) == 2
    assert 'WRITE-OUTSIDE-ROOTS' in capsys.readouterr().err
    assert writeroots.main(stdin=io.StringIO(json.dumps(_write(repo / 'output' / 'x.txt')))) == 0
    assert writeroots.main(stdin=io.StringIO('not json')) == 0  # a payload it cannot read is not its to judge
