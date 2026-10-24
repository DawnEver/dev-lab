"""A repo is ONBOARDED when every declaration the family flow needs is in its manifest -- one place, one answer.

THE DEFECT THIS CLOSES, measured 2026-10-20. Five consumer repos were each missing a different piece of the
same configuration: one had no `ephemeral` namespace, another's `pr_merges_since` did not exist yet in the
lab-commons it pinned, a third ran a pre-commit framework hook over a file with no configuration, a fourth
had no `AGENTS.md` at all, and two had Pull Requests switched OFF on the forge so no PR could be opened into
them. Each was found by failing at something else, one at a time, over hours.

SO THE PIECES ARE ONE STATEMENT. :func:`assert_repo_is_onboarded` reads the manifest and names every missing
piece at once, with the line to add; :func:`assert_the_forge_takes_pull_requests` is the one half that needs
the network and is therefore separate. A new repo runs both once and then adopts the same two lines every
other consumer carries.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from dev_lab.dev.branchset import EPHEMERAL_OFF, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forgework import Client

__all__ = ['OnboardingViolation', 'assert_repo_is_onboarded', 'assert_the_forge_takes_pull_requests']

#: The files a repo must carry, and what each is for.
_FILES: tuple[tuple[str, str], ...] = (
    ('AGENTS.md', 'names the flow by its one page, so an arriving agent can find how this repo integrates'),
    ('uv.lock', 'a committed lock is what a verdict pins an environment to (PIN + FRESHNESS)'),
)


class OnboardingViolation(AssertionError):
    """A repo cannot take part in the family flow as it stands; the message names every missing piece."""


def assert_repo_is_onboarded(*, root: Path) -> tuple[str, ...]:
    """Refuse a repo the flow cannot run in, naming EVERY missing declaration at once.

    Returns:
        The notes a caller may print (today: none), so the signature matches the other family assertions.

    Raises:
        OnboardingViolation: one or more pieces are missing, each with the line that supplies it.

    """
    missing: list[str] = []
    policy = load_policy(root)
    try:
        declared = declared_branchset(root)
    except BranchSetNotDeclared as undeclared:
        declared = None
        missing.append(f'[tool.lab_commons.branchset] trunk/sessions/ephemeral -- absent ({undeclared})')
    if declared is not None:
        missing += [
            *([EPHEMERAL_OFF] if not declared.is_ephemeral('pr/x') else []),
            *(
                [f'[tool.lab_commons.branchset] sessions names {policy.integration!r}']
                if policy.integration not in declared.sessions
                else []
            ),
        ]
    missing += [
        *(
            ['[tool.lab_commons.integrator] pr_merges_since = "<the integrate/main sha the flow starts after>"']
            if not policy.pr_merges_since
            else []
        ),
        *(
            ['[tool.lab_commons.tests] produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]']
            if not _produces(root)
            else []
        ),
        *([] if _hooks_declared(root) else ['[tool.lab_commons.hooks] -- an empty table, so the base rows run']),
    ]
    missing += [f'{name} -- {why}' for name, why in _FILES if not (root / name).is_file()]
    if missing:
        msg = f'{root} is not onboarded; add or supply:\n  - ' + '\n  - '.join(missing)
        raise OnboardingViolation(msg)
    return ()


def _table(root: Path) -> dict[str, object]:
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return {}
    return tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('lab_commons', {})


def _produces(root: Path) -> bool:
    return bool((_table(root).get('tests') or {}).get('produce'))


def _hooks_declared(root: Path) -> bool:
    return 'hooks' in _table(root)


def assert_the_forge_takes_pull_requests(client: Client) -> None:
    """Refuse a repo whose forge has Pull Requests switched off -- no PR can be opened into it.

    The other half of onboarding is a FORGE setting rather than a file, so it cannot be read from the tree:
    a repo whose `/pulls` answers 404 while `GET` of the repo answers has the unit off, and the fix is one
    checkbox in the repo's settings.

    Raises:
        OnboardingViolation: the forge answers for the repo but not for its pull requests.

    """
    client.call('GET', client.repo)
    try:
        client.call('GET', f'{client.repo}/pulls?state=all&limit=1')
    except Exception as refused:
        msg = (
            f'{client.repo}: the forge answers for the repository but not for its pull requests ({refused}); '
            'the Pull Requests unit is OFF -- switch it on in the repository settings, or no PR can be opened'
        )
        raise OnboardingViolation(msg) from refused
