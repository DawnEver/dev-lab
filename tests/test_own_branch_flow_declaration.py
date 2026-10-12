"""lab-commons follows its own family model: integrate/main coordinates, main moves only by promote."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import admission, platformparts
from lab_commons.dev.branchset import declared_branchset
from lab_commons.dev.lanepolicy import load_policy

ROOT = Path(__file__).resolve().parents[1]
SHA = '0' * 40


def test_the_integration_branch_is_declared_and_long_lived() -> None:
    policy = load_policy(ROOT)
    assert (policy.trunk, policy.integration) == ('main', 'integrate/main')
    assert declared_branchset(ROOT).sessions == {'integrate/main'}


def test_a_push_to_integrate_main_needs_no_part_and_main_does() -> None:
    """PLANTED CONTROL: the same empty forge admits integrate/main and refuses the trunk."""
    policy = load_policy(ROOT)
    destination = admission.destination_of('refs/heads/integrate/main', policy)
    assert destination == admission.INTEGRATION
    assert admission.admit(destination, head=SHA, statuses=lambda: ()).allowed
    assert not admission.admit(admission.TRUNK, head=SHA, statuses=lambda: ()).allowed


def test_every_part_this_repo_needs_has_a_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platformparts, 'checkout_interpreter', lambda *_a, **_k: Path('python'))
    monkeypatch.setattr(platformparts, 'dated_log', lambda *_a, **_k: Path('output'))
    monkeypatch.setattr(platformparts, 'origin_url', lambda *_a: 'https://h/o/r.git')
    assert platformparts.part_argv(ROOT, 'windows', scope='full', os_name='nt')[1:] == ['-m', 'lab_commons.dev.verify']
    assert platformparts.cluster_part(ROOT, SHA).collect == ''
