"""``python -m dev_lab.dev.forge ci logs|artifact <ref>`` -- READ a CI run's job logs and artifacts, nothing else.

WHY A DOOR. A red hosted job shows an agent only its check annotation ("Process completed with exit code 1") and
the part its producer posted; the cause sits in the job log and in the run's uploaded verify logs, and both need
the forge credential. User ruling 2026-11-26: agents read CI logs READ-ONLY, through this generic door and the
credential the forge door already presents (:func:`~dev_lab.dev.forgeclient.client_for`) -- never by pulling a
token out of git's store by hand. No verb here re-runs, cancels or writes anything on the forge.

- ``<ref>`` is a commit (a sha or an ``origin`` branch, :func:`~dev_lab.dev.forgestatus.resolve_commit`),
  ``pr:<number>`` (the pull request's head) or ``run:<id>`` (one Actions run). A bare number is refused: it is
  either, so it is neither.
- ``logs`` lists every job of the ref's runs with its conclusion, then writes the FULL log of each selected job
  (``--job <name|glob>``, repeatable, or ``--failed``) to a file under the checkout's dated output directory and
  prints only its last ``--tail`` lines up to the failed step's first ``##[error]`` (``--until end``: the log's
  end; ``--grep`` first keeps the matching ones): an agent's context is bounded, the file is whole. No selection
  lists the jobs and the run's artifacts, and says how to select.
- ``artifact`` lists the runs' artifacts; ``--name <name|glob>`` downloads each selected one, unpacks it under the
  output directory and prints the bounded tail of every ``.log`` it holds -- the rendered CI uploads each part's
  verify log (``verify-log-<part>-<attempt>``), where the real test failure is.

Both forges answer the same Actions paths under their API root (GitHub; Gitea with its Actions run API); a forge
answering 404 there has no Actions runs to read, and the refusal says so.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import re
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final, cast

from lab_commons.log import emit

from dev_lab.dev.datedlog import UndeclaredOutput, dated_base, declared_output, output_dir
from dev_lab.dev.forge import NoCredential, Transport, UnreadableRemote, forge_from_remote, forge_transport
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgecredential import LOGIN_DOOR
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import resolve_commit
from dev_lab.dev.forgework import Client

__all__ = [
    'DEFAULT_TAIL',
    'ERROR_MARK',
    'FAILED_JOB',
    'KIND',
    'UNTIL',
    'Artifact',
    'Job',
    'Run',
    'artifacts_of',
    'excerpt',
    'jobs_of',
    'main',
    'runs_of',
    'select',
]

#: The conclusions of a job that FAILED (``--failed``): it ended without succeeding, skipped and neutral aside.
FAILED_JOB: Final = frozenset({'failure', 'cancelled', 'timed_out', 'startup_failure'})

#: How many lines of each log are printed unless ``--tail`` says otherwise; the whole log is in its file.
DEFAULT_TAIL: Final = 40

#: The leaf directory under the checkout's dated output tree every file this door writes lands in.
KIND: Final = 'ci'

#: How many items one page asks for; a forge serving fewer per page is paged on to its ``total_count``.
_PAGE: Final = 100

#: Where a printed excerpt ends (``--until``): ``error`` at the first line the runner marks a failed step with
#: (:data:`ERROR_MARK`; measured 2026-11-26, document-lab PR #60: the last 30 lines of a red job were all post-job
#: cleanup, the failure 50 lines above them), ``end`` at the log's last line. A log with no mark ends at its last.
UNTIL: Final = ('error', 'end')
ERROR_MARK: Final = '##[error]'

#: What a printed line drops: the runner's timestamp prefix and terminal color codes, kept whole in the file.
_STAMP: Final = re.compile(r'^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ')
_COLOR: Final = re.compile(r'\x1b\[[0-9;]*m')
_UNSAFE: Final = re.compile(r'[^A-Za-z0-9._@+-]+')
_REF: Final = re.compile(r'(?P<kind>pr|run):(?P<number>\d+)')


@dataclass(frozen=True)
class Run:
    """One Actions run: its id, its workflow's name and the commit it ran."""

    id: int
    workflow: str
    sha: str


@dataclass(frozen=True)
class Job:
    """One job of a run: ``conclusion`` is ``''`` while it has not concluded (``status`` says how far it is)."""

    id: int
    name: str
    status: str
    conclusion: str
    url: str
    run: Run


@dataclass(frozen=True)
class Artifact:
    """One artifact a run uploaded; an ``expired`` one can no longer be downloaded."""

    id: int
    name: str
    size: int
    expired: bool
    run: Run


def _paged(client: Client, path: str, key: str) -> list[dict[str, Any]]:
    """Every item under *key* of the paged listing at *path*, read to its ``total_count``."""
    items: list[dict[str, Any]] = []
    joiner = '&' if '?' in path else '?'
    page = 1
    while True:
        answer: dict[str, Any] = client.call('GET', f'{path}{joiner}{client.backend.page_param}={_PAGE}&page={page}')
        listed: list[Any] = (answer or {}).get(key) or []
        got = [cast('dict[str, Any]', item) for item in listed if isinstance(item, dict)]
        items += got
        total: int = (answer or {}).get('total_count') or 0
        if not got or len(items) >= total:
            return items
        page += 1


def _run_of(raw: Mapping[str, Any]) -> Run:
    return Run(int(raw['id']), str(raw.get('name') or raw.get('display_title') or ''), str(raw.get('head_sha') or ''))


def runs_of(client: Client, root: Path, ref: str) -> tuple[Run, ...]:
    """The Actions runs *ref* names: one ``run:<id>``, or every run of a commit (``pr:<n>`` is its head's).

    Raises:
        ValueError: *ref* is a bare number, or names no commit here.

    """
    found = _REF.fullmatch(ref)
    if found is not None and found['kind'] == 'run':
        return (_run_of(client.call('GET', f'{client.repo}/actions/runs/{found["number"]}')),)
    if found is not None:
        sha = client.pr_view(int(found['number'])).head_sha
    elif ref.isdigit():
        msg = f'{ref!r} is a bare number: say pr:{ref} for a pull request or run:{ref} for an Actions run'
        raise ValueError(msg)
    else:
        sha = resolve_commit(root, ref)
    listed = _paged(client, f'{client.repo}/actions/runs?head_sha={sha}', 'workflow_runs')
    # filtered here too: a forge that ignores the head_sha query answers every run
    return tuple(_run_of(raw) for raw in listed if raw.get('head_sha') == sha)


def jobs_of(client: Client, runs: Iterable[Run]) -> tuple[Job, ...]:
    """Every job of *runs* (each run's latest attempt), in the order the forge lists them."""
    return tuple(
        Job(
            int(raw['id']),
            str(raw.get('name') or ''),
            str(raw.get('status') or ''),
            str(raw.get('conclusion') or ''),
            str(raw.get('html_url') or ''),
            run,
        )
        for run in runs
        for raw in _paged(client, f'{client.repo}/actions/runs/{run.id}/jobs', 'jobs')
    )


def artifacts_of(client: Client, runs: Iterable[Run]) -> tuple[Artifact, ...]:
    """Every artifact *runs* uploaded."""
    return tuple(
        Artifact(
            int(raw['id']),
            str(raw.get('name') or ''),
            int(raw.get('size_in_bytes') or 0),
            bool(raw.get('expired')),
            run,
        )
        for run in runs
        for raw in _paged(client, f'{client.repo}/actions/runs/{run.id}/artifacts', 'artifacts')
    )


def select[T: (Job, Artifact)](items: Sequence[T], patterns: Sequence[str], *, what: str) -> tuple[T, ...]:
    """The *items* whose name matches one of *patterns* (exact or glob).

    Raises:
        ValueError: a pattern matches nothing, naming every *what* there is.

    """
    if missed := [p for p in patterns if not any(fnmatch.fnmatchcase(item.name, p) for item in items)]:
        names = ', '.join(sorted({item.name for item in items})) or 'none'
        msg = f'no {what} matches {", ".join(missed)}; the {what}s here: {names}'
        raise ValueError(msg)
    return tuple(item for item in items if any(fnmatch.fnmatchcase(item.name, p) for p in patterns))


def excerpt(text: str, *, tail: int, grep: re.Pattern[str] | None, until: str) -> tuple[list[str], str]:
    """``(the last *tail* lines of *text* up to *until* (:data:`UNTIL`), a line saying what they are)``.

    With *grep* only its matching lines count. Each line drops the runner's timestamp and color codes.
    """
    lines = [_COLOR.sub('', _STAMP.sub('', line)) for line in text.splitlines()]
    marks = [n for n, line in enumerate(lines) if until == 'error' and line.startswith(ERROR_MARK)]
    kept = lines[: marks[0] + 1] if marks else lines
    if grep is not None:
        kept = [line for line in kept if grep.search(line)]
    shown = kept[-tail:] if tail else []
    upto = f'up to its first {ERROR_MARK} (line {marks[0] + 1})' if marks else 'up to its last line'
    matching = f' matching {grep.pattern!r}' if grep is not None else ''
    return shown, f'{len(lines)} lines; the last {len(shown)}{matching} {upto}'


def _safe(name: str) -> str:
    """*name* as one filename segment (a job name carries ``/`` and spaces)."""
    return _UNSAFE.sub('_', name).strip('_') or 'unnamed'


def _out_dir(root: Path, given: str) -> Path:
    """Where this run's files go: *given* when it is inside the checkout's output directory, else today's ``ci``.

    Raises:
        ValueError: *given* is outside the checkout's output directory, or the checkout declares none.

    """
    try:
        if not given:
            return output_dir(root, KIND)
        base = dated_base(root, declared_output(root)).resolve()
    except UndeclaredOutput as undeclared:
        raise ValueError(str(undeclared)) from undeclared
    out = (root / given).resolve()
    if not out.is_relative_to(base):
        msg = f"--out {given} is outside this checkout's output directory {base}: name a directory under it"
        raise ValueError(msg)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _shown(text: str, label: str, path: Path, args: argparse.Namespace) -> list[str]:
    """The header naming *path* and the bounded excerpt of *text* printed under it."""
    lines, said = excerpt(text, tail=args.tail, grep=args.grep, until=args.until)
    return [f'--- {label}: {path} ({said})', *lines]


def _listing(jobs: Sequence[Job]) -> list[str]:
    return [
        f'  {job.conclusion or job.status:<10} {job.name}  (run {job.run.id} {job.run.workflow})  {job.url}'.rstrip()
        for job in jobs
    ]


def _logs(client: Client, root: Path, ref: str, runs: Sequence[Run], args: argparse.Namespace) -> int:
    jobs = jobs_of(client, runs)
    lines = [f'[ci] {ref}: {len(jobs)} job(s) in {len(runs)} run(s)', *_listing(jobs)]
    if not args.job and not args.failed:
        held = artifacts_of(client, runs)
        named = ', '.join(f'{a.name} ({a.size // 1024} KiB)' for a in held if not a.expired)
        hint = f'--failed, or --job <name|glob> (repeatable); an artifact: forge ci artifact {ref} --name <name|glob>'
        emit('\n'.join([*lines, f'[ci] artifacts: {named or "none"}', f'[ci] select: {hint}']))
        return 0
    chosen = select(jobs, args.job, what='job') if args.job else ()
    chosen += tuple(job for job in jobs if args.failed and job.conclusion in FAILED_JOB and job not in chosen)
    if not chosen:
        emit('\n'.join([*lines, '[ci] no job concluded failed']))
        return 0
    out, code = _out_dir(root, args.out), 0
    for job in chosen:
        if not job.conclusion:  # measured 2026-11-26: a running job's log redirects to a blob not yet written
            lines.append(f'--- {job.name} ({job.status}): its log is published once it concludes; read it again then')
            continue
        try:
            text = client.download(f'{client.repo}/actions/jobs/{job.id}/logs').decode('utf-8', 'replace')
        except ForgeCallFailed as failed:
            lines.append(f'--- {job.name}: its log could not be read (HTTP {_status(failed)})')
            code = 1
            continue
        path = out / f'{job.run.sha[:12]}-{_safe(job.name)}-{job.id}.log'
        path.write_text(text, encoding='utf-8')
        lines += _shown(text, f'{job.name} ({job.conclusion or job.status})', path, args)
    emit('\n'.join(lines))
    return code


def _artifacts(client: Client, root: Path, ref: str, runs: Sequence[Run], args: argparse.Namespace) -> int:
    held = artifacts_of(client, runs)
    lines = [f'[ci] {ref}: {len(held)} artifact(s) in {len(runs)} run(s)'] + [
        f'  {"expired" if a.expired else f"{a.size // 1024} KiB":<10} {a.name}  (run {a.run.id} {a.run.workflow})'
        for a in held
    ]
    if not args.name:
        emit('\n'.join([*lines, '[ci] select: --name <name|glob> (repeatable)']))
        return 0
    out, code = _out_dir(root, args.out), 0
    for artifact in select(held, args.name, what='artifact'):
        if artifact.expired:
            lines.append(f'--- {artifact.name}: expired, the forge no longer holds it')
            code = 1
            continue
        try:
            packed = client.download(f'{client.repo}/actions/artifacts/{artifact.id}/zip')
        except ForgeCallFailed as failed:
            lines.append(f'--- {artifact.name}: it could not be downloaded (HTTP {_status(failed)})')
            code = 1
            continue
        where = out / f'{artifact.run.sha[:12]}-{_safe(artifact.name)}-{artifact.id}'
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            archive.extractall(where)  # zipfile drops absolute and `..` member paths: nothing lands outside
        files = sorted(path for path in where.rglob('*') if path.is_file())
        logs = [path for path in files if path.suffix == '.log']
        for path in logs:
            lines += _shown(path.read_text(encoding='utf-8', errors='replace'), artifact.name, path, args)
        lines.append(f'--- {artifact.name}: {len(files)} file(s) under {where}, {len(logs)} log(s) shown')
    emit('\n'.join(lines))
    return code


def _pattern(text: str) -> re.Pattern[str]:
    """``--grep``'s regex; a malformed one is argparse's usage error, naming what re said."""
    try:
        return re.compile(text)
    except re.error as bad:
        msg = f'{text!r} is no regex: {bad}'
        raise argparse.ArgumentTypeError(msg) from bad


def _count(text: str) -> int:
    """``--tail``'s count of lines, 0 or more."""
    if not text.isdigit():
        msg = f'{text!r} is no count of lines (0 or more)'
        raise argparse.ArgumentTypeError(msg)
    return int(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge ci', description="read a CI run's job logs and artifacts")
    verbs = parser.add_subparsers(dest='verb', required=True)
    logs = verbs.add_parser('logs', help="list a ref's jobs; print the bounded log of the selected ones")
    logs.add_argument('--job', action='append', default=[], help='a job name or glob (repeatable)')
    logs.add_argument('--failed', action='store_true', help='every job that concluded failed, cancelled or timed out')
    artifact = verbs.add_parser('artifact', help="list a ref's artifacts; unpack the selected ones and print logs")
    artifact.add_argument('--name', action='append', default=[], help='an artifact name or glob (repeatable)')
    for verb in (logs, artifact):
        verb.add_argument('ref', help='a commit (sha or origin branch), pr:<number> or run:<id>')
        verb.add_argument('--tail', type=_count, default=DEFAULT_TAIL, help='lines printed per log; the file is whole')
        verb.add_argument('--grep', type=_pattern, help='print only the lines matching this regex (then --tail)')
        verb.add_argument(
            '--until', choices=UNTIL, default='error',
            help=f'end the excerpt at the first {ERROR_MARK} line (a failed step), or at the end of the log',
        )  # fmt: skip
        verb.add_argument('--out', default='', help="a directory under the checkout's output dir (default: today's ci)")
    return parser


def _status(failed: ForgeCallFailed) -> int:
    """The HTTP status *failed* ended on; a download's message is never printed (a redirect's URL is signed)."""
    return failed.report.attempts[-1].returncode if failed.report.attempts else 0


def _refusal(failed: ForgeCallFailed, host: str) -> str:
    """What a failed API read says, with the door its status names: a credential's scope, or no Actions API."""
    status = _status(failed)
    if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        return (f'{failed} -- reading CI logs needs a token that may read Actions (GitHub: the Actions read '
                f'permission, or classic repo scope); store one: {LOGIN_DOOR.format(host=host)}')  # fmt: skip
    if status == HTTPStatus.NOT_FOUND:
        return f'{failed} -- {host} answered 404: no such run, pull request or job, or this forge has no Actions API'
    return str(failed)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
) -> int:
    """``forge ci logs|artifact <ref> ...`` (module docs): 0 shown, 1 a read failed, 2 refused naming its door."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return _read(args, Path.cwd() if cwd is None else cwd, env, transport)
    except ValueError as refused:
        emit(f'[forge] ci: {refused}', err=True)
        return 2


def _read(args: argparse.Namespace, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    """The verb *args* names, read through *root*'s forge client; a failed read is 1, naming its door.

    Raises:
        ValueError: refused -- no forge, no credential, a ref naming no run, a selection matching nothing.

    """
    try:
        host = forge_from_remote(root).host
    except UnreadableRemote as unreadable:
        raise ValueError(str(unreadable)) from unreadable
    try:
        client = client_for(root, env=env, transport=transport)
    except NoCredential as none:
        msg = f"no forge credential is stored for this checkout's forge; store one: {LOGIN_DOOR.format(host=host)}"
        raise ValueError(msg) from none
    verb: Callable[[Client, Path, str, Sequence[Run], argparse.Namespace], int] = (
        _logs if args.verb == 'logs' else _artifacts
    )
    try:
        runs = runs_of(client, root, args.ref)
        if not runs:
            msg = f'{args.ref} has no Actions run on {host}: its parts come from a forge serve host (forge status show)'
            raise ValueError(msg)
        return verb(client, root, args.ref, runs, args)
    except ForgeCallFailed as failed:
        emit(f'[forge] ci: {_refusal(failed, host)}', err=True)
        return 1
