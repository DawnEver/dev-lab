"""Check a config-source repository OFF its hosts: the CI of the repository ``[ops.config] source`` names.

Five checks, each generic (the repository's own facts arrive as the files it holds):

- a HOST file is a server's (``[ops]``), a development machine's (``[dev]``, :mod:`dev_lab.dev.devhost`,
  checked with the family file: a restated family key is refused; the machine tables it renders are open, but
  ``[ssh]`` is checked against :data:`~dev_lab.dev.devschema.SSH`) or an HPC account's (``[deploy]``, neither of
  the others: :mod:`dev_lab.dev.accounthost`, checked with the family file that holds its grant); a
  server's file loads by structure
  (:func:`dev_lab.ops.config.load` with ``structure_only``): the shape the live door will load, without the host's
  environment or secret files, which exist only on the host; and it holds no key the schema
  does not declare -- ``[ops]`` as the loader declares it, every other table as the supervisor's
  :data:`~dev_lab.supervise.config.DEFAULTS` does (a table whose default is empty, ``components``, is open); and
  a host that is no HPC account carries no ``[serve]`` (:func:`dev_lab.dev.rolecheck.host_refusals`);
- the FAMILY file shares no machine-local table (:data:`LOCAL_ONLY`) and no secret VALUE -- a secret is named by
  path (``*_file``, ``*_path``), never held; a refusal names the key, never repeats the value;
- the family's ROLES BINDING holds against the host files (:func:`check_roles`): every role bound to a host names a
  host file carrying the role's ``[ops.<duty>]`` (:func:`dev_lab.dev.roles.host_refusals`), and every repo a judge's
  ``[ops.judge] repos`` or a promoter's ``[ops] repos`` lists is bound to THAT host for that role -- the host's list
  and the binding are one fact, the binding its source;
- no development machine's host file declares a route (ssh jump, host key, endpoint) to another one
  (:func:`check_routes`, MACHINES-MEET-ONLY-THROUGH-THE-FORGE): they meet only through the forge;
- a change NEEDS CONSENT when it touches a boundary key (:func:`dev_lab.ops.configdoor.boundary`): merging it
  grants nothing, applying it still needs the user's ``ops.config`` consent, so the PR is labelled :data:`LABEL`.

Merging such a repository is not the security gate; ``config apply`` is.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from lab_commons.log import emit

from dev_lab.dev import accounthost, devschema, rolecheck, roles, writeroots
from dev_lab.dev.machineroutes import route_defects
from dev_lab.ops import clientkeys
from dev_lab.ops import config as opsconfig
from dev_lab.ops.configdoor import boundary, changes
from dev_lab.supervise.config import DEFAULTS

__all__ = ['LABEL', 'LOCAL_ONLY', 'check_family', 'check_host', 'check_roles', 'check_routes', 'main', 'needs_consent']

#: Tables a machine holds for itself; the family layer never carries them.
LOCAL_ONLY: Final = ('repos', 'writeroots', 'sync')
#: The label a PR gets when its change needs consent at apply time.
LABEL: Final = 'needs-consent'

_SECRET_NAME = re.compile(r'(?:token|secret|password|passwd|api_?key|private_?key)$', re.IGNORECASE)
_PATH_NAME = re.compile(r'_(?:file|path|dir)$')
_SECRET_SHAPE = re.compile(
    r'^(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{30,}|xox[abpr]-[\w-]{10,}|[0-9a-f]{40})$'
)


def _undeclared(table: Mapping[str, Any], schema: Mapping[str, Any], prefix: str = '') -> Iterator[str]:
    """The dotted keys of *table* that *schema* does not declare; an empty schema table is open."""
    for key, value in table.items():
        if key not in schema:
            yield f'{prefix}{key}'
        elif schema[key] and isinstance(schema[key], Mapping) and isinstance(value, Mapping):
            yield from _undeclared(value, schema[key], f'{prefix}{key}.')


def check_host(path: Path, family: Path | None = None) -> list[str]:
    """Defects of a host file as the live door would load it, judged by structure alone, plus undeclared keys."""
    try:
        parsed = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as bad:
        return [f'{path.name}: {bad}']
    shared = tomllib.loads(family.read_text(encoding='utf-8')) if family is not None else {}
    table = parsed.get('writeroots', {})
    allow = [f'{path.name}: {line}' for line in writeroots.allow_defects(table.get('allow', []))] if table else []
    if accounthost.is_account(parsed):
        return allow + [f'{path.name}: {line}' for line in accounthost.check(path, parsed, shared)]
    found = allow + rolecheck.host_refusals(path.name, parsed)
    if clientkeys.TABLE in parsed.get('ops', {}):
        found.append(f'{path.name}: [ops.{clientkeys.TABLE}] is derived by config fetch ([ops.config] clients); '
                     f'declare a machine key as [dev] {clientkeys.DEV_KEY} in its own host file')  # fmt: skip
    if 'dev' in parsed:
        found += [f'{path.name}: {line}' for line in devschema.check(parsed, shared)]
        if 'ssh' in parsed:
            found += [f'{path.name}: {line}' for line in devschema.ssh_defects(parsed['ssh'])]
    if 'ops' in parsed or 'dev' not in parsed:
        try:
            opsconfig.load(path, environ={}, as_root=False, structure_only=True)
        except (ValueError, TypeError, KeyError) as bad:
            return [*found, f'{path.name}: {bad}']
        found += [f'{path.name}: {line}' for line in _forge_repos(parsed.get('ops', {}), shared)]
    schema = {
        **DEFAULTS,
        'ops': {},
        'dev': {},
        'writeroots': {},  # every host's writable-root allowlist (WRITES-STAY-IN-THE-TREE, ruling R8)
        **({key: {} for key in devschema.MACHINE_TABLES} if 'dev' in parsed else {}),
        **({'ssh': {}} if 'dev' in parsed else {}),
        **({app: {} for app in devschema.app_tables(shared)} if 'dev' in parsed else {}),
    }
    return found + [f'{path.name}: {key} is not a declared key' for key in _undeclared(parsed, schema)]


def _forge_repos(ops: Mapping[str, Any], family: Mapping[str, Any]) -> list[str]:
    """``[ops.forge] repos`` against the family: exactly the ``[family_repos]`` rows on this host's forge sites.

    The family names every repository once; the forge's set is that list read on the forge's own sites
    (``[ops.caddy] sites``), so a repo added to the family and missed here (or kept here after it left) is named.
    """
    declared = ops.get('forge', {}).get('repos')
    sites = set(ops.get('caddy', {}).get('sites', ()))
    rows = family.get('family_repos')
    if declared is None or not sites or not isinstance(rows, Mapping):
        return []
    on_forge = set()
    for row in rows.values():
        url = urlsplit(str(row.get('remote', '')) if isinstance(row, Mapping) else '')
        if url.hostname in sites:
            on_forge.add(url.path.strip('/').removesuffix('.git'))
    missing, extra = sorted(on_forge - set(declared)), sorted(set(declared) - on_forge)
    found = [f'[ops.forge] repos is missing {missing}: [family_repos] lists them on {sorted(sites)}'] if missing else []
    if extra:
        found.append(f'[ops.forge] repos has extra {extra}: no [family_repos] row on {sorted(sites)}')
    return found


def _leaves(table: Mapping[str, Any], prefix: str = '') -> Iterator[tuple[str, Any]]:
    for key, value in table.items():
        dotted = f'{prefix}{key}'
        if isinstance(value, Mapping):
            yield from _leaves(value, f'{dotted}.')
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    yield from _leaves(item, f'{dotted}.')
                else:
                    yield dotted, item
        else:
            yield dotted, value


def check_family(path: Path) -> list[str]:
    """Defects of a family file: a machine-local table, or a secret value where a path belongs."""
    try:
        parsed = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as bad:
        return [f'{path.name}: not TOML: {bad}']
    found = [f'{path.name}: {line}' for line in devschema.check_family(parsed)]
    found += [
        f'{path.name}: [{name}] is machine-local; it lives in each machine file'
        for name in LOCAL_ONLY
        if name in parsed
    ]
    remotes = parsed.get('storage', {}).get('remotes', {})
    for name, remote in remotes.items():  # a remote's own secret_keys is the one source of which keys are secret
        found += [
            f'{path.name}: storage.remotes.{name}.{key} holds a secret value; name a file holding it (`*_file`)'
            for key in remote.get('secret_keys', ())
            if remote.get(key)
        ]
    judged = {key: item for key, item in parsed.items() if key not in LOCAL_ONLY}
    if remotes:
        judged['storage'] = {key: item for key, item in parsed['storage'].items() if key != 'remotes'}
    for dotted, value in _leaves(judged):
        if not isinstance(value, str) or not value:
            continue
        leaf = dotted.rsplit('.', 1)[-1]
        named = _SECRET_NAME.search(leaf) is not None and _PATH_NAME.search(leaf) is None
        if named or _SECRET_SHAPE.match(value):
            found.append(f'{path.name}: {dotted} holds a secret value; name a file holding it (`*_file`)')
    return found


def _listed(name: str, card: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Each (role, url, where) host card *name* lists a repo for: its judge's repos, its promoter's repos."""
    ops = card.get('ops', {})
    for role, duty in roles.DUTIES.items():
        if duty not in ops:
            continue
        listed = ops[duty].get('repos', ()) if role == roles.REVIEW else ops.get('repos', ())
        where = f'[ops.{duty}] repos' if role == roles.REVIEW else '[ops] repos'
        yield from ((role, url, f'{name}: {where}') for url in listed)


def check_roles(family: Path, hosts: Sequence[Path]) -> list[str]:
    """Where the family's roles binding and the *hosts*' files disagree; a host is named by its file's stem."""
    layer = tomllib.loads(family.read_text(encoding='utf-8'))
    cards = {path.stem: tomllib.loads(path.read_text(encoding='utf-8')) for path in hosts}
    found = [f'{family.name}: {line}' for line in roles.host_refusals(layer, cards)]
    for name, card in cards.items():
        for role, url, where in _listed(name, card):
            try:
                bound = roles.roles_of_url(url, layer=layer).of(role)
            except roles.Unbound as unbound:
                found.append(f'{where} lists {url}, but {unbound}')
                continue
            if bound != roles.Executor(roles.HOST, host=name):
                found.append(
                    f'{where} lists {url}, whose {role} the family binds to {bound}: the binding is the source'
                )
    return found


def check_routes(hosts: Sequence[Path]) -> list[str]:
    """Every route one development machine's host file declares to another (:mod:`dev_lab.dev.machineroutes`)."""
    cards = {}
    for path in hosts:
        try:
            cards[path.stem] = tomllib.loads(path.read_text(encoding='utf-8'))
        except tomllib.TOMLDecodeError:
            continue  # check_host names it
    return route_defects(cards)


def needs_consent(old: str, new: str) -> tuple[str, ...]:
    """The boundary keys a change from *old* to *new* touches (empty: it applies on the operator's word)."""
    return boundary(changes(tomllib.loads(old) if old else {}, tomllib.loads(new)))


def main(argv: list[str] | None = None) -> int:
    """``python -m dev_lab.ops.configcheck [--family F] [--against DIR] HOST...``; exit 1 on any defect."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.configcheck', description=__doc__.split('\n')[0])
    parser.add_argument('hosts', nargs='*', type=Path, help='host files, checked by structure')
    parser.add_argument('--family', type=Path, default=None, help='the family file')
    parser.add_argument('--against', type=Path, default=None, help="a directory holding the base's host files")
    args = parser.parse_args(argv)
    defects = [line for host in args.hosts for line in check_host(host, args.family)]
    defects += check_routes(args.hosts)
    if args.family is not None:
        defects += check_family(args.family) + check_roles(args.family, args.hosts)
    for line in defects:
        emit(f'refused: {line}', err=True)
    if args.against is not None:
        for host in args.hosts:
            base = args.against / host.name
            old = base.read_text(encoding='utf-8') if base.is_file() else ''
            if guarded := needs_consent(old, host.read_text(encoding='utf-8')):
                emit(f'{LABEL}: {host.name}: {list(guarded)}')
    return 1 if defects else 0


if __name__ == '__main__':
    raise SystemExit(main())
