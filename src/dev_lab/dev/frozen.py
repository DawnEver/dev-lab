"""USER-FROZEN-FILES: a file or directory the user finalized keeps its content.

User rulings 2026-11-24: once the user finalizes a file it is FROZEN -- no modification. Freeze judges frozen CONTENT
only: which paths may exist at all is the layout allowlist's (``[tool.dev_lab.placement.layout]``), and memory's
append-only rule is :mod:`dev_lab.dev.memoryadds`'s -- neither is restated here. A repo opts in with
``[tool.dev_lab.freeze] repo = "<name>"`` in its ``pyproject.toml``; the facts are DATA in ONE file the table makes
mandatory, :data:`FREEZE_FILE` at the root, mapping a file to its git BLOB id and a directory to its git TREE id::

    [frozen]
    ".vscode/settings.json" = "<blob id>"
    "docs-src/guide" = "<tree id>"
    "freeze.toml" = "self"

THE APPROVAL IS THE USER'S CONSENT CODE, not who typed the file. The agent may draft :data:`FREEZE_FILE`; it takes
effect only beside :data:`RECEIPT_FILE`, a credential the consent issuer (:mod:`dev_lab.ops.consent`) signed for the
action :data:`ACTION` whose subject is ``<repo> <sha256 of freeze.toml>`` (:func:`subject`). Only the user's TOTP code
makes the issuer sign, and every check verifies the signature offline against the declared issuer key
(:func:`dev_lab.ops.consent.client.public_key`), so an agent cannot approve itself. The freeze file freezes itself as
:data:`SELF`: no file can hold its own hash, and the receipt is what pins its bytes. Three layers read this module
(no server-side protection):

1. the agent hooks: the ``codeplace`` Write/Edit hook calls :func:`refuse_write`, and the shell deny row
   :mod:`dev_lab.dev._deny_frozen_row` asks :func:`main` ``--admit`` on a write-verb line -- a frozen file is never
   written by an agent;
2. the pre-commit row ``frozen-files`` (``main commit``) judges the INDEX;
3. the always-on family check :func:`check` judges the same index -- a CI checkout's index IS the pushed commit -- so
   the PR's own test run reds.

The door for a change: ``python -m dev_lab.dev.frozen request`` writes the consent request for the drafted file and
names the grant; ``python -m dev_lab.dev.frozen receipt <credential.json>`` places the signed credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Final

from lab_commons.launch import run

from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

__all__ = [
    'ACTION',
    'FREEZE_FILE',
    'HAZARD',
    'RECEIPT_FILE',
    'REMEDY',
    'RULE_ID',
    'SELF',
    'Freeze',
    'check',
    'declared',
    'index_object',
    'judge',
    'main',
    'parse',
    'receipt_problems',
    'refuse_write',
    'shell_targets',
    'subject',
]

RULE_ID: Final = 'USER-FROZEN-FILES'
FREEZE_FILE: Final = 'freeze.toml'
RECEIPT_FILE: Final = 'freeze.receipt.json'
ACTION: Final = 'repo.freeze.change'
SELF: Final = 'self'
_TABLE: Final = 'freeze'
_OID: Final = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
HAZARD: Final = 'a file or directory the user finalized is frozen: its content changes only with their consent.'
REMEDY: Final = (
    f'Only the USER approves: edit {FREEZE_FILE} (`[frozen]` `"<path>" = "<object id>"`), run '
    '`{python} -m dev_lab.dev.frozen request`, ask the user for the code, run the grant it names, then '
    f'`{{python}} -m dev_lab.dev.frozen receipt <credential.json>`; commit {FREEZE_FILE} with {RECEIPT_FILE}.'
)


@dataclass(frozen=True, slots=True)
class Freeze:
    """The declaration: frozen path -> git object id (file: blob, directory: tree, itself: :data:`SELF`)."""

    frozen: Mapping[str, str]


def _python() -> str:
    from dev_lab.dev.venvpath import running_interpreter  # noqa: PLC0415 -- the remedy's interpreter, at refusal time

    return running_interpreter()


def _refusal(what: str) -> str:
    remedy = REMEDY.replace('{python}', _python())
    return f'{RULE_ID}: {what} -- {HAZARD} {remedy}\ndetails: docs-src/dev/refusals.md#user-frozen-files (dev-lab)'


def parse(text: str) -> Freeze:
    """*text* of :data:`FREEZE_FILE` as a :class:`Freeze`; a malformed one raises ValueError naming the fault."""
    data = tomllib.loads(text)
    if unknown := sorted(set(data) - {'frozen'}):
        msg = f'{FREEZE_FILE} holds only [frozen], not {unknown}'
        raise ValueError(msg)
    frozen = data.get('frozen')
    if not isinstance(frozen, dict) or not all(isinstance(v, str) for v in frozen.values()):
        msg = f'{FREEZE_FILE}: `[frozen]` must map repo-relative paths to git object ids, not {frozen!r}'
        raise ValueError(msg)
    if bad := sorted(p for p, oid in frozen.items() if p != FREEZE_FILE and not _OID.fullmatch(oid)):
        msg = f'{FREEZE_FILE}: [frozen] {bad} carry no lowercase git object id'
        raise ValueError(msg)
    if frozen.get(FREEZE_FILE) != SELF:
        msg = f'{FREEZE_FILE} must freeze itself: `"{FREEZE_FILE}" = "{SELF}"` under [frozen]'
        raise ValueError(msg)
    return Freeze(dict(frozen))


def judge(freeze: Freeze, object_id: Callable[[str], tuple[str, str] | None]) -> list[str]:
    """Every frozen path whose ``(kind, id)`` (*object_id*; ``None``: absent) moved."""
    problems: list[str] = []
    for path, oid in sorted(freeze.frozen.items()):
        if oid == SELF:
            continue
        found = object_id(path)
        if found is None:
            problems.append(f'{path} is frozen and was deleted')
        elif found[1] != oid:
            problems.append(f'{path} is frozen and its {found[0]} changed ({oid[:12]} -> {found[1][:12]})')
    return problems


def subject(repo: str, freeze_bytes: bytes) -> str:
    """The consent subject approving *freeze_bytes* in *repo*: ``<repo> <sha256>``.

    The digest is over LF line ends: a checkout's line-end conversion (``core.autocrlf``, ``.gitattributes``) changes
    the working bytes, never what the user approved, so the draft, the index and a CI checkout name one subject.
    """
    return f'{repo} {hashlib.sha256(freeze_bytes.replace(b"\r\n", b"\n")).hexdigest()}'


def _issuer_key() -> Ed25519PublicKey | None:
    """The declared issuer key (:func:`dev_lab.ops.consent.client.public_key`); ``None`` when none is declared."""
    from dev_lab.ops.consent.client import public_key  # noqa: PLC0415 -- only a judged repo pays for the client

    try:
        return public_key()
    except ValueError:
        return None


def receipt_problems(repo: str, freeze_bytes: bytes, receipt: bytes | None, key: Ed25519PublicKey | None) -> list[str]:
    """Why *receipt* does not approve *freeze_bytes* in *repo*: empty when the issuer signed exactly that."""
    from dev_lab.ops.consent.credential import ConsentRefused, verify  # noqa: PLC0415

    if receipt is None:
        return [f'{RECEIPT_FILE} is missing: no consent approves this {FREEZE_FILE}']
    if key is None:
        return ['no consent issuer key is declared ([consent] public_key), so no receipt can be verified']
    try:
        data: Any = json.loads(receipt.decode('utf-8'))
        # A receipt proves the user's word AT ISSUE: its lifetime bounds the grant, never the commit that carries it.
        issued = data.get('issued') if isinstance(data, dict) else None
        when = float(issued) if isinstance(issued, int | float) and not isinstance(issued, bool) else time.time()
        credential = verify(data, key, now=when)
    except ConsentRefused as exc:
        return [f'{RECEIPT_FILE} does not verify: {exc}']
    except (ValueError, UnicodeError) as exc:
        return [f'{RECEIPT_FILE} is not a credential JSON: {exc}']
    want = subject(repo, freeze_bytes)
    if credential.action != ACTION or credential.subject != want:
        got = f'{credential.action} {credential.subject!r}'
        return [f'{RECEIPT_FILE} approves {got}, not {ACTION} {want!r}: the user approved another {FREEZE_FILE}']
    return []


def _manifest(root: Path) -> dict[str, Any] | None:
    try:
        return tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return None
    except ValueError:
        return {}


def declared(root: Path) -> bool:
    """Whether *root*'s ``pyproject.toml`` opts in with ``[tool.dev_lab.freeze]``; a broken manifest opts in."""
    data = _manifest(root)
    return data is not None and (not data or declared_table(data, _TABLE) is not None)


def _repo(root: Path) -> str:
    table = declared_table(_manifest(root) or {}, _TABLE) or {}
    repo = table.get('repo')
    if not isinstance(repo, str) or not repo:
        msg = f'[tool.dev_lab.{_TABLE}] must name the repo (`repo = "<name>"`): it is half the consent subject'
        raise ValueError(msg)
    return repo


def _git(root: Path, *args: str) -> bytes:
    done = run(['git', *args], cwd=root, capture_output=True, check=False, timeout=60)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed in {root}: {done.stderr.decode("utf-8", "replace").strip()}'
        raise RuntimeError(msg)
    return done.stdout


def index_object(root: Path, path: str) -> tuple[str, str] | None:
    """*path*'s ``(kind, id)`` in *root*'s index: a file's blob, a directory's tree; ``None`` when it holds neither."""
    staged = _git(root, '-c', 'core.quotepath=off', 'ls-files', '-s', '-z', '--', path).decode('utf-8')
    for entry in filter(None, staged.split('\0')):
        meta, name = entry.split('\t', 1)
        if name == path:
            return 'blob', meta.split()[1]
    if not staged:
        return None
    tree = run(['git', 'write-tree', f'--prefix={path}/'], cwd=root, capture_output=True, check=False, timeout=60)
    return ('tree', tree.stdout.decode().strip()) if tree.returncode == 0 else None


def _staged(root: Path, path: str) -> bytes | None:
    return _git(root, 'show', f':{path}') if index_object(root, path) else None


def _problems(root: Path) -> list[str]:
    """The violations in *root*'s index: what a commit would carry, and what a CI checkout carries."""
    if not declared(root):
        return []
    text = _staged(root, FREEZE_FILE)
    if text is None:
        return [f'[tool.dev_lab.{_TABLE}] is declared but {FREEZE_FILE} is not tracked']
    try:
        repo = _repo(root)
        freeze = parse(text.decode('utf-8'))
    except ValueError as exc:
        return [str(exc)]
    receipt = _staged(root, RECEIPT_FILE)
    return receipt_problems(repo, text, receipt, _issuer_key()) + judge(freeze, lambda p: index_object(root, p))


def check(root: Path) -> None:
    """The always-on family check: raise naming every violation in *root*'s index."""
    if problems := _problems(root):
        raise AssertionError(_refusal('; '.join(problems)))


def _frozen_of(path: Path) -> tuple[Path, Freeze] | None:
    from dev_lab.dev.gitdirs import checkout_of  # noqa: PLC0415 -- only a hook pays for it

    root = checkout_of(path.parent)
    if root is None or not declared(root):
        return None
    try:
        return root, parse((root / FREEZE_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def refuse_write(path: Path) -> str | None:
    """The refusal for an agent writing *path* when its checkout freezes it; ``None`` otherwise.

    The freeze file itself is the agent's to DRAFT (user ruling 2026-11-24): its receipt, not its author, approves it.
    """
    target = Path(path).resolve()
    found = _frozen_of(target)
    if found is None:
        return None
    root, freeze = found
    rel = target.relative_to(root.resolve()).as_posix()
    for frozen_path, oid in freeze.frozen.items():
        if oid != SELF and (rel == frozen_path or rel.startswith(frozen_path.rstrip('/') + '/')):
            return _refusal(f'{rel} is frozen' if rel == frozen_path else f'{rel} is inside frozen {frozen_path}')
    return None


_SEGMENTS: Final = re.compile(r'&&|\|\||[;|\n]')
_REMOVERS: Final = frozenset({'mv', 'rm', 'touch', 'tee', 'truncate', 'Move-Item', 'Remove-Item', 'New-Item'})
_SETTERS: Final = frozenset({'Set-Content', 'Out-File', 'Add-Content', 'Clear-Content'})


def _operands(words: list[str]) -> list[str]:
    return [w for w in words if not w.startswith('-')]


def _redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """The redirect targets among *words*, and the words left once the redirect operators are taken out."""
    targets: list[str] = []
    rest: list[str] = []
    for i, word in enumerate(words):
        match = re.fullmatch(r'\d?>>?(.*)', word)
        if match is None:
            rest.append(word)
        elif match.group(1) and not match.group(1).startswith('&'):
            targets.append(match.group(1))
        elif not match.group(1) and i + 1 < len(words):
            targets.append(words[i + 1])
    return targets, rest


def _verb_targets(words: list[str]) -> list[str]:
    """The operands a write verb at the head of *words* writes, moves or removes."""
    verb, args = words[0].rsplit('/', 1)[-1], words[1:]
    if verb == 'git' and args[:1] in (['rm'], ['mv']):
        verb, args = args[0], args[1:]
    if verb in _REMOVERS or verb in _SETTERS:
        return _operands(args)
    if verb == 'sed' and any(re.fullmatch(r'-[a-zA-Z]*i\S*', a) for a in args):
        return _operands(args)[1:]
    if verb in {'cp', 'Copy-Item'}:
        return _operands(args)[-1:]
    return []


def shell_targets(command: str) -> list[str]:
    """The paths *command* writes, moves or removes: redirect targets and the write verbs' operands."""
    found: list[str] = []
    for segment in _SEGMENTS.split(command):
        try:
            words = [w.strip('"\'') for w in shlex.split(segment, posix=False)]
        except ValueError:
            continue
        targets, rest = _redirects(words)
        found.extend(targets)
        if rest:
            found.extend(_verb_targets(rest))
    return found


def _shell_refusal(payload: Mapping[str, object]) -> str | None:
    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict):
        return None
    cwd = Path(str(payload.get('cwd') or Path.cwd()))
    for token in shell_targets(str(tool_input.get('command', ''))):
        target = Path(token).expanduser()
        if reason := refuse_write(target if target.is_absolute() else cwd / target):
            return reason
    return None


def _request(root: Path, now: datetime) -> str:
    """Write the consent request approving *root*'s drafted freeze file; the line naming the grant."""
    text = (root / FREEZE_FILE).read_bytes()
    parse(text.decode('utf-8'))  # a malformed draft is refused before the user spends a code
    want = subject(_repo(root), text)
    where = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / 'consent'
    where.mkdir(parents=True, exist_ok=True)
    request = where / f'freeze-{want.rsplit(" ", 1)[1][:12]}.json'
    request.write_text(json.dumps({'action': ACTION, 'subject': want, 'params': {}}, indent=2) + '\n', encoding='utf-8')
    return (
        f'wrote {request.as_posix()} for {ACTION} {want!r}; ask the user for the cluster code, then run '
        f'`{_python()} -m dev_lab.ops.consent grant {request.as_posix()} --code <the code they gave>` and '
        f'`{_python()} -m dev_lab.dev.frozen receipt <the credential it wrote>`'
    )


def _receipt(root: Path, credential: Path) -> list[str]:
    """Place *credential* as *root*'s receipt once it approves the freeze file as it stands; the problems, else none."""
    data = credential.read_bytes()
    problems = receipt_problems(_repo(root), (root / FREEZE_FILE).read_bytes(), data, _issuer_key())
    if not problems:
        (root / RECEIPT_FILE).write_bytes(data)
    return problems


def main(argv: list[str] | None = None, *, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """``commit``: refuse the staged index. ``request``: write the consent request for the drafted freeze file.

    ``receipt <credential.json>``: place a granted credential as the receipt. ``--admit``: judge a shell hook payload
    on stdin. A refusal exits 1 with its reason on stdout.
    """
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.frozen', description=main.__doc__)
    parser.add_argument('mode', nargs='?', choices=('commit', 'request', 'receipt'))
    parser.add_argument('credential', nargs='?', type=Path)
    parser.add_argument('--admit', action='store_true')
    args = parser.parse_args(argv)
    out = stdout or sys.stdout.buffer
    reason: str | None = None
    if args.admit:
        try:
            payload = json.loads((stdin or sys.stdin.buffer).read().decode('utf-8'))
            reason = _shell_refusal(payload) if isinstance(payload, dict) else None
        except (ValueError, OSError, RuntimeError):
            return 0
    elif args.mode == 'commit':
        problems = _problems(Path.cwd())
        reason = _refusal('; '.join(problems)) if problems else None
    elif args.mode == 'request':
        out.write(_request(Path.cwd(), datetime.now(UTC)).encode('utf-8') + b'\n')
    elif args.mode == 'receipt' and args.credential is not None:
        problems = _receipt(Path.cwd(), args.credential)
        reason = _refusal('; '.join(problems)) if problems else None
    else:
        parser.error('name a mode: commit, request, receipt <credential.json>, or --admit')
    if reason is None:
        return 0
    out.write(reason.encode('utf-8') + b'\n')
    out.flush()
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
