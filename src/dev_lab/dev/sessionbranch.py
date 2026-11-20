"""A SESSION BRANCH IS PROTECTED AT PUSH: three local invariants, judged on git's own pre-push lines.

User ruling 2026-10-13: every session has ONE branch it leads (``[tool.dev_lab.branchset] sessions``,
the integration branch among them), and that branch is protected for what it IS, never for where it is
checked out or which box pushes it -- both move.

``ONE-WRITER-PER-SESSION-BRANCH`` (P1) is git's own, and nothing is built for it (user ruling 2026-10-14:
no lease refs -- every push would read and write origin). LOCALLY a branch is checked out in at most one
worktree, so the sessions of one host and repo, one per worktree, never share a branch. REMOTELY a plain
push is compare-and-swap: origin refuses a non-fast-forward, so a writer working on a stale tip loses and
must merge first -- and P3 below refuses the force that would bypass it.

The invariants refused here by name, with NO network call beyond the push itself:

* ``PUBLISH-IS-THE-LOCAL-REF`` (P2) -- a push to ``refs/heads/X`` carries the local branch ``X``: its local
  ref, with ``HEAD`` resolved, IS ``refs/heads/X``. ``HEAD:X`` from another branch, ``Y:X`` and a bare sha
  are refused. Any checkout may publish ``X`` -- none needs it checked out. And EVERY local branch ``Y`` is
  published only as ``Y``: ``Y:Z`` and a bare push whose git upstream names another branch are refused, so a
  lane cut from ``origin/<integration>`` never lands there by accident. A detached HEAD and a bare sha name no
  branch, so they are refused onto EVERY branch (``git checkout --detach`` then ``HEAD:pr/x`` landed a lane on a
  ``pr/`` name, acme-consumer #5541) -- save the forge's own pushers' branches, :data:`MACHINE_BRANCHES`.
* ``SESSION-HISTORY-ONLY-GROWS`` (P3) -- the old remote tip git hands the hook is an ancestor of the new
  one; a forced non-fast-forward and a deletion are refused. ONE place: no other hook judges this.
* ``INTEGRATION-IS-MERGES-ONLY`` (P4) -- every new first-parent commit of the integration branch is a
  two-parent merge naming its branch in a ``Merged-Branch:`` trailer, and the merge audit
  (:func:`dev_lab.dev.mergeaudit.judge`, the SAME judgement the commit-msg hook makes) passes on it.
  Judged from ``[tool.dev_lab.integrator] merges_only_since`` forward: no retroactive check.
* ``INTEGRATION-TAKES-ONLY-FORGE-MERGES`` (P5) -- once ``[tool.dev_lab.integrator] pr_merges_since`` is
  declared, the integration branch moves ONLY by the forge's server-side merge of a pull request
  (:mod:`dev_lab.dev.forgemerge`). Such a merge is on origin before any client holds it, so a client push
  that adds ANY first-parent commit past origin's tip (and past the declared start) is not one, and is refused.
  It replaces P4 for that branch. The ONE bypass is in the history: a push whose every new first-parent
  commit carries a non-empty ``Break-Glass: <reason>`` trailer is admitted (:mod:`dev_lab.dev.breakglass`), its
  heads' reviews unasked: the review is advisory (user rulings 2026-11-11/12), so it never holds a push either.
* ``ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES`` (P6) -- a push that creates or updates ``refs/heads/X`` lands only
  when the branch set admits ``X`` (:meth:`BranchSet.admits`: a declared long-lived branch, or one in an
  ``ephemeral`` namespace, default ``pr/*``). Fan-out ``lane/`` ``feat/`` ``fix/`` branches stay local; a
  feature is published as its one ``pr/<feature>``. A deletion is P3's business, so origin's existing
  undeclared branches may still be deleted -- never automatically here -- and take no new push. Tags are not
  branches and are not judged.
* ``PUSHED-HEAD-CARRIES-ITS-TASK`` (P7, user ruling D25 2026-11-17) -- branch names follow the task: an AGENT
  session (:func:`~dev_lab.dev.native_session.session_of`) creates or updates a head in the task namespace
  (``[tool.dev_lab.branchset] task_heads``, default ``pr/<task>/<feature>``) only under the task its user bound it
  to (:mod:`dev_lab.dev.taskbinding`), one feature per PR. Another task's head, a flat ``pr/<feature>`` and the bare
  ``pr/<task>`` are refused naming ``pr/<task>/``; with no bound task the refusal names how a task is bound. A human
  push and the forge (which holds no session) are not judged; local fan-out never reaches origin.

THE FORGE DECIDES; this hook is EARLY FEEDBACK (user ruling 2026-11-07: a family check never depends on a consumer's
local hook being current). The same :func:`refusals` runs on every open PR head as the forge's ``session-branch``
status (:func:`head_refusals`, :mod:`dev_lab.dev.forgeheadgate`), which the merge requires; the integration branch
itself is protected by the forge (:mod:`dev_lab.dev.forgeprotect`).

Every ref is judged by the declaration its pushed tip carries, never the working tree's; a deletion carries
no content, so it is judged by the integration branch's declaration (``origin/<integration>``, else the
trunk's, else ``HEAD``'s) -- never the deleted tip's, nor a stale checkout's. There is no bypass:
a guard that cannot judge (no branch set at that tip) refuses.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import metrics
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, branchset_at
from dev_lab.dev.breakglass import BREAK_GLASS, reason
from dev_lab.dev.componentbump import LANE as COMPONENT_LANE
from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.native_session import session_of
from dev_lab.dev.relock import BRANCH as RELOCK_BRANCH
from dev_lab.dev.taskbinding import DOOR, head_for, session_task, slug_of

__all__ = [
    'HOOK_ID',
    'MACHINE_BRANCHES',
    'MERGED_BRANCH',
    'P2',
    'P3',
    'P4',
    'P5',
    'P6',
    'P7',
    'head_refusals',
    'main',
    'merged_branch',
    'refusals',
]

P2: Final = 'PUBLISH-IS-THE-LOCAL-REF'
P3: Final = 'SESSION-HISTORY-ONLY-GROWS'
P4: Final = 'INTEGRATION-IS-MERGES-ONLY'
P5: Final = 'INTEGRATION-TAKES-ONLY-FORGE-MERGES'
P6: Final = 'ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES'
P7: Final = 'PUSHED-HEAD-CARRIES-ITS-TASK'
#: The id this guard runs under in ``githooks/base.toml``: its refusals are logged under it, so a bypass is too.
HOOK_ID: Final = 'session-branch'
#: The branches the forge's own pushers publish from a detached tip or a sha (relock, component bump): the ONLY
#: targets a source naming no branch may land on.
MACHINE_BRANCHES: Final = frozenset({RELOCK_BRANCH, COMPONENT_LANE})
#: The trailer an integration merge names its merged branch under.
MERGED_BRANCH: Final = 'Merged-Branch'

_GIT: Final = shutil.which('git') or 'git'
_HEADS: Final = 'refs/heads/'
_FIELDS: Final = 4
_PARENTS: Final = 2
_TRAILER: Final = re.compile(rf'^{MERGED_BRANCH}:\s*(\S+)\s*$', re.MULTILINE)

#: What every refusal here ends with: this hook is early feedback, the forge's status is the gate.
EARLY: Final = (
    f'  (early feedback: the forge posts this judgement as the {HOOK_ID!r} status on the PR head, and the merge '
    'requires it)'
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=120
    )


def _zero(sha: str) -> bool:
    return set(sha) == {'0'}


def merged_branch(message: str) -> str | None:
    """The branch a merge commit's ``Merged-Branch:`` trailer names, or ``None``."""
    found = _TRAILER.findall(message)
    return found[-1] if found else None


def _merges_only(root: Path, policy: Policy, old: str, new: str) -> list[str]:
    """P4 over the first-parent commits *new* adds to the integration branch past *old* and the declared start."""
    since = policy.merges_only_since
    if _zero(old) and not since:
        return [
            (
                f'{P4}: this push CREATES {policy.integration}, so its whole history would be judged; declare '
                f'[tool.dev_lab.integrator] merges_only_since = "<sha>" to start the rule there'
            )
        ]
    excluded = [f'^{sha}' for sha in (old, since) if sha and not _zero(sha)]
    listed = _git(root, 'rev-list', '--first-parent', '--reverse', new, *excluded)
    if listed.returncode != 0:
        return [f'{P4}: cannot list the new commits of {policy.integration}: {listed.stderr.strip()}']
    found = []
    for sha in listed.stdout.split():
        parents = _git(root, 'rev-list', '--parents', '-n', '1', sha).stdout.split()[1:]
        message = _git(root, 'log', '-1', '--format=%B', sha).stdout
        if len(parents) != _PARENTS:
            found.append(f'{P4}: {sha[:12]} is not a merge ({len(parents)} parent(s)); land it as a forge-merged PR')
            continue
        name = merged_branch(message)
        if name is None or name == policy.integration:
            found.append(f'{P4}: {sha[:12]} names no {MERGED_BRANCH}: <branch> trailer; land it as a forge-merged PR')
            continue
        try:
            problems = judge(root, parents, sha, message, roots=policy.test_roots, label=sha[:12])
        except MergeAuditError as error:
            problems = (str(error),)
        found += [f'{P4}: {sha[:12]} merge-audit: {problem}' for problem in problems]
    return found


def _forge_merges_only(root: Path, policy: Policy, old: str, new: str) -> list[str]:
    """P5: the first-parent commits *new* adds past origin's *old* and the declared start -- every one refused."""
    excluded = [f'^{sha}' for sha in (old, policy.pr_merges_since) if not _zero(sha)]
    listed = _git(root, 'rev-list', '--first-parent', new, *excluded)
    if listed.returncode != 0:
        return [f'{P5}: cannot list the new commits of {policy.integration}: {listed.stderr.strip()}']
    added = listed.stdout.split()
    messages = {sha: _git(root, 'log', '-1', '--format=%B', sha).stdout for sha in added}
    unglassed = [sha for sha in added if not reason(messages[sha])]
    if not unglassed:
        _record_break_glass(root, new, messages)
        return []
    return [
        (
            f'{P5}: this push adds {len(added)} commit(s) to {policy.integration}, {len(unglassed)} with no '
            f'{BREAK_GLASS}: <reason> trailer (newest {unglassed[0][:12]}); it moves only by the forge merging a '
            f'pull request. Push a pr/<topic> branch and open a PR into {policy.integration} instead -- or, '
            f'only when the forge itself is down or its auto-merge broken, give EVERY new commit a '
            f'{BREAK_GLASS}: <reason> trailer'
        )
    ]


def _record_break_glass(root: Path, new: str, messages: dict[str, str]) -> None:
    """The metrics of an admitted Break-Glass push: one bypass, and one hand action per commit it carries.

    *messages* maps each new first-parent commit to its message, newest first as ``rev-list`` lists them.
    """
    if not messages:
        return
    repo = metrics.repo_of(root)
    metrics.record(metrics.BYPASS, root=root, repo=repo, rule=HOOK_ID, reason=BREAK_GLASS, vcs_ref_head_revision=new)
    for sha, message in reversed(messages.items()):
        branch = merged_branch(message) or ''
        metrics.break_glass(root, repo=repo, sha=sha, branch=branch, reason=reason(message))


def _local(root: Path, local: str) -> str:
    if local != 'HEAD':
        return local
    done = _git(root, 'symbolic-ref', '-q', 'HEAD')
    return done.stdout.strip() if done.returncode == 0 else 'a detached HEAD'


def _judge_ref(root: Path, policy: Policy, fields: Sequence[str]) -> list[str]:
    """P2, P3 and P4 for one pre-push line whose remote ref is a guarded branch."""
    local, sha, remote, old = fields
    branch = remote[len(_HEADS) :]
    if _zero(sha):
        return [f'{P3}: deleting {branch} is refused; a session branch only grows']
    found = []
    if (named := _local(root, local)) != remote:
        found.append(
            f'{P2}: {branch} is published only from the local branch {branch}, not {named}; '
            f'merge into {branch} and push `{branch}`'
        )
    if not _zero(old) and _git(root, 'merge-base', '--is-ancestor', old, sha).returncode != 0:
        found.append(
            f'{P3}: {branch} at {old[:12]} on origin is not an ancestor of {sha[:12]}; history only grows: '
            f'fetch, merge origin/{branch} into {branch}, push again (never force)'
        )
    if branch == policy.integration and policy.pr_merges_since:
        found += _forge_merges_only(root, policy, old, sha)
    elif branch == policy.integration:
        found += _merges_only(root, policy, old, sha)
    return found


def rename_remedy(branch: str, task: str | None = None) -> str:
    """The ONE exit for a feature on a local branch origin does not hold: rename it to its ``pr/`` name, push that.

    ``fix/x`` becomes ``pr/x`` (the namespace dropped, the feature kept), so P6 and P2 name the same command
    and the first remedy never walks into the second refusal (2026-11-02, dev-lab #68). A session bound to task
    *task* (a slug, :mod:`dev_lab.dev.taskbinding`) gets its task's head ``pr/<task>/x`` instead (D5, 2026-11-15).
    """
    target = f'pr/{branch.split("/", 1)[-1]}' if task is None else head_for(task, branch.rsplit('/', 1)[-1])
    return f'rename it and push: `git branch -m {branch} {target}` then `push -u origin {target}`'


def _bound_slug() -> str | None:
    """The slug of the task this process's session is bound to, or ``None`` (none, or no readable session)."""
    try:
        task = session_task(os.environ)
    except ValueError:
        return None
    return None if task is None else slug_of(task)


def _undeclared(declared: BranchSet, branch: str) -> list[str]:
    """P6 for a create or update of *branch*: refused unless the branch set admits it."""
    if declared.admits(branch):
        return []
    names = ', '.join(sorted(declared.declared))
    globs = ', '.join(declared.ephemeral) or 'none'
    return [
        (
            f'{P6}: origin holds only the declared branches ({names}) and the ephemeral namespaces ({globs}), '
            f'not {branch}; {rename_remedy(branch, _bound_slug())}'
        )
    ]


def _off_task(root: Path, declared: BranchSet, branch: str, env: Mapping[str, str]) -> list[str]:
    """P7 for a create or update of *branch* by the agent session *env* names: a task head carries its bound task."""
    namespace = declared.task_namespace
    if not namespace or not branch.startswith(namespace):
        return []
    try:
        if not session_of(env):
            return []
        task = session_task(env, start=root)
    except ValueError as unread:
        return [f'{P7}: {branch} is a task head and this agent session cannot be read: {unread}']
    shape = declared.task_heads
    feature = branch.rsplit('/', 1)[-1]
    if task is None:
        return [
            (
                f'{P7}: a pushed head carries its task ({shape}), and this agent session is bound to no task, '
                f'so {branch} has none; a short fix binds to an open task too (any task the family holds, from any '
                f'repo once the task is a forge issue), and there are no flat pr/<feature> heads.\n'
                f'Door: {DOOR}; then push it as {declared.task_head("<task>", feature)}.'
            )
        ]
    slug = slug_of(task)
    if declared.carries_task(branch, slug):
        return []
    head = declared.task_head(slug, feature)
    return [
        (
            f'{P7}: this session is bound to task {task}, so its pushed heads are {declared.task_head(slug, "")}'
            f'<feature>, one feature per PR; {branch} is not one.\n'
            f'Door: `git branch -m {branch} {head}` then `push -u origin {head}`.'
        )
    ]


def _misnamed(root: Path, local: str, target: str) -> list[str]:
    """P2 for a branch no session declares: a local branch lands only as itself, a detached tip only on a machine's."""
    named = _local(root, local)
    if named == f'{_HEADS}{target}':
        return []
    if named.startswith(_HEADS):
        branch = named[len(_HEADS) :]
        own = f'push `git push origin {branch}`'
        exit_text = rename_remedy(branch, _bound_slug()) if target.startswith('pr/') else own
        return [f'{P2}: the local branch {branch} is published only as {branch}, not {target}; {exit_text}']
    if target in MACHINE_BRANCHES:
        return []
    return [
        (
            f'{P2}: {target} is published only from a local branch, not {named}; check out the branch whose work it is '
            f'and push it as itself: `git switch -c {target}` then `push -u origin {target}`'
        )
    ]


def _deletion_rev(root: Path) -> str:
    """The rev a deletion is judged by: ``origin/<integration>``, else ``origin/<trunk>``, else ``HEAD``.

    The names come from ``HEAD``'s ``[tool.dev_lab.integrator]``; when it cannot be read, ``HEAD`` itself is the
    rev, so the deletion is refused by name there: a stale checkout must not decide what deleting a ref means.
    """
    try:
        policy = policy_at(root, 'HEAD')
    except (ValueError, OSError, subprocess.CalledProcessError):
        return 'HEAD'
    for name in (policy.integration, policy.trunk):
        rev = f'refs/remotes/origin/{name}'
        if _git(root, 'rev-parse', '-q', '--verify', f'{rev}^{{commit}}').returncode == 0:
            return rev
    return 'HEAD'


def _trusted(root: Path, pushed: Policy | None, old: str) -> Policy | None:
    """*pushed*, unless it drops or renames the integration branch origin's tip *old* declares: then that one.

    Fail closed: a push cannot switch the integration audits off by dropping (*pushed* ``None``) or renaming
    the table it is judged by -- such a change is judged by the declaration origin already holds, and binds
    once it lands. A pushed table that keeps the name still binds at once, so a tightening applies.
    """
    if _zero(old) or _git(root, 'cat-file', '-e', f'{old}^{{commit}}').returncode != 0:
        return pushed
    try:
        held = policy_at(root, old)
    except (ValueError, subprocess.CalledProcessError):
        return pushed
    return held if pushed is None or held.integration != pushed.integration else pushed


def refusals(root: Path, lines: str, env: Mapping[str, str] | None = None) -> list[str]:
    """Every refusal for the push *lines* describe, from local reads; *env* names the pushing session (P7).

    Each ref is judged by the declaration its PUSHED tip carries -- never the working tree's. A deletion
    pushes no content, so it is judged by the integration branch's (:func:`_deletion_rev`), never the deleted
    ref's old tip, which may predate or outlive the table.
    """
    env = os.environ if env is None else env
    found: list[str] = []
    for fields in (line.split() for line in lines.splitlines()):
        if len(fields) != _FIELDS or not fields[2].startswith(_HEADS):
            continue
        at = _deletion_rev(root) if _zero(fields[1]) else fields[1]
        label = at if _zero(fields[1]) else at[:12]
        try:
            declared = branchset_at(root, at)
        except (BranchSetNotDeclared, ValueError, subprocess.CalledProcessError) as exc:
            found.append(f'{P2}: {label} declares no readable branch set, so {fields[2]} cannot be judged: {exc}')
            continue
        try:
            policy: Policy | None = policy_at(root, at)
        except (ValueError, subprocess.CalledProcessError) as exc:
            found.append(f'{P2}: {label} declares no readable integrator, so {fields[2]} cannot be judged: {exc}')
            policy = None
        if not _zero(fields[1]):
            found += _undeclared(declared, fields[2][len(_HEADS) :])
            found += _off_task(root, declared, fields[2][len(_HEADS) :], env)
        if fields[2] in {f'{_HEADS}{name}' for name in declared.sessions | {declared.trunk}}:
            if (judged := _trusted(root, policy, fields[3])) is not None:
                found += _judge_ref(root, judged, fields)
        elif not _zero(fields[1]):
            found += _misnamed(root, fields[0], fields[2][len(_HEADS) :])
    return found


def head_refusals(root: Path, sha: str, branch: str) -> list[str]:
    """:func:`refusals` for *branch* at *sha* as a forge holds an open PR head: published as itself, created.

    The forge's ``session-branch`` status (:mod:`dev_lab.dev.forgeheadgate`) calls this, so a stale or missing
    pre-push shim never disarms the rule. The forge pushes for no session, so P7 is the pusher's alone.
    """
    ref = f'{_HEADS}{branch}'
    return refusals(root, f'{ref} {sha} {ref} {"0" * 40}', env={})


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # git passes the remote name and url; nothing here reads the remote
    top = _git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip()
    found = refusals(Path(top or Path.cwd()), '' if sys.stdin.isatty() else sys.stdin.read())
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), EARLY, '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
