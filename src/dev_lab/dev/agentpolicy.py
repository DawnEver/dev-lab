"""AGENT-POLICY: the ONE table of which agent may run which family door, and what each door is for.

User ruling 2026-11-07: agent permissions and hooks have one source of truth. Before it, the same fact lived
three times -- ``autodoors.VERB_DOORS`` (the allow rows), ``automode.INTENTS`` (the classifier's prose) and the
remedy text of the deny row each door is the exit from -- and the copies drifted: FORGE-WRITE-VIA-CLI's remedy
named ``pr create|close`` while the doors also held ``ready`` and ``draft``.

A ROW (:class:`Door`) is a door and everything said about it:

* ``argv`` -- the argv PREFIX the door is, runner first (``python`` means the checkout's venv interpreter,
  rendered as :data:`dev_lab.dev.doorrows.INTERPRETERS`, the checkout's own interpreter of each platform
  layout). Empty for an intent the classifier judges with no narrow door behind it.
* ``actor`` -- who may run it: :data:`SUBAGENT` (any agent), :data:`MAIN` (the main session only: a subagent
  is refused it by SUBAGENT-NO-PUSH, whose pattern is derived from these rows) or :data:`USER` (no agent: it
  renders no allow row and no intent, and a remedy names it as the user's).
* ``intent`` -- ONE string, both the allow row's provenance and the auto-mode classifier's intent. Prose, never
  a spelling (:func:`dev_lab.dev.automode.spelled_commands` refuses one).
* ``deny`` -- the deny row whose exit this door is; that row's remedy text is DERIVED from its doors
  (:func:`exits_of`), never hand-copied.

Every renderer reads this table: :mod:`dev_lab.dev.autodoors` (the Claude allow rows and the Codex rules),
:mod:`dev_lab.dev.automode` (the classifier intents), the deny rows (their remedies and SUBAGENT-NO-PUSH's
pattern), and :mod:`dev_lab.dev.famfiles`, which writes them all into a repo. A REPO-SPECIFIC row is declared
in that repo's ``[tool.dev_lab.policy]`` (:mod:`dev_lab.dev.repopolicy`), never in a hand-written module.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev._policy_door import ACTORS, MAIN, SUBAGENT, USER, Door, module_argv
from dev_lab.dev.remotedoors import REMOTE_DOORS

#: The row shape (:class:`Door`, the actors) lives in :mod:`dev_lab.dev._policy_door`; this module is its one
#: public face, so every reader imports both from here.
__all__ = [
    'ACTORS',
    'MAIN',
    'POLICY',
    'SUBAGENT',
    'USER',
    'Door',
    'exits_of',
    'module_verbs',
]


def _forge(*verbs: str) -> tuple[str, ...]:
    return ('python', '-m', 'dev_lab.dev.forge', *verbs)


def _desktop(verb: str) -> tuple[str, ...]:
    return ('python', '-m', 'lab_commons.desktop', verb)


_FORGE_WRITE: Final = 'FORGE-WRITE-VIA-CLI'

#: THE TABLE. Ordered as a reader looks for a door: the local verdict and housekeeping, the forge's read side, its
#: write side, publishing, then the remote doors
#: (:mod:`dev_lab.dev.remotedoors`, spliced in here so this stays the ONE table).
POLICY: Final[tuple[Door, ...]] = (
    # ---- local, any agent
    Door(module_argv('verify'), SUBAGENT, 'Running the family verdict over the tests a change touched.'),
    Door(module_argv('stoprun'), SUBAGENT, 'Stopping one identifiable run this session started, with its subtree.'),
    Door(module_argv('netverb'), SUBAGENT, 'A network git or uv verb through the bounded-retry door.'),
    Door(
        module_argv('dep', '--bootstrap'),
        SUBAGENT,
        "Creating a checkout's own environment through the checked dependency door.",
    ),
    Door(
        module_argv('branchset'),
        SUBAGENT,
        'The branch census; applying it deletes merged local branches, never remote.',
    ),
    Door(
        module_argv('worktrees'),
        SUBAGENT,
        'The worktree census; pruning removes only a clean, pushed worktree, archiving moves its outputs home.',
    ),
    Door(module_argv('family', 'check'), SUBAGENT, "Read-only: every fact of this machine's family members, named."),
    Door(module_argv('family', 'join'), MAIN, 'Making a repo a family member: clone, record, protect, set its secret.'),
    Door(
        module_argv('famfiles'), SUBAGENT, "Rendering the family project files of a checkout from the kit's one source."
    ),
    Door(module_argv('autodoors'), SUBAGENT, "Rendering this checkout's door rules for each agent client."),
    # The desktop tool's READ verbs (user ruling 2026-11-14 E6); its acts (press, set-value, close) stay prompted.
    Door(_desktop('windows'), SUBAGENT, 'Read-only: the top-level desktop windows, listed.'),
    Door(_desktop('capture'), SUBAGENT, 'Read-only: an image of one desktop window, captured.'),
    Door(_desktop('controls'), SUBAGENT, "Read-only: one desktop window's control tree, listed."),
    Door(
        module_argv('hook_install', '--install'),
        SUBAGENT,
        'Installing or refreshing the kit git hooks in a checkout of this repository.',
    ),
    # ---- the forge, read side
    Door(_forge('watch'), SUBAGENT, 'Read-only: following one commit verdict on the forge until it settles.'),
    Door(
        _forge('queue'),
        SUBAGENT,
        'Read-only monitoring of the forge queue: what each serve host is running and what waits.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('sshhold', 'open'),
        MAIN,
        'Opening one held login session to a key and authenticator-code host, answered with the one-time code the '
        'user supplied in this conversation for it, within the machine ceiling on its hours; never an invented, '
        'stored, logged or reused code.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('sshhold', 'run'),
        MAIN,
        'Running one command on a login session the user authenticated, audited.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('sshhold', 'credential'),
        MAIN,
        "Storing a forge token on a held account's git credential helper, the token read on standard input from "
        'where the user placed it; never a token typed into a command line, a log or a file the agent writes.',
    ),
    Door(module_argv('sshhold', 'close'), MAIN, 'Ending a held login session.'),
    Door(module_argv('sshhold', 'status'), MAIN, 'Read-only: the held login sessions and time left.'),
    Door(_forge('status', 'list'), SUBAGENT, 'Read-only: the commit statuses the forge holds for one commit.'),
    Door(
        _forge('run', 'show'),
        SUBAGENT,
        'Read-only: what a cluster run of one commit learned, as the forge published it.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        (),
        SUBAGENT,
        "Editing a forge request issue's body to correct a malformed field, such as a short commit id to the "
        'full one, so the forge can serve it.',
    ),
    # ---- the forge, write side
    Door(_forge('issue', 'create'), SUBAGENT, 'Filing an issue on the forge through the family door.', _FORGE_WRITE),
    Door(_forge('issue', 'comment'), SUBAGENT, 'Commenting on a forge issue through the family door.', _FORGE_WRITE),
    Door(_forge('issue', 'close'), SUBAGENT, 'Closing a forge issue through the family door.', _FORGE_WRITE),
    Door(
        _forge('pr', 'create'),
        MAIN,
        'Opening a draft pull request onto the integration branch through the forge door; the agent does this '
        'itself and never hands it to the user.',
        _FORGE_WRITE,
    ),
    Door(
        _forge('pr', 'ready'),
        MAIN,
        'Marking a draft pull request ready for review once its pushed head is current, from any checkout.',
        _FORGE_WRITE,
    ),
    Door(
        _forge('pr', 'draft'),
        MAIN,
        'Returning a pull request to draft, so nothing reviews or merges it.',
        _FORGE_WRITE,
    ),
    Door(
        _forge('pr', 'close'),
        MAIN,
        'Closing a pull request with its reason posted first; its branch is never deleted.',
        _FORGE_WRITE,
    ),
    Door(
        _forge('pr', 'continue'),
        MAIN,
        'Opening the continuation pull request of a branch whose pull request already merged and '
        'whose tip moved past it (LANDED-BRANCH-CONTINUES).',
        _FORGE_WRITE,
    ),
    Door(
        _forge('review', 'carry'),
        MAIN,
        'Recording the disposition of a finding a continuation pull request carries: resolved, or deferred with '
        'a required reason.',
        _FORGE_WRITE,
    ),
    Door(_forge('pr', 'close-landed'), MAIN, 'Closing pull requests whose head is already merged into their base.'),
    Door(
        _forge('pr', 'close-superseded'),
        MAIN,
        'Closing an open pull request whose content was salvaged into another open pull request or a commit, '
        'with a comment naming the replacement; its branch is never deleted.',
    ),
    Door(
        _forge('pr', 'breakglass'),
        MAIN,
        'A Break-Glass merge into the integration branch inside a wave the user opened with a one-time code, '
        "at the pull request's current head, past its review AND its tests -- unrun, pending or red (user ruling "
        '2026-11-11: the tests are the slowest step) -- with the test state at merge time named in the PR comment, '
        'the audit and the wave summary, and carried by a commit trailer that states the reason, so every use '
        'stays in the history it bypassed.',
    ),
    Door(
        _forge('breakglass', 'open'),
        MAIN,
        'Opening a Break-Glass wave on a consent credential the user granted for it, or with the one-time code the '
        'user supplied in this conversation for that wave; never a code the agent did not receive from the user.',
    ),
    Door(
        ('python', '-m', 'dev_lab.ops.consent', 'grant'),
        MAIN,
        'Granting one consent credential with the cluster code the user supplied in this conversation for '
        'it (user ruling 2026-11-08: only the user provides the code, the agent runs the grant); never an '
        'invented, stored, logged or reused code.',
    ),
    Door(
        _forge('review', 'takeover'),
        MAIN,
        "Reviewing a head the forge's review has not reached, posted as advice on its pull request.",
    ),
    Door(
        _forge('review', 'again'),
        MAIN,
        'Asking the forge to review a PR again once a security finding in it is fixed '
        '(user ruling 2026-11-06: the review is one-shot advice; always allowed).',
    ),
    Door(
        _forge('security', 'release'),
        MAIN,
        'Releasing a pull request head clean under its own new security exemptions, the reason recorded.',
    ),
    Door(
        _forge('cancel-stuck'),
        MAIN,
        "Cancelling the forge's own test jobs of one commit that are confirmed stuck: busy at full CPU with no "
        'new test result for longer than a multiple of their measured duration. Never any other job.',
    ),
    Door(
        _forge('sync'),
        SUBAGENT,
        "Merging the integration branch into this agent's own branch through the forge door, with the relock of "
        'the floated siblings and the re-render of every generated family file it brings, committed locally and '
        'never pushed: publishing the result stays with the main session.',
    ),
    # ---- publishing
    Door(
        (),
        MAIN,
        "Publishing this session's pull request branch of a family toolchain repository to that repository's own "
        'origin through the bounded-retry push door; the repository pre-push rows, its public root among them, stay '
        'the guard and are never bypassed.',
    ),
    Door(
        module_argv('integrate', 'promote'),
        MAIN,
        'Promoting an integration commit whose every test part stands passed, as a fast-forward of the trunk.',
    ),
    Door(
        ('git', 'merge', '--ff-only'),
        MAIN,
        'A fast-forward of a trunk the main session publishes; never a merge commit.',
    ),
    Door(
        module_argv('branchprune', 'delete'),
        MAIN,
        'Deleting a remote branch only when every commit on it is already on the integration branch or on '
        'another live branch or open pull request; never a force push and never a lossy delete.',
    ),
    Door(
        module_argv('branchprune', 'delete-tag'),
        MAIN,
        'Deleting a remote tag the user approved in their own words, only when its commit is on the integration '
        'branch or the trunk; never a lossy delete.',
    ),
    Door(
        ('gh', 'workflow', 'enable'),
        MAIN,
        'Re-enabling a GitHub Actions workflow of a family repository that the integrator paused '
        '(user ruling 2026-11-07).',
    ),
    Door(
        ('gh', 'workflow', 'disable'),
        MAIN,
        'Pausing a GitHub Actions workflow of a family repository, so it starts no new runs until re-enabled '
        '(user ruling 2026-11-07).',
    ),
    # ---- remote: :data:`dev_lab.dev.remotedoors.REMOTE_DOORS`
    *REMOTE_DOORS,
)


def exits_of(rule_id: str, module: str) -> str:
    """The verbs of *module*'s doors that are *rule_id*'s exits, grouped by noun: ``issue create|close, pr ready``.

    DERIVED, so a deny row's remedy cannot name fewer doors than the table holds -- the FORGE-WRITE-VIA-CLI
    defect this table was built to end.
    """
    grouped: dict[str, list[str]] = {}
    for door in POLICY:
        if door.deny == rule_id and door.argv[:3] == ('python', '-m', module) and door.argv[3:]:
            noun, *verb = door.argv[3:]
            grouped.setdefault(noun, []).extend(verb)
    return ', '.join(f'{noun} {"|".join(verbs)}'.strip() for noun, verbs in grouped.items())


def module_verbs(actor: str) -> dict[str, tuple[tuple[str, ...], ...]]:
    """``{module: (verbs, ...)}`` of every ``python -m`` door *actor* alone may run -- what a deny pattern refuses."""
    out: dict[str, list[tuple[str, ...]]] = {}
    for door in POLICY:
        if door.actor == actor and door.argv[:2] == ('python', '-m'):
            out.setdefault(door.argv[2], []).append(door.argv[3:])
    return {module: tuple(verbs) for module, verbs in out.items()}
