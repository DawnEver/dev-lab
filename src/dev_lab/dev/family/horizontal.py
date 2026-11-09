"""THE FAMILY IS COMPARED HORIZONTALLY: what one member has and another lacks is a defect, unless DECLARED.

User, 2026-11-09: "compare ALL our toolchain repos horizontally; anything one lacks means our mechanism is
defective". MEASURED that day across the GitHub members: the review secret missing on two, the integration branch
unprotected on two, the trunk's contexts differing on one, a rendered workflow present on three and absent on four,
a branchset key on two, ``pr_merges_since`` absent on one, the kit itself without the ``AGENTS.md`` its own
onboarding page requires -- each found by a person looking, none by a check.

A member's PROFILE is a set of features (:func:`features`): its rendered workflow files, the files every member
carries, the manifest declarations of the flow, its forge's secret NAMES and each branch role's required contexts.
Members are compared within ONE forge host -- what a forge requires is derived per forge
(:mod:`dev_lab.dev.forgeprotect`), so a Gitea member is no GitHub member's peer. A feature some peer holds and a
member lacks is a finding naming who holds it, unless the machine file declares it an intended exception::

    [family.exceptions]
    some-repo = ["workflow:continue.yml"]

A secret no render REQUIRES is the other direction: held, and read by nothing the kit renders -- BAGGAGE, named on
every holder for the user to delete or to keep by declaring it. The required set is derived (the review task's
secret name, :func:`dev_lab.dev.taskkeys.secret_name`), never a list of old names.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Final

from dev_lab.dev.ciworkflows import WORKFLOW_DIRS
from dev_lab.dev.family.members import Facts, Finding
from dev_lab.dev.lanepolicy import load_policy

__all__ = ['FILES', 'compare', 'features']

#: The files every member carries (the onboarding page's entry point and its Claude alias).
FILES: Final = ('AGENTS.md', 'CLAUDE.md')


def features(root: Path, facts: Facts) -> frozenset[str]:
    """The member at *root*'s profile: local declarations and files, and its forge's *facts*."""
    found = {f'workflow:{p.name}' for d in WORKFLOW_DIRS.values() for p in (root / d).glob('*.yml')}
    found |= {f'file:{name}' for name in FILES if (root / name).is_file()}
    try:
        policy = load_policy(root)
        found |= {'manifest:pr_merges_since'} if policy.pr_merges_since else set()
    except ValueError:
        pass
    text = (root / 'pyproject.toml').read_text(encoding='utf-8') if (root / 'pyproject.toml').is_file() else ''
    found |= {'manifest:ephemeral'} if 'ephemeral' in text else set()
    found |= {f'secret:{name}' for name in facts.secrets}
    found |= {f'protect:{role}:{context}' for role, contexts in facts.contexts.items() for context in contexts}
    return frozenset(found)


def compare(
    profiles: Mapping[str, tuple[str, frozenset[str]]],
    exceptions: Mapping[str, Collection[str]],
    required: Collection[str],
) -> list[Finding]:
    """Every feature a member lacks that a peer on its forge holds, and every unrequired secret held; less declared.

    A secret is a peer's feature only when it is *required* (what the kit's renders read); any other secret a member
    holds is BAGGAGE on that member.
    """
    by_host: dict[str, dict[str, frozenset[str]]] = defaultdict(dict)
    for name, (host, held) in profiles.items():
        by_host[host][name] = held
    needed = {f'secret:{name}' for name in required}
    found = []
    for peers in by_host.values():
        union = frozenset(f for f in frozenset().union(*peers.values()) if not f.startswith('secret:') or f in needed)
        for name, held in sorted(peers.items()):
            excused = set(exceptions.get(name, ()))
            for feature in sorted(union - held - excused):
                holders = ', '.join(sorted(p for p, h in peers.items() if feature in h))
                found.append(Finding(name, f'lacks: {feature} (held by {holders}) -- render, protect or sync it, '
                                           'or declare [family.exceptions]'))  # fmt: skip
            spare = sorted(f for f in held - excused - needed if f.startswith('secret:'))
            found += [Finding(name, f'baggage: {f} -- no render reads it; delete it, or declare it') for f in spare]
    return found
