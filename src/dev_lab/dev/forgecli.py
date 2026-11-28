"""``python -m dev_lab.dev.forge <noun> <verb>`` -- the one noun dispatch over the ``forge*`` doors.

``status`` for commit statuses, ``issue claim|status|comments|comments-since|comment-view|view --comments``
for derived issue state and comment reads, ``auth`` for the token, ``protect plan|check|apply`` for the declared
branch protection,
``publish`` for the status outbox, ``records`` for
run records, ``run show <sha>`` for what a cluster run published (each round's losses, the final
failing ids), ``tick`` for requests and claims, ``queue`` for the read-only status view, ``route <record>``
for failure routing and ``serve`` for the whole harness sequence, ``sync`` / ``integration``
for the branch flow, ``tidy`` for declared issue hygiene, ``hosts retire HOST`` to drop a host card,
``request <producer> --sha <sha>`` to publish a request,
``pr close-landed [N...]`` to close landed PRs, ``pr close-superseded N... --by <M|sha>``
to close salvaged ones (neither deletes a branch),
``cancel-stuck <sha>`` for the forge's own stuck tasks, ``watch <sha>`` to follow a verdict read-only,
``ci logs|artifact <sha|pr:N|run:ID>`` to read a CI run's job logs and artifacts (read-only),
``notices`` for a session's PR notices, ``review again <pr>`` to have a PR reviewed again,
``review takeover|plan <sha>`` for a session's advisory review, ``security release <pr> --why`` for a head's new
security exemptions, ``headgate run --pr <N>`` for a PR head's gate statuses, ``secrets sync --task <task>`` for
a task's key bundle on every declared repo; anything else is the issue/PR door. The verbs
live in the sibling modules, which import :mod:`forge`, so :mod:`forge` reaches this module only from its
entry point.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

from dev_lab.dev import (
    _forgecli_args,
    branchnotices,
    forgeauth,
    forgebreakglass,
    forgeci,
    forgedraft,
    forgeheadgate,
    forgehold,
    forgehosts,
    forgeintegration,
    forgeissue,
    forgelabel,
    forgemergecall,
    forgemergeready,
    forgenotice,
    forgeoutbox,
    forgepr,
    forgeprotect,
    forgepublish,
    forgequeue,
    forgerecords,
    forgereview_bundle,
    forgeroute,
    forgerunshow,
    forgesecrets,
    forgesecurity,
    forgeserve,
    forgestatus,
    forgestuck,
    forgesync,
    forgetakeover,
    forgetask,
    forgetick,
    forgetidy,
    forgetry,
    forgewatch,
    issuekind,
    metrics,
    pradmit,
    prcontinue,
    prcurrent,
    prlanded,
    prsuperseded,
    pushwatch,
    servelock,
    standby,
    walls,
)
from dev_lab.dev.forge import Transport, forge_transport
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import BudgetSpent, ForgeCallFailed, within
from dev_lab.dev.forgefeedstatus import unheard_notice
from dev_lab.dev.forgelabels import LabelMissing, relabel
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgework import Client, Comment, Issue, PullRequest
from dev_lab.dev.labsession import ENV
from dev_lab.dev.native_session import session_of

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['ISSUE_VERBS', 'NOUNS', 'PR_VERBS', 'issue_and_pr', 'main']

NOUNS: dict[str, Callable[[list[str]], int]] = {
    'auth': forgeauth.main,
    'breakglass': forgebreakglass.wave_main,
    'ci': forgeci.main,
    'status': forgestatus.main,
    'protect': forgeprotect.main,
    'publish': forgeoutbox.main,
    'records': forgerecords.main,
    'run': forgerunshow.main,
    'route': forgeroute.main,
    'serve': lambda argv: servelock.locked(argv, forgeserve.main),
    'tick': forgetick.main,
    'queue': forgequeue.main,
    'sync': forgesync.main,
    'integration': forgeintegration.main,
    'merge': forgemergeready.main,
    'notices': forgenotice.main,
    'review': lambda argv: (forgereview_bundle.main if argv[:1] == ['judge'] else forgetakeover.main)(argv),
    'secrets': forgesecrets.main,
    'label': forgelabel.main,
    'headgate': forgeheadgate.main,
    'security': forgesecurity.main,
    'tidy': forgetidy.main,
    'hosts': forgehosts.main,
    'request': forgepublish.main,
    'cancel-stuck': forgestuck.main,
    'try': forgetry.main,
    'watch': forgewatch.main,
}

#: The ``pr`` verbs owned by a door module of their own; every other ``pr`` verb is the issue/PR door's.
PR_VERBS: dict[str, Callable[[list[str]], int]] = {
    'breakglass': forgebreakglass.merge_main,
    'close-landed': prlanded.main,
    'close-superseded': prsuperseded.main,
    'continue': prcontinue.main,
    'ready': lambda argv: forgedraft.main(['ready', *argv], judge=prcurrent.ready_refusals),
    'draft': lambda argv: forgedraft.main(['draft', *argv], judge=prcurrent.ready_refusals),
    'hold': lambda argv: forgehold.main(['hold', *argv]),
    'release': lambda argv: forgehold.main(['release', *argv]),
}

#: The ``issue`` verbs :mod:`forgeissue` owns; every other ``issue`` verb is the issue/PR door's.
ISSUE_VERBS = frozenset({'claim', 'status', 'comments', 'comments-since', 'comment-view'})


def main(argv: Sequence[str]) -> int:
    """Route *argv* to the door owning its noun; returns that door's exit code, a hand verb's success logged."""
    code = _route(list(argv))
    if code == 0:
        metrics.hand_action(Path.cwd(), argv)
    return code


def _route(args: list[str]) -> int:
    if args[:1] and (retired := refusal('forge', args[0])):
        emit(retired, err=True)
        return 2
    if args[:1] and args[0] in NOUNS:
        if refused := next(filter(None, (refusal(f'forge {args[0]}', w.split('=', 1)[0]) for w in args[1:])), None):
            emit(refused, err=True)
            return 2
        return NOUNS[args[0]](args[1:])
    if args[:1] == ['pr'] and args[1:2] and args[1] in PR_VERBS:
        return PR_VERBS[args[1]](args[2:])
    if args[:1] == ['issue'] and ((args[1:2] and args[1] in ISSUE_VERBS) or _threaded(args)):
        return forgeissue.main(args[1:])
    return issue_and_pr(args)


def _threaded(args: Sequence[str]) -> bool:
    """``issue view N --comments``: the issue WITH its thread is :mod:`forgeissue`'s; the bare view stays here."""
    return args[1:2] == ['view'] and '--comments' in args


def _dispatch(
    client: Client, args: argparse.Namespace, root: Path
) -> Issue | PullRequest | Comment | tuple[Issue | PullRequest, ...]:
    verbs: dict[tuple[str, str], Callable[[], Issue | PullRequest | Comment | tuple[Issue | PullRequest, ...]]] = {
        ('issue', 'list'): lambda: client.issue_list(state=args.state, limit=args.limit, labels=args.label),
        ('issue', 'view'): lambda: client.issue_view(args.number),
        ('issue', 'create'): lambda: issuekind.create(client, args.title, args.body, args.kind, args.label),
        ('issue', 'comment'): lambda: client.issue_comment(args.number, args.body),
        ('issue', 'close'): lambda: client.issue_close(args.number),
        ('issue', 'label'): lambda: _relabeled(client, args),
        ('pr', 'create'): lambda: client.pr_create(
            args.title, _declared_body(args), head=args.head, base=args.base, draft=not args.ready
        ),
        ('pr', 'list'): lambda: _pulls(client, args),
        ('pr', 'view'): lambda: client.pr_view(args.number),
        ('pr', 'close'): lambda: forgepr.pr_close(client, args.number, args.reason),
        ('pr', 'retarget'): lambda: forgepr.pr_retarget(
            client, args.number, args.base, allowed=forgepr.declared_bases(root), reason=args.reason
        ),
        ('pr', 'edit'): lambda: forgepr.pr_edit(
            client, args.number, body=forgepr.edit_text(args) if args.body_file else None, append=args.append_line
        ),
    }
    return verbs[args.noun, args.verb]()


def _pulls(client: Client, args: argparse.Namespace) -> tuple[PullRequest, ...]:
    """The first *args.limit* pulls in *args.state* (every page read), only those from *args.head* when it is named."""
    listed = pr_list(client, state=args.state)
    return tuple(pull for pull in listed if args.head in {None, pull.head})[: args.limit]


def _relabeled(client: Client, args: argparse.Namespace) -> Issue:
    """Relabel issue *args.number* (:func:`~dev_lab.dev.forgelabels.relabel`) and show it as it now stands."""
    relabel(client, args.number, add=args.add, remove=args.remove)
    return client.issue_view(args.number)


def _labels(args: argparse.Namespace) -> Sequence[str]:
    """The labels an issue verb names: ``label --add`` and ``list``/``create --label``; the other verbs name none."""
    if args.verb == 'label':
        return args.add
    return args.label if args.verb in {'list', 'create'} else ()


def _show(
    args: argparse.Namespace, result: Issue | PullRequest | Comment | tuple[Issue | PullRequest, ...], root: Path
) -> None:
    """Print *result* (JSON with ``--json``); an issue verb that subscribed a task nobody hears says so."""
    items = result if isinstance(result, tuple) else (result,)
    if args.json:
        data = [dataclasses.asdict(item) for item in items]
        emit(json.dumps(data if isinstance(result, tuple) else data[0], indent=2))
    else:
        for item in items:
            emit(_render(item))
    if args.noun == 'issue' and (said := unheard_notice(root, _labels(args))):
        emit(f'[forge] {said}', err=True)  # TASK-HEARS-ITS-FORGE-EVENTS: a subscription nobody hears is said


def _record_standby(args: argparse.Namespace, result: object, root: Path, env: Mapping[str, str] | None) -> None:
    """A standby comment this session posted is recorded for the stop hook (STANDBY-IS-RESTING)."""
    if isinstance(result, Comment) and standby.posted(args.body) and (who := session_of(env)):
        walls.standby(root, issue=result.url, session=who)


def _declared_body(args: argparse.Namespace) -> str:
    """*args*' PR body, with :data:`~dev_lab.dev.forgedraft.READY_WHEN` as its last line when the author declared it."""
    if not args.ready_when_current:
        return args.body
    return '\n\n'.join([*([args.body] if args.body else []), forgedraft.READY_WHEN])


def _render(item: Issue | PullRequest | Comment) -> str:
    if isinstance(item, Comment):
        return item.url
    if isinstance(item, PullRequest):
        return f'#{item.number} [{item.state}] {item.head} -> {item.base}  {item.title}  {item.url}'
    return f'#{item.number} [{item.state}] {item.title}  {item.url}'


#: The whole time an issue verb (or ``pr view``) may wait on the forge: one full 30 s attempt and a cut second.
#: v1 #2: reads hung 90-120 s without a word -- three 30 s socket timeouts and two backoffs, the retry loop's whole
#: bound, while the forge did not answer. Past the budget the verb ends, naming what each attempt measured.
READ_BUDGET_S: Final = 45.0


def _budgeted(noun: str, verb: str) -> bool:
    return noun == 'issue' or (noun, verb) in {('pr', 'view'), ('pr', 'list')}


def issue_and_pr(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    budget_s: float = READ_BUDGET_S,
) -> int:
    """``python -m dev_lab.dev.forge issue|pr <verb> ...`` (:mod:`forgework`); exit 1 with netverb's remedy.

    An issue verb, ``pr view`` and ``pr list`` end within *budget_s* (:data:`READ_BUDGET_S`), naming the cause.
    """
    parser = _forgecli_args.parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    if _budgeted(args.noun, args.verb):
        transport = within(transport, time.monotonic() + budget_s, f'forge {args.noun} {args.verb}', budget_s)
    if (refused := _forgecli_args.refused(parser, args, root, env, transport)) is not None:
        emit(refused, err=True)
        walls.refused_text(root, refused, reason=f'forge {args.noun} {args.verb}')
        return 1
    client = client_for(root, env=env, transport=transport)
    try:
        if (args.noun, args.verb) == ('pr', 'create') and (
            said := forgetask.head_advice(args.head, root)
            + pradmit.create_advice(root, client, head=args.head, base=args.base)
        ):
            lines = [f'{pradmit.ADMISSION}: {line}' for line in said]
            emit('\n'.join(f'[forge] {line}' for line in lines), err=True)
            args.body = '\n\n'.join([*([args.body] if args.body else []), '\n'.join(lines)])
        result = _dispatch(client, args, root)
        if (args.noun, args.verb) == ('pr', 'create') and isinstance(result, PullRequest):
            emit(f'[forge] {forgemergecall.auto_merge(client, result.number)}', err=True)
            if head := result.head_sha or pushwatch.pushed_sha(root, f'refs/remotes/origin/{result.head}'):
                emit(f'[forge] {pushwatch.heard_line(head)}', err=True)  # PUSHED-HEAD-IS-WATCHED
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except (BudgetSpent, LabelMissing) as stopped:
        emit(f'[forge] {stopped}', err=True)
        return 1
    forgetask.record(args, result, root)
    _record_standby(args, result, root, env)
    _show(args, result, root)
    if (args.noun, args.verb) == ('pr', 'create') and isinstance(result, PullRequest):
        emit(forgedraft.opened_line(result))  # the exact next step for a draft, on stdout (D53)
    if (args.noun, args.verb) == ('pr', 'create') and (
        said := branchnotices.report(
            root, [args.head], (os.environ if env is None else env).get(ENV, ''), client=client
        )
    ):
        emit(said, err=True)
    return 0
