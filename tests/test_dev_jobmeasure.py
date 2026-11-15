"""Actions measurements name actual selectors, never a full-part status or a shell command."""

import importlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev.ciworkflows import measurement_isolated, workflows
from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.logref import LogRef, stamp_line
from dev_lab.dev.producer import OUTCOME_VAR, PRODUCING_VAR


@pytest.fixture
def committed(tmp_path) -> tuple[Path, str, dict[str, str]]:
    run_git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.pytest.ini_options]\ntestpaths=["tests"]\n[tool.dev_lab.parts]\noutput="output/logs"\n',
        encoding='utf-8',
        newline='\n',
    )
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_a.py').write_text('def test_a():\n    assert True\n', encoding='utf-8', newline='\n')
    run_git(tmp_path, 'add', 'pyproject.toml', 'tests/test_a.py')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'initial')
    sha = git_out(tmp_path, 'rev-parse', 'HEAD')
    return tmp_path, sha, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': sha}


def _owner() -> ModuleType:
    return importlib.import_module('dev_lab.dev.jobmeasure')


@pytest.mark.parametrize('selector', ['tests/test_a.py', 'tests/test_a.py::test_a', 'tests/test_a.py::test_a[x y]'])
def test_real_file_and_node_selectors_remain_exact_argv(committed, selector) -> None:
    root, sha, env = committed
    assert _owner().validate(root, sha, json.dumps([selector]), env) == (selector,)


@pytest.mark.parametrize(
    'raw',
    [
        '',
        '[]',
        '{}',
        'null',
        '[1]',
        '[""]',
        '["--part"]',
        '["../tests/test_a.py"]',
        '["/tests/test_a.py"]',
        '["tests\\\\test_a.py"]',
        '["tests/*.py"]',
        '["tests/missing.py"]',
        '["tests/test_a.py;echo owned"]',
        '["tests/test_a.py\\n--part"]',
    ],
)
def test_empty_malformed_option_and_escape_selections_are_named_refusals(committed, raw) -> None:
    root, sha, env = committed
    with pytest.raises(ValueError, match='measurement'):
        _owner().validate(root, sha, raw, env)


@pytest.mark.parametrize('which', ['expected', 'action', 'event', 'pr', 'smoke'])
def test_wrong_ref_or_mixed_full_part_mode_never_reaches_verify(committed, which) -> None:
    root, sha, env = committed
    expected = sha
    if which == 'expected':
        expected = 'a' * 40
    elif which == 'action':
        env['GITHUB_SHA'] = 'b' * 40
    elif which == 'event':
        env['GITHUB_EVENT_NAME'] = 'push'
    elif which == 'pr':
        env['MEASUREMENT_PR'] = '123'
    else:
        env['MEASUREMENT_SMOKE'] = 'true'
    with pytest.raises(ValueError, match='measurement'):
        _owner().validate(root, expected, '["tests/test_a.py"]', env)


def test_checkout_byte_changes_are_not_the_requested_commit(committed) -> None:
    root, sha, env = committed
    (root / 'tests/test_a.py').write_text('raise RuntimeError("changed")\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'measurement.*bytes'):
        _owner().validate(root, sha, '["tests/test_a.py"]', env)


def test_a_symlink_cannot_escape_even_if_its_target_matches_a_committed_file(committed, monkeypatch) -> None:
    root, sha, env = committed
    original = Path.resolve
    target = root / 'tests/test_a.py'

    def escaped(path: Path, *, strict: bool = False) -> Path:
        return root.parent / 'outside.py' if path == target else original(path, strict=strict)

    monkeypatch.setattr(Path, 'resolve', escaped)
    with pytest.raises(ValueError, match=r'measurement.*repository'):
        _owner().validate(root, sha, '["tests/test_a.py"]', env)


def test_generated_measurement_has_no_part_status_or_merge_authority() -> None:
    ci = workflows(Path(__file__).parents[1])['ci.yml']
    inputs = ci['on']['workflow_dispatch']['inputs']
    assert {'measurement_paths', 'measurement_sha'} <= inputs.keys()
    job = ci['jobs']['measurement']
    assert job['runs-on'] == 'ubuntu-latest'
    assert job['permissions'] == {'contents': 'read'}
    assert 'GITHUB_TOKEN' not in job.get('env', {})
    assert any('dev_lab.dev.hook_install --repo . --install' in step.get('run', '') for step in job['steps'])
    command = next(step['run'] for step in job['steps'] if 'jobmeasure' in step.get('run', ''))
    assert '${{' not in command
    assert 'jobparts' not in command
    assert ' --part' not in command
    assert any(
        step.get('uses') == 'actions/upload-artifact@v4' and step.get('if') == '${{ always() }}'
        for step in job['steps']
    )
    for name, normal in ci['jobs'].items():
        if name != 'measurement':
            assert "inputs.measurement_paths == ''" in normal['if'], name
            assert "inputs.measurement_sha == ''" in normal['if'], name
    assert "inputs.measurement_paths == ''" in ci['concurrency']['cancel-in-progress']


@pytest.mark.parametrize(('code', 'result'), [(0, 'pass'), (1, 'fail'), (3, 'inconclusive')])
@pytest.mark.parametrize('mismatch', [None, 'tree', 'env', 'spec'])
@pytest.mark.parametrize('nested_logs', [False, True])
def test_the_canonical_child_records_measurement_evidence_without_producer_authority(
    committed, monkeypatch, *, code, result, mismatch, nested_logs
) -> None:
    root, sha, env = committed
    owner, seen = _owner(), []
    env.update({PRODUCING_VAR: 'tests/base@' + sha, OUTCOME_VAR: 'foreign-outcome', 'GITHUB_TOKEN': 'private-token'})
    identity = {'tree': 'tree-id', 'env': 'env-id', 'spec': 'verify tests/test_a.py::test_a'}

    def child(argv, **kwargs: object) -> SimpleNamespace:
        seen.append(argv)
        assert argv[1:] == ['-m', 'dev_lab.dev.verify', '--', 'tests/test_a.py::test_a']
        assert kwargs['cwd'] == root
        assert not kwargs.get('shell')
        assert PRODUCING_VAR not in kwargs['env']
        assert OUTCOME_VAR not in kwargs['env']
        assert 'GITHUB_TOKEN' not in kwargs['env']
        kwargs['stdout'].write('original child output\n')
        log = output_dir(root, 'verify') / 'actual.log'
        log.write_text('actual test output\n', encoding='utf-8')
        ref = LogRef.of(log)
        with log.open('a', encoding='utf-8') as handle:
            cited = {**identity, **({mismatch: 'other'} if mismatch else {})}
            handle.write(stamp_line(result=result, digest=ref.digest, lines=ref.lines, **cited) + '\n')
        if nested_logs:
            (log.parent / 'nested.log').write_bytes(
                log.read_bytes().replace(identity['spec'].encode(), b'verify tests/other.py')
            )
            (log.parent / 'truncated.log').write_text('incomplete unrelated nested run\n', encoding='utf-8')
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(owner._door, 'run', child)
    # Validation uses real Git; patch only after the validated request is frozen.
    monkeypatch.setattr(owner, 'validate', lambda *_: ('tests/test_a.py::test_a',))
    monkeypatch.setattr(
        owner,
        'run_key',
        lambda *_: SimpleNamespace(tree=identity['tree'], env=identity['env'], selector=identity['spec']),
        raising=False,
    )
    assert owner.run(root, sha, '["tests/test_a.py::test_a"]', env) == (3 if mismatch else code)
    assert len(seen) == 1
    receipt = json.loads(next(output_dir(root, 'measurement').glob('*/receipt.json')).read_text())
    assert receipt['kind'] == 'MEASUREMENT'
    assert receipt['sha'] == sha
    assert receipt['selectors'] == ['tests/test_a.py::test_a']
    assert receipt['exit_code'] == code
    assert receipt['result'] == ('inconclusive' if mismatch else result)
    if not mismatch:
        assert receipt['tree'] == 'tree-id'
        assert receipt['env'] == 'env-id'
    assert 'foreign-outcome' not in json.dumps(receipt)
    folder = next(output_dir(root, 'measurement').iterdir())
    assert (folder / 'stdout.log').read_text() == 'original child output\n'
    assert {p.name for p in folder.iterdir()} == (
        {'receipt.json', 'stdout.log'} if mismatch else {'receipt.json', 'stdout.log', 'verify.log'}
    )


def test_exit_zero_without_a_verifiable_log_is_incomplete_not_pass(committed, monkeypatch) -> None:
    root, sha, env = committed
    owner = _owner()
    monkeypatch.setattr(owner, 'validate', lambda *_: ('tests/test_a.py',))
    monkeypatch.setattr(owner, 'run_key', lambda *_: SimpleNamespace(tree='tree', env='env', selector='selector'))
    monkeypatch.setattr(owner._door, 'run', lambda *_, **__: SimpleNamespace(returncode=0))
    assert owner.run(root, sha, '["tests/test_a.py"]', env) == 3
    receipt = json.loads(next(output_dir(root, 'measurement').glob('*/receipt.json')).read_text())
    assert receipt['exit_code'] == 0
    assert receipt['result'] == 'inconclusive'


def test_invalid_unvalidated_inputs_are_not_copied_to_an_artifact(committed) -> None:
    root, _, env = committed
    assert _owner().run(root, 'unvalidated-sensitive-value', '[]', env) == 3
    receipt = next(output_dir(root, 'measurement').glob('*/receipt.json')).read_text()
    assert 'unvalidated-sensitive-value' not in receipt


@pytest.mark.parametrize('plant', ['permission', 'secret', 'token'])
def test_a_consumer_cannot_give_the_measurement_setup_write_authority_or_secrets(plant) -> None:
    job = {'permissions': {'contents': 'read'}, 'steps': [{'run': 'uv sync --frozen'}]}
    if plant == 'permission':
        job['permissions']['statuses'] = 'write'
    elif plant == 'secret':
        job['steps'][0]['env'] = {'KEY': '${{ secrets.PRIVATE_KEY }}'}
    else:
        job['env'] = {'GITHUB_TOKEN': '${{ github.token }}'}
    with pytest.raises(ValueError, match='measurement'):
        measurement_isolated({'jobs': {'measurement': job}})
