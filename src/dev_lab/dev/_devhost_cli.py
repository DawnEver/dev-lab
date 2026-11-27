"""The command line of :mod:`dev_lab.dev.devhost`: its verbs and their options, and nothing they do.

:func:`dev_lab.dev.devhost.main` parses with :func:`parser` and dispatches; each verb's behaviour stays there or in
the module that adds the verb (``use-store``, ``enroll``, ``admit``, ``vendor-row``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dev_lab.dev import devhostadmit, forgecredential, forgeenroll, vendorrow

__all__ = ['parser']


def parser(description: str | None) -> argparse.ArgumentParser:
    """The ``python -m dev_lab.dev.devhost`` parser, *description* its help text."""
    made = argparse.ArgumentParser(prog='python -m dev_lab.dev.devhost', description=description)
    made.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    verbs = made.add_subparsers(dest='verb', required=True)
    drifting = verbs.add_parser('drift', help='report where the machine file departs from its render')
    drifting.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    verbs.add_parser('session-start', help='the SessionStart hook: the machine-file notice, if any; always 0')
    telling = verbs.add_parser('channels', help="print this machine's declared session channels (source -> user)")
    telling.add_argument('--json', action='store_true', required=True, help='as one JSON object ({} when undeclared)')
    finding = verbs.add_parser('detect', help="print the host-file lines for this machine's vendor install homes")
    finding.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making = verbs.add_parser('render', help='render the machine file from the family and host files')
    making.add_argument('--host', default=None, help='the host name (default: the live [devhost] host, else this one)')
    making.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--write', action='store_true', help='back the live file up, then replace it')
    making.add_argument(
        '--backups', type=Path, default=None, help='where the backup goes (default: backedup.backups_dir)'
    )
    forgecredential.add_use_store(verbs)
    forgeenroll.add_enroll(verbs)
    devhostadmit.add_admit(verbs)
    vendorrow.add_vendor_row(
        verbs.add_parser('vendor-row', help='write a CONFIRMED vendor location row on a config-source PR branch')
    )
    checking = verbs.add_parser('bringup', help='list every wall a new workstation hits, each with its door')
    checking.add_argument('--check', action='store_true', required=True, help='read only; exit 1 while a wall stands')
    setting = verbs.add_parser('local', help='set or unset ONE local-layer key ([repos], [user]) and re-render')
    local_verbs = setting.add_subparsers(dest='local_verb', required=True)
    one = local_verbs.add_parser('set', help='set <table>.<key> to <value>')
    one.add_argument('key', help='<table>.<key>, e.g. repos.dev-lab')
    one.add_argument('value', help='the value; a [repos] path must be absolute')
    gone = local_verbs.add_parser('unset', help='remove <table>.<key>')
    gone.add_argument('key', help='<table>.<key>')
    for sub in (one, gone):
        sub.add_argument(
            '--backups', type=Path, default=None, help='where the backup goes (default: backedup.backups_dir)'
        )
    return made
