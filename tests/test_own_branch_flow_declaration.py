"""lab-commons follows its own family model: integrate/main coordinates, main moves only by promote."""

from __future__ import annotations

from pathlib import Path

import pytest
from lab_commons.hpc.needsets import read_vocabulary, scarce_parts

from dev_lab.dev import platformparts, pushgate
from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.lanepolicy import load_policy

ROOT = Path(__file__).resolve().parents[1]
SHA = '0' * 40


def test_the_integration_branch_is_declared_and_long_lived() -> None:
    policy = load_policy(ROOT)
    assert (policy.trunk, policy.integration) == ('main', 'integrate/main')
    assert declared_branchset(ROOT).sessions == {'integrate/main'}


def test_a_push_to_integrate_main_needs_no_part_and_main_does() -> None:
    """PLANTED CONTROL: the same empty forge admits integrate/main and refuses the trunk."""
    policy = load_policy(ROOT)
    destination = pushgate.destination_of('refs/heads/integrate/main', policy)
    assert destination == pushgate.INTEGRATION
    assert pushgate.decide(destination, head=SHA, statuses=lambda: ()).allowed
    assert not pushgate.decide(pushgate.TRUNK, head=SHA, statuses=lambda: ()).allowed


def test_every_part_this_repo_needs_has_a_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platformparts, 'dated_log', lambda *_a, **_k: Path('output'))
    monkeypatch.setattr(platformparts, 'origin_url', lambda *_a: 'https://h/o/r.git')
    assert platformparts.producer_argv(ROOT, 'workstation', sha='HEAD') == [
        '-m',
        'dev_lab.dev.verify',
        '--part',
        'workstation',
    ]
    assert platformparts.cluster_part(ROOT, 'HEAD').collect == ''


def test_the_workstation_part_is_scarce_so_a_pr_waits_on_it_only_by_reach() -> None:
    """Incident 2026-10-25: 13 open PRs waited on tests/workstation, which one host serves, whatever they touched.

    SCARCE-PARTS-BY-REACH (:mod:`dev_lab.dev.forgescarce`) waives a scarce part a PR's diff cannot reach; the
    part is scarce only by this declaration. PLANTED CONTROL: base is never scarce.
    """
    vocabulary = read_vocabulary((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert scarce_parts(['base', 'workstation'], vocabulary.scarce) == {'workstation'}
