"""``python -m dev_lab.dev.family check | join <name> <url>``: this machine's family (:mod:`.members`).

``check`` prints every finding and exits 1 on any (0 none, 2 refused); ``join`` runs the ordered steps and prints
what is left for the user. The review secret comes from the ONE stored bundle
(:func:`dev_lab.dev.forgesecrets.stored_bundle`) and is set on the joining repo only -- no user step.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from lab_commons.home import config_path, repos
from lab_commons.log import emit

from dev_lab.dev import forgeprotect
from dev_lab.dev.family.members import FamilyRefused, join
from dev_lab.dev.family.watch import findings
from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgesecrets import Target, set_secret, stored_bundle, withheld
from dev_lab.dev.forgework import client_for
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.taskkeys import REVIEW_TASK, secret_name

__all__ = ['main']


def _check() -> int:
    found = findings()
    for finding in found:
        emit(f'[family] {finding.member}: {finding.what}')
    emit(f'[family] {len(repos())} member(s); ' + (f'{len(found)} finding(s)' if found else 'every fact holds'))
    return 1 if found else 0


def _clone(url: str, where: Path) -> None:
    report = run_network_verb(['git', 'clone', url, str(where)], timeout=600)
    if report.returncode != 0:
        msg = f'git clone {url} {where} failed (exit {report.returncode})'
        raise OSError(msg)


def _protect(root: Path) -> list[str]:
    manifest = root / 'pyproject.toml'
    client = client_for(root)
    wanted = forgeprotect.targets(manifest.read_text(encoding='utf-8'), str(manifest), client.forge)
    return forgeprotect.render(forgeprotect.apply(client, client.forge, wanted))


def _secrets(name: str, bundle: str) -> Callable[[Path], str]:
    def put(root: Path) -> str:
        target = Target(name, root, forge_from_remote(root))
        if why := withheld(target):
            return why
        set_secret(target, secret_name(REVIEW_TASK), bundle)
        return f'set {secret_name(REVIEW_TASK)} (sha256 {hashlib.sha256(bundle.encode()).hexdigest()[:12]})'

    return put


def main(argv: Sequence[str] | None = None) -> int:
    """Route ``check`` / ``join``; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.family', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('check', help="every member's facts; exit 1 on any finding")
    joining = verbs.add_parser('join', help='the ordered steps that make a repo a member')
    joining.add_argument('name')
    joining.add_argument('url')
    args = parser.parse_args(argv)
    if args.verb == 'check':
        return _check()
    bundle = stored_bundle(REVIEW_TASK)  # the one stored copy (`forge secrets store`); none: a step left
    try:
        said = join(args.name, args.url, machine=config_path(), clone=_clone, protect=_protect,
                    secrets=_secrets(args.name, bundle) if bundle else None)  # fmt: skip
    except (FamilyRefused, OSError, ValueError) as refused:
        emit(f'[family] refused: {refused}', err=True)
        return 2
    for line in said:
        emit(f'[family] {line}')
    return 1 if any(line.startswith('left:') for line in said) else 0


if __name__ == '__main__':
    sys.exit(main())
