"""WRITE-OUTSIDE-ROOTS: every rule with one allowed and one refused (planted) case."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import disclosure, writeroots
from dev_lab.dev.writeroots import Policy, verdict


def refusal(payload: dict[str, object], policy: Policy) -> str | None:
    """The text of *payload*'s verdict, or ``None`` when it is allowed."""
    found = verdict(payload, policy)
    return None if found is None else found.text


@pytest.fixture
def world(tmp_path: Path) -> tuple[Policy, Path, Path]:
    """A machine with one repo, one agent repo, Claude's home and a OneDrive tree."""
    repo, home, user = tmp_path / 'repo', tmp_path / 'home', tmp_path / 'user'
    tracked = {repo / 'src' / 'kept.py'}
    links = {repo / 'output' / 'escape': user / 'away'}  # a junction out of output/

    def real(path: Path) -> Path:
        for link, target in links.items():
            if path == link or link in path.parents:
                return target / path.relative_to(link)
        return path

    def within(path: Path, root: Path) -> bool:
        path, root = real(path), real(root)
        return path == root or root in path.parents

    def repo_of(path: Path) -> Path | None:
        return repo if within(path, repo) else None

    def allowed(path: Path) -> bool:
        return any(within(path, root) for root in (home, repo / 'output', repo / 'scratch'))

    def exempt(path: Path) -> bool:
        return any(within(path, root) for root in (user / '.claude', tmp_path / 'cc-config'))

    policy = Policy(
        allowed=allowed,
        exempt=exempt,
        repo_of=repo_of,
        tracked=lambda path: path in tracked,
        consent=(user / 'OneDrive - Uni',),
        within=within,
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
    assert 'scratch/ holds scripts only' in refusal(_write(repo / 'scratch' / 'leak.py'), policy)  # planted: undated
    assert 'scratch/ holds scripts only' in refusal(
        _write(repo / 'scratch' / '26' / '11' / '03' / 'probe' / 'rows.json'), policy
    )


def test_output_refuses_a_script(world) -> None:
    policy, repo, _ = world
    assert refusal(_write(repo / 'output' / 'logs' / 'run.log'), policy) is None
    assert 'output/ holds outputs only' in refusal(_write(repo / 'output' / 'tmp' / 'probe.py'), policy)


def test_a_synced_folder_asks_the_user_for_that_one_write(world) -> None:
    policy, _, user = world
    found = verdict(_write(user / 'OneDrive - Uni' / 'Sync' / 'x.json'), policy)
    assert found is not None
    assert found.decision == 'ask'
    assert verdict(_write(user / 'Elsewhere' / 'x.json'), policy).decision == 'deny'  # planted: not synced


def test_a_link_out_of_output_is_judged_by_where_it_leads(world) -> None:
    policy, repo, _ = world
    assert refusal(_write(repo / 'output' / 'logs' / 'r.json'), policy) is None
    assert refusal(_write(repo / 'output' / 'escape' / 'r.json'), policy) is not None  # planted: the junction


@pytest.mark.parametrize('word', ['/c/tmp/x.json', '/cygdrive/c/tmp/x.json', '//c/tmp/x.json', '/C/tmp/x.json'])
def test_every_git_bash_spelling_of_a_drive_maps_on_windows_only(word: str) -> None:
    assert writeroots._drive_path(word, 'win32') == 'C:/tmp/x.json'
    assert writeroots._drive_path(word, 'linux') == word  # off Windows a path is what it says


def test_a_git_bash_write_is_judged_at_its_drive_path(world, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, repo, user = world

    def drive(root: Path) -> Callable[[str, str], str]:
        return lambda word, _platform: word.replace('/x/', f'{root.as_posix()}/', 1)

    monkeypatch.setattr(writeroots, '_drive_path', drive(repo))
    assert refusal(_shell('echo 1 > /x/output/a.log', user), policy) is None  # a Git Bash spelling of output/
    monkeypatch.setattr(writeroots, '_drive_path', drive(user))
    assert refusal(_shell('echo 1 > /x/tmp/a.log', user), policy) is not None  # planted: /c/tmp


@pytest.mark.parametrize(
    'payload',
    [
        {'tool_name': 'Write', 'tool_input': {'file_path': 'C:/Users/u/elsewhere/r.json'}},
        {'tool_name': 'Write', 'tool_input': {'file_path': 'C:/w/repo/scratch/leak.py'}},
        {'tool_name': 'Write', 'tool_input': {'file_path': 'C:/w/repo/output/probe.py'}},
    ],
)
def test_every_refusal_fits_the_refusal_budget(payload: dict[str, object]) -> None:
    repo = Path('C:/w/repo')

    def inside(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

    policy = Policy(
        allowed=lambda path: inside(path, repo / 'output'),
        exempt=lambda _path: False,
        repo_of=lambda path: repo if inside(path, repo) else None,
        tracked=lambda _path: False,
        consent=(),
        within=inside,
    )
    text = refusal(payload, policy)
    assert text is not None
    assert disclosure.problems(text, 'refusal') == []
    assert text.splitlines()[-1] == disclosure.details_for('WRITE-OUTSIDE-ROOTS')


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


def test_main_asks_on_stdout_for_a_synced_folder(world, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, _, user = world
    monkeypatch.setattr(writeroots, 'machine_policy', lambda: policy)
    out = io.StringIO()
    payload = io.StringIO(json.dumps(_write(user / 'OneDrive - Uni' / 'x.json')))
    assert writeroots.main(stdin=payload, stdout=out) == 0
    decision = json.loads(out.getvalue())['hookSpecificOutput']
    assert decision['permissionDecision'] == 'ask'
    assert decision['hookEventName'] == 'PreToolUse'
