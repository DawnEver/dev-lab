"""THE ENVIRONMENT A VERDICT CITES leaves out the project under test: its tree already names that code.

The incident (2026-11-05): dev-lab #107's PR head f0f28483 and its merge 0ad7c9b5 had ONE tree, yet the merge's
smoke re-ran every part -- 46 min on Windows -- because the env key hashed ``dev-lab==0.0.1.dev2253+gf0f28483d``
against ``dev-lab==0.0.1.dev2254+g0ad7c9b54``: a VCS version moves with every commit, so no two shas ever shared
a key and the store's lookup by (tree, env, part) could never hit.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.envkey import env_key

from dev_lab.dev import verdictenv

INTERPRETER = 'cpython-3.13.1-linux'
DEPS = ('lab-commons==1.2+gabc', 'numpy==2.1')


def _root(tmp_path: Path, name: str = 'Dev_Lab') -> Path:
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "{name}"\n', encoding='utf-8')
    return tmp_path


def _manifest(own: str) -> tuple[str, ...]:
    return (INTERPRETER, *sorted((*DEPS, f'dev-lab=={own}')))


def test_two_commits_of_one_environment_share_the_key(tmp_path: Path) -> None:
    root = _root(tmp_path)
    one = verdictenv.verdict_manifest(root, _manifest('0.0.1.dev2253+gf0f28483d'))
    two = verdictenv.verdict_manifest(root, _manifest('0.0.1.dev2254+g0ad7c9b54'))
    assert one == two == (INTERPRETER, *DEPS), 'the project under test is left out, by its normalized name'
    assert env_key(one) == env_key(two)


def test_any_other_distribution_still_moves_the_key(tmp_path: Path) -> None:
    """PLANTED CONTROL: a git dependency's commit rides in its version, and it still keys the verdict."""
    root = _root(tmp_path)
    moved = tuple(line.replace('+gabc', '+gdef') for line in _manifest('1'))
    assert env_key(verdictenv.verdict_manifest(root, moved)) != env_key(
        verdictenv.verdict_manifest(root, _manifest('1'))
    )


def test_a_checkout_naming_no_project_keeps_every_line(tmp_path: Path) -> None:
    assert verdictenv.verdict_manifest(tmp_path, _manifest('1')) == _manifest('1')


def test_the_record_states_the_key_and_the_lines_it_was_taken_over(tmp_path: Path) -> None:
    root = _root(tmp_path)
    record = verdictenv.verdict_env_record(root, _manifest('1'))
    assert record == {
        'env': env_key((INTERPRETER, *DEPS)),
        'resolved': [INTERPRETER, *DEPS],
        'policy': verdictenv.verdict_policy((root / 'pyproject.toml').read_text(encoding='utf-8'), ''),
    }
    assert verdictenv.verdict_env(root) == verdictenv.verdict_env_record(root)['env'], 'one reading, one key'


def test_the_policy_moves_with_the_test_declaration_and_the_lock_and_nothing_else() -> None:
    """PLANTED both ways: a test table or the lock changes it; an unrelated table does not."""
    base = '[project]\nname = "x"\n[tool.lab_commons.tests]\nproduce = ["a"]\n'
    policy = verdictenv.verdict_policy(base, 'lock-1')
    assert verdictenv.verdict_policy(base + '[tool.ruff]\nline-length = 9\n', 'lock-1') == policy
    assert verdictenv.verdict_policy(base.replace('"a"', '"b"'), 'lock-1') != policy
    assert verdictenv.verdict_policy(base + '[tool.dev_lab.parts]\nrequired = ["jmag"]\n', 'lock-1') != policy
    assert verdictenv.verdict_policy(base, 'lock-2') != policy
    assert len(policy) == verdictenv.POLICY_CHARS
