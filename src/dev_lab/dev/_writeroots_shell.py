"""The SHELL half of :mod:`dev_lab.dev.writeroots`: every target a shell line writes, as spelled.

Split out of :mod:`dev_lab.dev.writeroots` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module judges
a path against the machine's writable roots; this one only READS a line -- tokens, heredocs, redirects, the cwd a
``cd`` moves -- and places nothing.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ['shell_targets']

_TOKEN: Final = re.compile(r"""\d?>>?|&>>?|\|\||&&|[|;&\n]|<<?|(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s|;&<>"'])+""")
_HEREDOC: Final = re.compile(r"""<<-?\s*(["']?)([A-Za-z_][A-Za-z0-9_]*)\1""")
_REDIRECT: Final = re.compile(r'\d?>>?|&>>?')
_SEPARATORS: Final = frozenset({'|', '||', '&&', ';', '&', '\n'})
_DISCARDS: Final = frozenset({'/dev/null', '/dev/stdout', '/dev/stderr', '/dev/tty', 'nul', '$null'})
_CD: Final = frozenset({'cd', 'pushd', 'set-location', 'sl', 'chdir'})
_EACH_OPERAND: Final = frozenset({'mkdir', 'touch', 'tee'})
_LAST_OPERAND: Final = frozenset({'cp', 'mv', 'copy', 'move', 'rsync', 'install', 'copy-item', 'move-item'})
_PS_WRITERS: Final = frozenset({'new-item', 'ni', 'out-file', 'set-content', 'add-content'})
_PS_PATH: Final = frozenset({'-path', '-filepath', '-literalpath', '-destination'})
#: PowerShell writer options that take a value, which is no target.
_PS_VALUED: Final = frozenset({'-itemtype', '-type', '-value', '-encoding', '-inputobject', '-name'})


def _without_heredoc_bodies(command: str) -> str:
    """*command* without its heredoc BODIES; the opening line stays whole, a redirect after ``<<EOF`` included."""
    out, index = '', 0
    for match in _HEREDOC.finditer(command):
        if match.start() < index:
            continue
        body = command.find('\n', match.end())
        if body == -1:
            break
        closer = re.compile(rf'^[ \t]*{re.escape(match.group(2))}[ \t]*$', re.MULTILINE)
        end = closer.search(command, body + 1)
        out += command[index:body] + '\n'
        index = len(command) if end is None else end.end()
    return out + command[index:]


def _unquote(token: str) -> str:
    return ''.join(
        part[1:-1] if part[:1] in '"\'' else part for part in re.findall(r'"[^"]*"|\'[^\']*\'|[^"\']+', token)
    )


def _absolute(text: str) -> bool:
    return bool(re.match(r'^(?:[A-Za-z]:[\\/]|[\\/]|~|\$|%)', text))


def _segment_targets(words: list[str], cwd: str, found: list[tuple[str, str]]) -> str:
    """Append the targets one command segment (*words*) writes to *found*; return the cwd after it."""
    if not words:
        return cwd
    verb = words[0].replace('\\', '/').rsplit('/', 1)[-1].casefold()
    operands = [one for one in words[1:] if not one.startswith('-')]
    if verb in _CD and operands:
        return operands[0] if not cwd or _absolute(operands[0]) else f'{cwd}/{operands[0]}'
    if verb in _EACH_OPERAND:
        found.extend((one, cwd) for one in operands)
    elif verb in _LAST_OPERAND and len(operands) > 1:
        found.append((operands[-1], cwd))
    elif verb == 'dd':
        found.extend((one[3:], cwd) for one in words[1:] if one.startswith('of='))
    elif verb in _PS_WRITERS:
        named = [words[i + 1] for i, one in enumerate(words[:-1]) if one.casefold() in _PS_PATH]
        valued = {i + 1 for i, one in enumerate(words) if one.casefold() in _PS_VALUED}
        positional = [one for i, one in enumerate(words) if i and i not in valued and not one.startswith('-')]
        found.extend((one, cwd) for one in (named or positional[:1]))
    return cwd


def shell_targets(command: str) -> list[tuple[str, str]]:
    """Each (target, the cwd it is relative to -- ``''`` for the call's own) a shell line writes, as spelled.

    Read: a redirect (``>``, ``>>``, ``2>``, ``&>``), ``tee``/``mkdir``/``touch`` operands, the last operand of a
    copy or move, ``dd of=``, a PowerShell writer's ``-Path``/``-FilePath``/``-Destination`` or first operand; a
    ``cd``/``pushd``/``Set-Location`` moves the cwd later targets are relative to. A discard (``/dev/null``) is none.
    """
    found: list[tuple[str, str]] = []
    cwd = ''
    segment: list[str] = []
    redirect = False
    for token in [*_TOKEN.findall(_without_heredoc_bodies(command)), '\n']:
        if redirect:
            redirect = False
            if not token.startswith('&'):
                found.append((_unquote(token), cwd))
        elif _REDIRECT.fullmatch(token):
            redirect = True
        elif token in _SEPARATORS:
            cwd = _segment_targets([_unquote(one) for one in segment], cwd, found)
            segment = []
        elif token not in ('<', '<<'):
            segment.append(token)
    return [(target, where) for target, where in found if target and target.casefold() not in _DISCARDS]
