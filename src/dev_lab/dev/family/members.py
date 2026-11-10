"""THE FAMILY OF THIS MACHINE: the machine file's ``[repos]`` is the member list, and every fact is checked against it.

User ruling 2026-11-09: adding a repo is a documented, procedural MECHANISM. MEASURED that day on a newly adopted
lab: its founding PR open since creation (the review red because ``forge secrets sync`` never ran for it), no trunk
branch, no ``pr_merges_since``, its integration branch unprotected, absent from what the workstation serves and
from every cluster account, not cloned beside its siblings -- and nothing noticed, because no list named it.

ONE LIST, the one that already existed: ``[repos]`` of the machine file (:func:`lab_commons.home.repos`), name ->
absolute checkout path, the place a checkout's location is declared. A member's forge is its checkout's
``origin``. Membership by MANIFEST (:func:`dev_lab.dev.family.is_member`) is still the member's own fact; this
list is which members THIS machine works with, and :func:`check` refuses a listed checkout that is no member. What
else lists repos DERIVES from it (``forge secrets sync``'s targets) or is CHECKED against it (``[serve] repos``:
a served name that is no member, a member this serving machine does not serve).

:func:`check` names, per member, every fact that is not so (:class:`Finding`): cloned, beside its siblings,
onboarded (:func:`~dev_lab.dev.famtests.onboarding.assert_repo_is_onboarded`), and on its forge (:class:`Facts`):
Pull Requests on, the trunk and integration branches present, protection as declared (:mod:`dev_lab.dev.forgeprotect`),
the review secret present (by NAME; a value is never read), no PR open past :data:`OPEN_PR_DAYS`.

:func:`join` runs the steps in order, each idempotent: clone beside the siblings, RECORD the member (first, so the
watch sees a half-joined repo), check onboarding, apply protection, sync the review secret (only with the user's
bundle), and returns what is left for the user.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Protocol

import tomlkit

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.family import is_member
from dev_lab.dev.famtests.onboarding import OnboardingViolation, assert_repo_is_onboarded
from dev_lab.dev.lanepolicy import load_policy

__all__ = ['OPEN_PR_DAYS', 'Facts', 'FamilyRefused', 'Finding', 'ForgeFacts', 'check', 'join', 'siblings_root']

#: A PR open longer than this is a finding: a founding PR left open is a repo nobody finished joining.
OPEN_PR_DAYS: Final = 7


class FamilyRefused(ValueError):
    """The machine file cannot say where a member belongs; nothing was changed."""


@dataclass(frozen=True)
class Finding:
    """One fact about one member that is not so: ``what`` starts with its kind, then the remedy."""

    member: str
    what: str


@dataclass(frozen=True)
class Facts:
    """What a member's forge holds: Pull Requests on, missing branches, protection drift, secret NAMES, oldest PR."""

    pulls: bool
    missing_branches: tuple[str, ...]
    protection_drift: tuple[str, ...]
    secrets: frozenset[str]
    oldest_open: tuple[int, datetime] | None
    #: What could not be read, each with why: a fact unread is named, never taken as absent.
    unread: tuple[str, ...] = ()
    #: Each branch role's required status contexts, as the forge holds them (compared across the family).
    contexts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: The forge host: members are compared with their peers on one forge.
    host: str = ''


class ForgeFacts(Protocol):
    """Reads one member's :class:`Facts` (:mod:`dev_lab.dev.family.forgefacts` on a forge, a fake in tests)."""

    def facts(self, root: Path, trunk: str, integration: str) -> Facts:
        """The facts of the member at *root*."""
        ...


def siblings_root(family: Mapping[str, Path]) -> Path | None:
    """Where the members live: the parent most of them share; ``None`` for no member."""
    parents = Counter(path.parent for path in family.values())
    return parents.most_common(1)[0][0] if parents else None


def _forge_findings(name: str, facts: Facts, *, bundle_name: str, now: datetime) -> list[Finding]:
    found = [Finding(name, f'unread: {why}') for why in facts.unread]
    found += [] if facts.pulls else [Finding(name, 'pull requests: OFF -- switch the unit on in the repo settings')]
    found += [Finding(name, f'trunk branch: {b} is absent -- push it from the founding commit')
              for b in facts.missing_branches]  # fmt: skip
    found += [Finding(name, f'protection: {line} -- python -m dev_lab.dev.forge protect apply')
              for line in facts.protection_drift]  # fmt: skip
    if facts.host and facts.host != GITHUB_HOST:  # never a bundle off GitHub (dev_lab.dev.forgesecrets)
        if bundle_name in facts.secrets:
            found.append(Finding(name, f'secret: {bundle_name} is set on {facts.host}, where any PR can read it -- '
                                       'delete it (ruling 2026-11-03)'))  # fmt: skip
    elif bundle_name not in facts.secrets and not any(why.startswith('secrets') for why in facts.unread):
        found.append(
            Finding(
                name, f'secret: {bundle_name} is absent -- python -m dev_lab.dev.forge secrets sync --task pr-review'
            )
        )
    if facts.oldest_open is not None and now - facts.oldest_open[1] > timedelta(days=OPEN_PR_DAYS):
        number, opened = facts.oldest_open
        found.append(Finding(name, f'open PR: #{number} open {(now - opened).days} days -- finish or close it'))
    return found


def _member(
    name: str, root: Path, home: Path | None, forge: ForgeFacts, *, bundle_name: str, now: datetime
) -> tuple[list[Finding], Facts | None]:
    if not (root / 'pyproject.toml').is_file():
        return [Finding(name, f'not cloned: no checkout at {root} -- python -m dev_lab.dev.family join')], None
    found = [] if home is None or root.parent == home else [Finding(name, f'not beside its siblings in {home}')]
    if not is_member(root):
        return [*found, Finding(name, 'onboarding: declares no [tool.dev_lab] table -- it is no family member')], None
    try:
        assert_repo_is_onboarded(root=root)
    except OnboardingViolation as missing:
        found.append(Finding(name, f'onboarding: {missing}'))
    try:
        policy = load_policy(root)
    except ValueError:
        return found, None  # the onboarding finding names the missing integrator table
    facts = forge.facts(root, policy.trunk, policy.integration)
    return found + _forge_findings(name, facts, bundle_name=bundle_name, now=now), facts


def check(
    family: Mapping[str, Path],
    *,
    forge: Callable[[str, Path], ForgeFacts],
    served: Iterable[str] | None,
    now: datetime,
    bundle_name: str,
    compare: Callable[[Mapping[str, tuple[Path, Facts]]], list[Finding]] | None = None,
) -> list[Finding]:
    """Every :class:`Finding` of *family*; *served* is ``[serve] repos`` (``None``: this machine serves nothing).

    *compare* is handed every member whose forge was read, ``{name: (root, facts)}``, for the findings that exist
    only BETWEEN members (:mod:`dev_lab.dev.family.horizontal`).
    """
    home = siblings_root(family)
    found: list[Finding] = []
    read: dict[str, tuple[Path, Facts]] = {}
    for name, root in sorted(family.items()):
        own, facts = _member(name, root, home, forge(name, root), bundle_name=bundle_name, now=now)
        found += own
        if facts is not None:
            read[name] = (root, facts)
    found += compare(read) if compare is not None else []
    if served is not None:
        named = set(served)
        found += [Finding(name, 'served but no [repos] member') for name in sorted(named - set(family))]
        found += [Finding(name, 'not served: add it to [serve] repos (workstation deploy)')
                  for name in sorted(set(family) - named)]  # fmt: skip
    return found


def _record(machine: Path, name: str, where: Path) -> bool:
    """Write ``[repos] <name> = "<where>"`` into the machine file; whether it changed."""
    document = tomlkit.parse(machine.read_text(encoding='utf-8')) if machine.is_file() else tomlkit.document()
    table = document.setdefault('repos', tomlkit.table())
    if table.get(name) == where.as_posix():
        return False
    table[name] = where.as_posix()
    machine.write_text(tomlkit.dumps(document), encoding='utf-8')
    return True


def join(
    name: str,
    url: str,
    *,
    machine: Path,
    clone: Callable[[str, Path], None],
    protect: Callable[[Path], Iterable[str]],
    secrets: Callable[[Path], str] | None,
) -> list[str]:
    """The ordered, idempotent steps that make *name* a member; each line said, ``left: ...`` for the user.

    *protect* applies protection and returns what the forge still lacks; *secrets* sets the review secret
    (``None``: no bundle was given). Neither runs before the onboarding the forge rules are rendered from.

    Raises:
        FamilyRefused: the machine file names no member, so where the siblings live is unknown.

    """
    document = tomlkit.parse(machine.read_text(encoding='utf-8')) if machine.is_file() else {}
    family = {str(k): Path(str(v)) for k, v in dict(document.get('repos', {})).items()}
    home = siblings_root({k: v for k, v in family.items() if k != name})
    if home is None:
        msg = f'{machine} [repos] names no member: declare one sibling\'s checkout first, so "beside" has a place'
        raise FamilyRefused(msg)
    where = family.get(name, home / name)
    said: list[str] = []
    if not (where / '.git').exists() and not (where / 'pyproject.toml').is_file():
        clone(url, where)
        said.append(f'cloned {url} to {where}')
    if _record(machine, name, where):
        said.append(f'recorded [repos] {name} = {where.as_posix()}')
    try:
        assert_repo_is_onboarded(root=where)
    except OnboardingViolation as missing:
        return [*said, f'left: onboarding -- land a PR adding: {missing}', _SECRETS_LEFT, _PROTECT_LEFT]
    said += [f'left: protection -- {line}' for line in protect(where)]
    if secrets is None:
        said.append(_SECRETS_LEFT)
    else:
        said.append(secrets(where))
    return said


_SECRETS_LEFT: Final = (
    'left: secrets -- no stored review bundle: pipe it once to `python -m dev_lab.dev.forge secrets store '
    '--task pr-review`'
)
_PROTECT_LEFT: Final = 'left: protection -- re-run join once onboarded (protection is rendered from the manifest)'
