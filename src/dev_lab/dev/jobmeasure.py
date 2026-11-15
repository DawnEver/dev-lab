"""A pinned Actions MEASUREMENT through verify, never a producer of a full part.

Dispatch inputs are JSON data passed through the environment, not shell source. Existing
verify logs own tree/environment/selector evidence; the receipt only indexes that evidence.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import lab_commons.launch as _door
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.forgerequestpaths import NOT_A_PATH, blobs, path_refusal, test_roots
from dev_lab.dev.forgestatus import head_sha
from dev_lab.dev.logref import Citation, UnverifiableLog, verify_log
from dev_lab.dev.producer import OUTCOME_VAR, PRODUCING_VAR
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.verify import EXIT_CODES, run_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.inflight import RunKey

__all__ = ['MeasurementRefused', 'main', 'run', 'validate']


class MeasurementRefused(ValueError):
    """The requested measurement cannot describe this checkout or selection."""


def _refuse(reason: str) -> NoReturn:
    msg = f'measurement refused: {reason}'
    raise MeasurementRefused(msg)


def _selectors(raw: str) -> tuple[str, ...]:
    """Parse argv data; only a file prefix, not a parameterized node ID, is a filesystem path."""
    try:
        selectors = json.loads(raw)
    except json.JSONDecodeError as why:
        _refuse(f'measurement_paths must be a JSON array: {why.msg}')
    if not isinstance(selectors, list) or not selectors or not all(isinstance(s, str) and s for s in selectors):
        _refuse('measurement_paths must be a nonempty JSON array of test selectors')
    for selector in selectors:
        if any(c in selector for c in '\x00\r\n'):
            _refuse('a selector contains a control character')
        parts = selector.split('::')
        if not all(parts):
            _refuse('a selector has an empty file or node name')
        path = parts[0]
        if NOT_A_PATH & set(path):
            _refuse(f'{path!r} is not one repository-relative test file')
    return tuple(selectors)


def validate(root: Path, sha: str, raw: str, env: Mapping[str, str]) -> tuple[str, ...]:
    """Freeze actual file/node selectors after proving their commit and checked-out bytes."""
    if env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        _refuse('only an explicit workflow_dispatch may request a measurement')
    if env.get('MEASUREMENT_PR') or env.get('MEASUREMENT_SMOKE', '') not in ('', 'false'):
        _refuse('measurement cannot be combined with a PR or smoke/full-part run')
    if not re.fullmatch('[0-9a-f]{40}', sha) or sha != env.get('GITHUB_SHA') or sha != head_sha(root):
        _refuse('measurement_sha, Actions GITHUB_SHA and checked-out HEAD must be the same full SHA')
    selectors = _selectors(raw)
    paths = [s.split('::', 1)[0] for s in selectors]
    roots = test_roots((root / 'pyproject.toml').read_text(encoding='utf-8'))
    files = blobs(root, sha, paths)
    for path in paths:
        if why := path_refusal(path, roots, files, sha):
            _refuse(why)
        target = root / path
        if not target.resolve().is_relative_to(root.resolve()):
            _refuse(f'{path!r} resolves outside the repository')
        if target.read_bytes() != files[path]:
            _refuse(f'{path!r} checkout bytes differ from the requested commit')
    if status_paths(root) != ():
        _refuse('the requested commit has uncommitted or unreadable checkout state')
    return tuple(selectors)


def _matching(logs: set[Path], key: RunKey) -> Citation:
    """Nested verify controls can write other logs; only this exact identity is evidence."""
    matches = []
    for path in logs:
        try:
            cited = verify_log(path)
        except UnverifiableLog:
            continue  # Not this run's evidence; absence of a matching proof below is still INCONCLUSIVE.
        if (cited.tree, cited.env, cited.spec) == (key.tree, key.env, key.selector):
            matches.append(cited)
    if len(matches) != 1:
        _refuse('the child produced no unique verifiable log for the requested identity; inspect stdout.log')
    return matches[0]


def run(root: Path, sha: str, raw: str, env: Mapping[str, str]) -> int:
    """Run the canonical measure argv, retaining raw output and an evidence-only receipt."""
    artifact = output_dir(root, 'measurement') / uuid.uuid4().hex
    artifact.mkdir()
    if output := env.get('GITHUB_OUTPUT'):
        with Path(output).open('a', encoding='utf-8') as handle:
            handle.write(f'artifacts={artifact.as_posix()}\n')
    receipt: dict[str, Any] = {'kind': 'MEASUREMENT', 'result': Conclusion.INCONCLUSIVE.value, 'exit_code': None}
    receipt_path = artifact / 'receipt.json'

    def save() -> None:
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')

    save()  # A stopped job already has an explicitly incomplete receipt, never a default PASS.
    try:
        selectors = validate(root, sha, raw, env)
        key = run_key(root, selectors)
        receipt['sha'] = sha
        receipt['selectors'] = list(selectors)
        save()
        directory = output_dir(root, 'verify')
        before = set(directory.glob('*.log'))
        child = {k: v for k, v in env.items() if k not in (PRODUCING_VAR, OUTCOME_VAR, 'GITHUB_TOKEN', 'GH_TOKEN')}
        with (artifact / 'stdout.log').open('w', encoding='utf-8') as handle:
            done = _door.run([sys.executable, '-m', 'dev_lab.dev.verify', '--', *selectors],
                             cwd=root, env=child, stdout=handle, stderr=subprocess.STDOUT, check=False)  # fmt: skip
        receipt['exit_code'] = done.returncode
        validate(root, sha, raw, env)  # A ref or source change during the child invalidates the receipt too.
        logs = set(directory.glob('*.log')) - before
        cited = _matching(logs, key)
        expected = next((outcome.value for outcome, code in EXIT_CODES.items() if code == done.returncode), None)
        if cited.result != expected:
            _refuse('the child exit and its verifiable log disagree')
        shutil.copyfile(cited.log.path, artifact / 'verify.log')
        receipt.update(result=cited.result, tree=cited.tree, env=cited.env, selector=cited.spec)
    except (ValueError, OSError, UnverifiableLog) as why:
        receipt['reason'] = str(why)
        emit(f'measurement: INCONCLUSIVE -- {why}', err=True)
        return 3
    else:
        return done.returncode
    finally:
        save()


def main() -> int:
    """Read the fixed dispatch environment; never interpolate selector data into a command."""
    return run(Path.cwd(), os.environ.get('MEASUREMENT_SHA', ''), os.environ.get('MEASUREMENT_PATHS', ''), os.environ)


if __name__ == '__main__':
    raise SystemExit(main())
