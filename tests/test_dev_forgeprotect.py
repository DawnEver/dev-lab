"""FORGE-PROTECTION-DECLARED: the declaration, the contexts derived from the workflows, and both backends' plans.

Every backend test drives an in-memory forge (:mod:`_protect_fakes`) and asserts on what it was asked to write; every
planted control is a declaration or a live rule that must NOT read as clean.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from _protect_fakes import GITEA_TEXT, GITHUB_TEXT, INTEGRATOR, FakeGitea, FakeGitHub, refused

from dev_lab.dev import forgeprotect
from dev_lab.dev._forgebackends import NotWired
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecli import NOUNS
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeprotect import INTEGRATION, TRUNK, apply, declaration_from, plan, required_contexts, targets
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

GITHUB = Forge('github.com', 'owner', 'alpha')
GITEA = Forge('gitea.example', 'owner', 'alpha')
JUDGED = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "review-bot"\n'


# -- the declaration -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'said'),
    [
        (INTEGRATOR, 'declares no forges'),
        (GITEA_TEXT + '[tool.dev_lab.protection]\nextra = 1\n', 'unknown key'),
        (INTEGRATOR + '[tool.dev_lab.protection.forges."gitea.example"]\npromote = ["p"]\n', 'names no breakglass'),
        (INTEGRATOR + '[tool.dev_lab.protection.forges."gitea.example"]\nbreakglass = "b"\nwho = 1\n', 'unknown'),
        (GITEA_TEXT + '[tool.dev_lab.protection]\napprovals = 1\n', 'the judge is advisory'),
        (GITEA_TEXT + JUDGED + '[tool.dev_lab.protection]\napprovals = -1\n', 'below zero'),
    ],
)
def test_a_declaration_that_cannot_mean_anything_is_refused(text: str, said: str) -> None:
    """PLANTED: each declaration would render a rule nobody decided, or one no merge could ever satisfy."""
    with pytest.raises(ValueError, match=said):
        declaration_from(text, 'pyproject.toml')


def test_a_judge_reviewed_repo_requires_no_approval_since_the_judge_is_advisory() -> None:
    integration, trunk = targets(GITEA_TEXT + JUDGED, 'p', GITEA)
    assert (integration.approvals, integration.approver) == (0, '')
    assert (trunk.approvals, trunk.approver) == (0, '')


def test_a_serve_reviewed_repo_requires_no_approval() -> None:
    integration, _ = targets(GITEA_TEXT, 'p', GITEA)
    assert (integration.approvals, integration.approver) == (0, '')


def test_the_branches_and_identities_come_from_their_one_declaration() -> None:
    integration, trunk = targets(GITEA_TEXT.replace('integrate/main', 'next'), 'p', GITEA)
    assert (integration.role, integration.branch, integration.bypass, integration.pushers) == (
        INTEGRATION,
        'next',
        ('breakglass-bot',),
        (),
    )
    assert (trunk.role, trunk.branch, trunk.pushers) == (TRUNK, 'main', ('promote-bot',))  # fmt: skip


def test_a_forge_the_declaration_does_not_name_is_refused() -> None:
    """PLANTED: a repo mirrored onto a forge it declares nothing for has no bypass identity there."""
    with pytest.raises(ValueError, match=r'names no "github\.com"'):
        targets(GITEA_TEXT, 'p', GITHUB)


# -- the contexts, derived from the rendered workflows ---------------------------------------------------------------


def test_a_forge_whose_workflows_post_the_decision_requires_it_and_every_base_row() -> None:
    derived = required_contexts(GITHUB_TEXT, 'p', GITHUB)
    assert derived == {
        INTEGRATION: ('tests/merge-ready',),
        TRUNK: ('tests/base', 'tests/base@macos', 'tests/base@windows'),
    }


def test_the_trunk_never_requires_a_hand_part() -> None:
    """User ruling 2026-11-10: a part a declared resource derives (``tests/windows``, a vendor tool's) is tested later.

    Requiring it on the trunk would hold every promotion whenever its host is away (lab-commons declares
    ``resources = ["windows"]``). PLANTED CONTROL: the base part's rows are still required.
    """
    declared = GITHUB_TEXT + '[tool.lab_commons.tests]\nresources = ["windows", "vendortool"]\n'
    trunk = required_contexts(declared, 'p', GITHUB)[TRUNK]
    assert trunk == required_contexts(GITHUB_TEXT, 'p', GITHUB)[TRUNK]
    assert 'tests/windows' not in trunk
    assert 'tests/vendortool' not in trunk
    assert {'tests/base', 'tests/base@windows'} <= set(trunk), 'PLANTED CONTROL'


def test_a_served_forge_requires_its_tests_and_never_the_review_status() -> None:
    """User ruling 2026-11-05: the merge decision enforces the review itself; a capped review merges WARNED."""
    assert required_contexts(GITEA_TEXT, 'p', GITEA) == {
        INTEGRATION: ('tests/base', 'tests/security'),
        TRUNK: ('tests/base',),
    }


def test_a_judged_repo_requires_no_review_status() -> None:
    """The judge's verdict is a PR review, never a ``tests/review`` status: requiring one would hold every merge."""
    assert 'tests/review' not in required_contexts(GITEA_TEXT + JUDGED, 'p', GITEA)[INTEGRATION]


def test_a_workflow_on_the_other_forge_is_not_this_forge_s_context() -> None:
    """GitHub's ci.yml posts ``tests/merge-ready`` on GitHub only; a Gitea mirror of the repo is served."""
    text = GITHUB_TEXT + '[tool.dev_lab.protection.forges."gitea.example"]\nbreakglass = "b"\n'
    assert required_contexts(text, 'p', GITEA)[INTEGRATION] == ('tests/base', 'tests/security')


# -- GitHub: rulesets ------------------------------------------------------------------------------------------------


def test_github_creates_one_enforced_ruleset_per_branch_and_then_holds_it() -> None:
    forge = FakeGitHub()
    wanted = targets(GITHUB_TEXT, 'p', GITHUB)
    assert [step.subject for step in plan(forge, GITHUB, wanted)] == [
        'integration integrate/main: ruleset "dev-lab integration" absent -> create',
        'trunk main: ruleset "dev-lab trunk" absent -> create',
    ]
    assert apply(forge, GITHUB, wanted) == []
    integration, trunk = (one for one in forge.rulesets.values())
    assert integration['enforcement'] == 'active'
    assert integration['bypass_actors'] == [
        {'actor_id': 5, 'actor_type': 'RepositoryRole', 'bypass_mode': 'pull_request'}
    ]
    assert {rule['type'] for rule in integration['rules']} == {
        'deletion', 'non_fast_forward', 'required_status_checks', 'pull_request'}  # fmt: skip
    assert 'pull_request' not in {rule['type'] for rule in trunk['rules']}
    assert plan(forge, GITHUB, wanted) == []


def test_github_classic_protection_is_a_second_rule_and_is_deleted() -> None:
    forge = FakeGitHub(classic={'main': {'enforce_admins': {'enabled': False},
                                         'required_status_checks': {'contexts': ['tests/base']}}})  # fmt: skip
    wanted = targets(GITHUB_TEXT, 'p', GITHUB)
    said = [step.subject for step in plan(forge, GITHUB, wanted)]
    assert 'trunk main: classic branch protection is a second, undeclared rule -> delete' in said
    apply(forge, GITHUB, wanted)
    assert forge.classic == {}
    assert ('DELETE', '/repos/owner/alpha/branches/main/protection', None) in forge.writes


@pytest.mark.parametrize(
    ('drift', 'named'),
    [
        (lambda rs: rs | {'enforcement': 'evaluate'}, 'enforcement'),
        (
            lambda rs: (
                rs
                | {
                    'bypass_actors': [
                        *rs['bypass_actors'],
                        {'actor_id': 4, 'actor_type': 'RepositoryRole', 'bypass_mode': 'always'},
                    ]
                }
            ),
            'bypass',
        ),
        (lambda rs: rs | {'rules': [r for r in rs['rules'] if r['type'] != 'required_status_checks']}, 'contexts'),
        (lambda rs: rs | {'conditions': {'ref_name': {'include': ['~ALL'], 'exclude': []}}}, 'branches'),
    ],
)
def test_github_drift_in_any_enforced_fact_is_named(drift, named: str) -> None:
    """PLANTED: a ruleset loosened by hand (evaluate-only, a second bypass, a check dropped) is not as declared."""
    forge = FakeGitHub()
    wanted = targets(GITHUB_TEXT, 'p', GITHUB)
    apply(forge, GITHUB, wanted)
    forge.rulesets[1] = drift(forge.rulesets[1])
    steps = plan(forge, GITHUB, wanted)
    assert [step.subject for step in steps] == [
        'integration integrate/main: ruleset "dev-lab integration" differs -> update'
    ]
    assert any(line.startswith(f'{named}:') for line in steps[0].lines), steps[0].lines
    assert apply(forge, GITHUB, wanted) == []


def test_github_bypass_actors_a_credential_cannot_read_are_said_as_unanswered() -> None:
    """GitHub omits bypass actors for a non-admin: UNREADABLE, never read as an empty (and so drifted) list."""
    forge = FakeGitHub()
    wanted = targets(GITHUB_TEXT, 'p', GITHUB)
    apply(forge, GITHUB, wanted)
    forge.admin = False
    lines = [line for step in plan(forge, GITHUB, wanted) for line in step.lines]
    assert lines
    assert all('the forge did not answer' in line for line in lines), lines


def test_github_strays_of_this_door_are_deleted_and_any_other_ruleset_is_left() -> None:
    forge = FakeGitHub(rulesets={7: {'name': 'dev-lab old-role', 'rules': []}, 8: {'name': 'tags', 'rules': []}})
    apply(forge, GITHUB, targets(GITHUB_TEXT, 'p', GITHUB))
    assert sorted(one['name'] for one in forge.rulesets.values()) == ['dev-lab integration', 'dev-lab trunk', 'tags']


@pytest.mark.parametrize(
    ('forges', 'said'),
    [
        ('[tool.dev_lab.protection.forges."github.com"]\nbreakglass = "breakglass-bot"\n', 'never a login'),
        ('[tool.dev_lab.protection.forges."github.com"]\nbreakglass = "role:owner"\n', 'never a login'),
        ('[tool.dev_lab.protection.forges."github.com"]\nbreakglass = "app:x"\n', 'never a login'),
        ('[tool.dev_lab.protection.forges."github.com"]\nbreakglass = "role:admin"\npromote = ["p"]\n', 'job token'),
    ],
)
def test_github_refuses_an_identity_a_ruleset_cannot_name(forges: str, said: str) -> None:
    """PLANTED: a login GitHub would silently not bypass with -- refused before any call."""
    forge = FakeGitHub()
    with pytest.raises(ValueError, match=said):
        plan(forge, GITHUB, targets(INTEGRATOR + '[tool.dev_lab.ci."ci.yml"]\n' + forges, 'p', GITHUB))
    assert forge.writes == []


def test_github_an_unreadable_classic_protection_raises_rather_than_reading_as_none() -> None:
    """A 403 is not "no classic protection": only a 404 says the rule is absent."""

    class Forbidden(FakeGitHub):
        def answer(self, method: str, path: str, body: dict[str, Any] | None) -> object:
            if '/branches/' in path:
                raise refused(403, 'forbidden')
            return super().answer(method, path, body)

    with pytest.raises(ForgeCallFailed):
        plan(Forbidden(), GITHUB, targets(GITHUB_TEXT, 'p', GITHUB))


# -- Gitea: branch protections ---------------------------------------------------------------------------------------

#: The acme-consumer rules as clicked by hand on 2026-11-04 (read from the forge's database, read-only).
_HAND_SET = {
    'main': {'enable_push': True, 'enable_push_whitelist': True,
             'push_whitelist_usernames': ['user-a-admin', 'promote-bot'], 'enable_merge_whitelist': True,
             'merge_whitelist_usernames': ['user-a-admin'], 'enable_force_push': False,
             'enable_bypass_allowlist': False, 'block_admin_merge_override': False, 'required_approvals': 0},
    'integrate/main': {'enable_push': False, 'enable_bypass_allowlist': True,
                       'bypass_allowlist_usernames': ['breakglass-bot'], 'block_on_rejected_reviews': True,
                       'dismiss_stale_approvals': True, 'required_approvals': 0},
}  # fmt: skip


def test_gitea_names_every_hand_set_difference_and_apply_removes_them() -> None:
    forge = FakeGitea(protections={name: dict(rule) for name, rule in _HAND_SET.items()})
    wanted = targets(GITEA_TEXT, 'p', GITEA)
    steps = {step.subject: step.lines for step in plan(forge, GITEA, wanted)}
    trunk = steps['trunk main: branch protection differs -> update']
    assert "push_whitelist_usernames: live=['promote-bot', 'user-a-admin'] declared=['promote-bot']" in trunk
    assert 'block_admin_merge_override: live=False declared=True' in trunk
    integration = steps['integration integrate/main: branch protection differs -> update']
    assert any(line.startswith('status_check_contexts: the forge did not answer') for line in integration)
    assert apply(forge, GITEA, wanted) == []
    assert forge.protections['main']['bypass_allowlist_usernames'] == ['breakglass-bot']
    assert ('PATCH', '/api/v1/repos/owner/alpha/branch_protections/integrate%2Fmain') in {w[:2] for w in forge.writes}


def test_gitea_creates_an_absent_rule_and_reads_its_nulls_as_empty_lists() -> None:
    """Gitea answers ``null`` for every empty list: read as ``[]``, never as drift after a clean apply."""
    forge = FakeGitea()
    wanted = targets(GITEA_TEXT + JUDGED, 'p', GITEA)
    assert len(plan(forge, GITEA, wanted)) == 2  # FLOOR: an empty forge is never clean
    assert apply(forge, GITEA, wanted) == []
    integration = forge.protections['integrate/main']
    assert (integration['enable_push'], integration['approvals_whitelist_username']) == (False, [])
    assert forge.protections['main']['merge_whitelist_usernames'] == []


def test_gitea_refuses_a_github_actor_as_its_bypass() -> None:
    text = INTEGRATOR + '[tool.dev_lab.protection.forges."gitea.example"]\nbreakglass = "role:admin"\n'
    with pytest.raises(ValueError, match='names a login'):
        plan(FakeGitea(), GITEA, targets(text, 'p', GITEA))


def test_gitea_leaves_a_rule_for_an_undeclared_branch_alone() -> None:
    forge = FakeGitea(protections={'release/*': {'enable_push': False}})
    apply(forge, GITEA, targets(GITEA_TEXT, 'p', GITEA))
    assert forge.protections['release/*'] == {'enable_push': False}


def test_the_door_is_the_forge_noun() -> None:
    assert NOUNS['protect'] is forgeprotect.main


# -- a GitHub App judge ------------------------------------------------------------------------------------------------

APP_JUDGED = '[tool.dev_lab.review]\nwhere = "judge"\njudge_app = 5619495\n'


def test_an_app_judged_github_repo_is_refused_since_actions_alone_gate_it() -> None:
    """User ruling 2026-11-11: GitHub wires no judge host, and on Gitea the judge is advisory: no approval required."""
    with pytest.raises(NotWired, match='judge-host'):
        targets(GITHUB_TEXT + APP_JUDGED, 'p', GITHUB)
    integration, _ = targets(GITEA_TEXT + JUDGED, 'p', GITEA)
    assert (integration.approvals, integration.approver) == (0, '')
    with pytest.raises(ValueError, match='the judge is advisory'):
        declaration_from(GITEA_TEXT + JUDGED + '[tool.dev_lab.protection]\napprovals = 1\n', 'p')


def test_an_app_judge_takes_no_approval_and_never_renders_on_gitea() -> None:
    with pytest.raises(ValueError, match='the judge is advisory'):
        declaration_from(GITHUB_TEXT + APP_JUDGED + '[tool.dev_lab.protection]\napprovals = 1\n', 'p')
    with pytest.raises(ValueError, match='no GitHub App'):
        plan(FakeGitea(), GITEA, targets(GITEA_TEXT + APP_JUDGED, 'p', GITEA))


def test_github_bypasses_every_declared_actor_an_app_beside_the_admin_role() -> None:
    """The ops App and the admin role are both bypass actors: ``breakglass`` may be a list, rendered in order."""
    text = INTEGRATOR + '[tool.dev_lab.protection.forges."github.com"]\nbreakglass = ["app:4242", "role:admin"]\n'
    forge = FakeGitHub()
    apply(forge, GITHUB, targets(text, 'p', GITHUB))
    actors = [(one['actor_type'], one['actor_id']) for one in next(iter(forge.rulesets.values()))['bypass_actors']]
    assert actors == [('Integration', 4242), ('RepositoryRole', 5)]
    assert plan(forge, GITHUB, targets(text, 'p', GITHUB)) == []


def test_gitea_refuses_more_than_one_bypass_login() -> None:
    text = INTEGRATOR + '[tool.dev_lab.protection.forges."gitea.example"]\nbreakglass = ["a-bot", "b-bot"]\n'
    with pytest.raises(ValueError, match='one login'):
        plan(FakeGitea(), GITEA, targets(text, 'p', GITEA))


# -- a refused write says why ------------------------------------------------------------------------------------------

#: GitHub's answer to a ruleset requiring a check from an App not installed on the repository (2026-11-11).
INVALID_APP = (
    '{"message":"Validation Failed","errors":["Invalid rule \'required_status_checks\': Invalid parameter '
    'required_status_checks: Invalid integration ids"],'
    '"documentation_url":"https://docs.github.com/rest/repos/rules#create-a-repository-ruleset","status":"422"}'
)


def test_a_refused_write_names_the_app_a_target_requires_a_check_from() -> None:
    failed = ForgeCallFailed(Report(('POST', 'x'), (Attempt(1, 422, INVALID_APP, Diagnosis.FORGE_REFUSED),), 3))
    wanted = [replace(one, judge_app=5619495) for one in targets(GITHUB_TEXT, 'p', GITHUB)]
    text = ' '.join(forgeprotect.refusal(failed, wanted))
    assert '422' in text
    assert 'Invalid integration ids' in text
    assert '5619495' in text
    assert 'install' in text


def test_a_refusal_without_an_app_fault_names_no_app() -> None:
    failed = ForgeCallFailed(
        Report(('POST', 'x'), (Attempt(1, 422, '{"message":"nope"}', Diagnosis.FORGE_REFUSED),), 3)
    )
    lines = forgeprotect.refusal(failed, targets(GITHUB_TEXT, 'p', GITHUB))
    assert 'nope' in '\n'.join(lines)
    assert 'install' not in '\n'.join(lines)


def test_a_final_refusal_s_message_carries_the_status_and_every_error_the_forge_named() -> None:
    failed = ForgeCallFailed(Report(('POST', 'x'), (Attempt(1, 422, INVALID_APP, Diagnosis.FORGE_REFUSED),), 3))
    assert 'the forge answered 422: Validation Failed' in str(failed)
    assert 'Invalid integration ids' in str(failed)
