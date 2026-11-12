"""EVERY FORGE CALL RETRIES: no HTTP exchange opens outside the one retrying loop, unless named here with its reason.

The loop is :func:`dev_lab.dev.forgefailure.retried` (transient -> retry with backoff, rate limit -> wait, refused
credential -> stop with the named remedy); :class:`dev_lab.dev.forgework.Client` and
:func:`dev_lab.dev.actionsartifact.retrying` run every exchange through it. INCIDENT 2026-11-12: the review job's
first step (``reviewcode``) called the forge raw, once, and swallowed every failure -- a refused job token included;
``ops.giteaadmin`` asked the host's Gitea with no retry, and the review workflow's inline fetch did the same.

THE SCAN. Every module in ``src`` that opens a connection itself -- a call to ``HTTPConnection`` /
``HTTPSConnection``, or any reference to ``urlopen`` (a default argument included) -- and every TOML under ``src``
whose inline program calls ``urlopen(``, must be a row of :data:`OPENS_A_CONNECTION`: a transport the loop wraps,
a stdlib twin a test pins to it, or a host that is not a forge. The set is the ceiling: a new raw forge call is a
new row a reviewer reads, never a silent one.
"""

from __future__ import annotations

import ast
from typing import Final

import pytest
from _arch_corpus import ROOT, assert_floor, parse, rel, source_modules

#: Who opens an HTTP connection itself, and why that is not a forge call bypassing the loop.
OPENS_A_CONNECTION: Final[dict[str, str]] = {
    'src/dev_lab/dev/forge.py': 'forge_transport: the connection every forgework.Client exchange opens inside '
    'forgefailure.retried',
    'src/dev_lab/dev/actionsartifact.py': '_urllib_once: the exchange actionsartifact.retrying runs through '
    'forgefailure.retried',
    'src/dev_lab/ops/giteaadmin.py': '_exchange: the exchange local_api runs through forgefailure.retried',
    'src/dev_lab/dev/reviewcode.py': 'stdlib only (fetched alone before any install): forge_call is the bare twin '
    'of forgefailure.retried, every decision pinned by test_the_bare_loop_decides_as_the_family_loop_does',
    'src/dev_lab/dev/ci_base.toml': "the review settle step's inline fetch of reviewcode, before it exists on the "
    'runner: retried as reviewcode does, pinned by test_the_settle_step_s_own_reads_retry_a_transient_and_report_a_'
    'refused_token',
    'src/dev_lab/dev/dep_observe.py': 'PyPI, not a forge',
    'src/dev_lab/dev/security.py': 'the OSV database, not a forge',
    'src/dev_lab/supervise/transport.py': 'alert webhooks, not a forge',
}

#: The openers the scan finds: MEASURED 2026-11-12 at 8 (every row above); a floor refuses an unread corpus.
OPENER_FLOOR: Final = 8

_CONNECTIONS: Final = frozenset({'HTTPConnection', 'HTTPSConnection'})


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ''


def opens(tree: ast.Module) -> list[int]:
    """The line of every connection *tree* opens itself: a connection constructed, or ``urlopen`` referenced."""
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if (isinstance(node, ast.Call) and _name(node.func) in _CONNECTIONS)
            or (isinstance(node, (ast.Name, ast.Attribute)) and _name(node) == 'urlopen')
        }
    )


def _toml_openers() -> dict[str, list[int]]:
    found = {}
    for path in sorted((ROOT / 'src').rglob('*.toml')):
        text = path.read_text(encoding='utf-8')
        if lines := [n for n, line in enumerate(text.splitlines(), 1) if 'urlopen(' in line]:
            found[rel(path)] = lines
    return found


def test_no_forge_call_opens_outside_the_retrying_loop() -> None:
    found = {rel(path): lines for path in source_modules() if (lines := opens(parse(path)))}
    found |= _toml_openers()
    assert_floor(len(found), OPENER_FLOOR, 'modules opening an HTTP connection')
    raw = {path: lines for path, lines in found.items() if path not in OPENS_A_CONNECTION}
    assert raw == {}, f'route these through forgework.Client or forgefailure.retried, or name why not: {raw}'
    stale = sorted(path for path in OPENS_A_CONNECTION if path not in found)
    assert stale == [], f'rows naming a module that no longer opens a connection -- delete them: {stale}'


#: reviewcode's forge door before 2026-11-12: one raw call, no retry -- the shape this test exists to refuse.
_OLD_REVIEWCODE: Final = """
def forge_call(token):
    def call(method, url, body):
        request = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(request, timeout=60) as reply:
            return json.loads(reply.read())
    return call
"""


@pytest.mark.parametrize(
    ('body', 'flagged'),
    [
        (_OLD_REVIEWCODE, True),
        ('def f(host):\n    return http.client.HTTPSConnection(host, timeout=5)\n', True),
        ('def f(token, *, opener=urllib.request.urlopen):\n    return opener\n', True),
        ("def f(client):\n    return client.call('GET', client.repo)\n", False),
        ("def f(once):\n    return retried(('GET', '/x'), once)\n", False),
        ('X: type = http.client.HTTPConnection\n', False),
    ],
)
def test_a_planted_raw_forge_call_is_flagged_and_one_through_the_loop_passes(body: str, *, flagged: bool) -> None:
    """PLANTED CONTROL: reviewcode's old raw call is caught; a call through the client or the loop is not."""
    assert bool(opens(ast.parse(body))) is flagged
