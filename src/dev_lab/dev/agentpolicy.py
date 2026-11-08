"""AGENT-POLICY: the ONE table of which agent may run which family door, and what each door is for.

User ruling 2026-11-07: agent permissions and hooks have one source of truth. Before it, the same fact lived
three times -- ``autodoors.VERB_DOORS`` (the allow rows), ``automode.INTENTS`` (the classifier's prose) and the
remedy text of the deny row each door is the exit from -- and the copies drifted: FORGE-WRITE-VIA-CLI's remedy
named ``pr create|close`` while the doors also held ``ready`` and ``draft``.

A ROW (:class:`Door`) is a door and everything said about it:

* ``argv`` -- the argv PREFIX the door is, runner first (``python`` means the checkout's venv interpreter,
  rendered as :data:`INTERPRETERS`, the checkout's own interpreter of each platform layout). Empty for an
  intent the classifier judges with no narrow door behind it.
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

from dataclasses import dataclass
from typing import Final

from dev_lab.dev.venvpath import VENV_INTERPRETER_GLOB, VENV_LAYOUTS

__all__ = [
    'ACTORS',
    'INTERPRETERS',
    'MAIN',
    'POLICY',
    'SUBAGENT',
    'USER',
    'Door',
    'allow_rows',
    'exits_of',
    'literal_rows',
    'module_verbs',
]

#: The main session: it publishes (MAIN-SESSION-PUBLISHES) and changes forge state.
MAIN: Final = 'main'
#: Any agent, the main session's subagents included.
SUBAGENT: Final = 'subagent'
#: The user alone: no agent is allowed it, whatever mode the client runs in.
USER: Final = 'user'
ACTORS: Final = (MAIN, SUBAGENT, USER)

_RUNNERS: Final = ('python', 'git', 'sh', 'gh')

#: The checkout's own interpreter, one LITERAL per platform layout -- the only interpreter spelling a door row
#: carries. NOT :data:`dev_lab.dev.venvpath.VENV_INTERPRETER_GLOB` (``.venv/*/python*``): in a permission glob
#: the ``*`` after ``python`` also matches ``.exe -c <code>``, so ``.venv/*/python* -m <door> *`` admits
#: arbitrary code run AHEAD of the door (measured 2026-11-07, ``fnmatch``). Two literal rows admit only the door.
INTERPRETERS: Final = tuple('/'.join(VENV_LAYOUTS[name]) for name in sorted(VENV_LAYOUTS))


def literal_rows(entry: str) -> tuple[str, ...]:
    """*entry* with the interpreter glob rendered as one row per :data:`INTERPRETERS`; else *entry* alone."""
    if VENV_INTERPRETER_GLOB not in entry:
        return (entry,)
    return tuple(entry.replace(VENV_INTERPRETER_GLOB, head) for head in INTERPRETERS)


def allow_rows(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The ``permissions.allow`` rows of a door *argv*: per interpreter layout; a git door also as ``git -C *``."""
    runner, *rest = argv
    tail = ' '.join(rest)
    if runner == 'python':
        return tuple(f'Bash({head} {tail} *)' for head in INTERPRETERS)
    if runner == 'git':
        return (f'Bash(git {tail} *)', f'Bash(git -C * {tail} *)')
    return (f'Bash({runner} {tail} *)',)


@dataclass(frozen=True, slots=True)
class Door:
    """One door: its argv prefix, who may run it, what it is for (one string), and the deny row it answers."""

    argv: tuple[str, ...]
    actor: str
    intent: str
    deny: str | None = None

    def __post_init__(self) -> None:
        """Refuse an unknown actor or runner, an empty intent, and an allowed door with no argv."""
        if self.actor not in ACTORS:
            msg = f'{self.argv}: actor {self.actor!r} is none of {ACTORS}'
            raise ValueError(msg)
        if self.argv and self.argv[0] not in _RUNNERS:
            msg = f'{self.argv}: runner {self.argv[0]!r} is none of {_RUNNERS}'
            raise ValueError(msg)
        if not self.intent.strip():
            msg = f'{self.argv}: no intent -- say what the door is for, once'
            raise ValueError(msg)

    @property
    def allow_lines(self) -> tuple[str, ...]:
        """The ``permissions.allow`` rows: none for the user's doors or a door-less intent; git also as ``-C``."""
        return () if self.actor == USER or not self.argv else allow_rows(self.argv)


def _forge(*verbs: str) -> tuple[str, ...]:
    return ('python', '-m', 'dev_lab.dev.forge', *verbs)


def _module(name: str, *verbs: str) -> tuple[str, ...]:
    return ('python', '-m', f'dev_lab.dev.{name}', *verbs)


_FORGE_WRITE: Final = 'FORGE-WRITE-VIA-CLI'

#: THE TABLE. Ordered as a reader looks for a door: the local verdict and housekeeping, the forge's read side, its
#: write side, publishing, then the remote doors.
POLICY: Final[tuple[Door, ...]] = (
    # ---- local, any agent
    Door(_module('verify'), SUBAGENT, 'Running the family verdict over the tests a change touched.'),
    Door(_module('stoprun'), SUBAGENT, 'Stopping one identifiable run this session started, with its subtree.'),
    Door(_module('netverb'), SUBAGENT, 'A network git or uv verb through the bounded-retry door.'),
    Door(
        _module('dep', '--bootstrap'),
        SUBAGENT,
        "Creating a checkout's own environment through the checked dependency door.",
    ),
    Door(_module('branchset'), SUBAGENT, 'The branch census; applying it deletes merged local branches, never remote.'),
    Door(
        _module('worktrees'),
        SUBAGENT,
        'The worktree census; pruning removes only a clean, pushed worktree, archiving moves its outputs home.',
    ),
    Door(_module('famfiles'), SUBAGENT, "Rendering the family project files of a checkout from the kit's one source."),
    Door(_module('autodoors'), SUBAGENT, "Rendering this checkout's door rules for each agent client."),
    Door(
        _module('hook_install', '--install'),
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
        'Marking a draft pull request ready for review once its tree is clean and its head current.',
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
        'carried by a commit trailer that states the reason, so every use stays in the history it bypassed.',
    ),
    Door(
        _forge('breakglass', 'open'),
        MAIN,
        'Opening a Break-Glass wave on a consent credential the user granted for it.',
    ),
    Door(
        ('python', '-m', 'dev_lab.ops.consent', 'grant'),
        USER,
        'Granting one consent credential: the user alone, in their own terminal, with their authenticator code.',
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
    # ---- publishing
    Door(
        _forge('sync'), MAIN, "Merging the integration branch into this session's own branches through the forge door."
    ),
    Door(
        _module('integrate', 'promote'),
        MAIN,
        'Promoting an integration commit whose every test part stands passed, as a fast-forward of the trunk.',
    ),
    Door(
        ('git', 'merge', '--ff-only'),
        MAIN,
        'A fast-forward of a trunk the main session publishes; never a merge commit.',
    ),
    Door(
        _module('branchprune', 'delete'),
        MAIN,
        'Deleting a remote branch only when every commit on it is already on the integration branch or on '
        'another live branch or open pull request; never a force push and never a lossy delete.',
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
    # ---- remote
    Door(
        _module('hpcaccount', 'deploy-fleet'),
        MAIN,
        'Deploying or restarting the forge serve hosts of the trusted fleet: each trusted cluster account on its '
        'own declared login host, over ssh, detached, one log per account.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        _module('opsserver'),
        MAIN,
        "Running one of the ops account's fixed verbs on a declared server the integrator deploys: install, a "
        "unit's status, restart, reload or logs, or a daemon reload, with the user's one-time code at the login.",
        deny='REMOTE-WRITE-THROUGH-A-DOOR',
    ),
    Door(
        _module('hpcaccount', 'deploy'),
        USER,
        "Making a cluster account's login host a forge serve host: run by the user on that account.",
        deny='HPC-THROUGH-THE-DOOR',
    ),
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
