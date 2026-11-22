"""IMAGES-BY-ABSOLUTE-PATH: a final message that delivers an image names it by its ABSOLUTE path.

User ruling 2026-11-22: when an image is delivered, an absolute path must be used. A relative path resolves
against a working directory the reader is not in -- an agent works in a worktree, the user reads from somewhere
else -- so the figure cannot be opened from the message that announces it.

THE MECHANISM is the ``Stop``/``SubagentStop`` hook (:mod:`dev_lab.dev.handback`), which already reads the final
assistant message: :func:`refusal` blocks the stop once with the paths it found and the door.

WHAT IS READ, and what is not. A path TOKEN ending in an image suffix (:data:`IMAGE_SUFFIXES`) with a file stem,
wherever it stands -- a markdown image, a code span, bare prose. Let through: an absolute path (a drive, a
leading ``/`` or a UNC share), a URL, a ``data:`` source, a pattern or template (``*.png``, ``<name>.png``,
``{stem}.png``), a path through a shell variable, and a bare suffix. The text cannot say whether a mentioned
image is DELIVERED or merely discussed, so both are read: naming a file absolutely is never wrong.
"""

from __future__ import annotations

import re
from typing import Final

from dev_lab.dev.disclosure import details_for

__all__ = ['IMAGE_SUFFIXES', 'RULE', 'refusal', 'relative_images']

RULE: Final = 'IMAGES-BY-ABSOLUTE-PATH'

#: What an image is, as a NAMED SET: a data or document suffix here would refuse every report citing a file.
IMAGE_SUFFIXES: Final = frozenset({'.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.bmp', '.tif', '.tiff'})

#: How many paths the refusal quotes before it counts the rest, and how much of each.
_SHOWN: Final = 2
_QUOTED_CHARS: Final = 80

#: A path token: ASCII word characters and the punctuation a path is spelled with.
_TOKEN: Final = re.compile(r'[\w./\\:~@%+$-]+', re.ASCII)
#: Where an absolute path, a URL or a ``data:`` source starts.
_ABSOLUTE: Final = re.compile(r'(?:[A-Za-z]:[\\/]|/|\\\\|[A-Za-z][\w+.-]*://|data:)', re.ASCII)
#: What opens a delimited span a path with spaces sits in.
_OPENERS: Final = '`"\'('


def _image_stem(token: str) -> bool:
    """Does *token* end in an image suffix after a real file stem (``.png`` alone and ``x/.png`` do not)?"""
    leaf = re.split(r'[\\/]', token)[-1]
    stem, dot, suffix = leaf.rpartition('.')
    return bool(dot) and bool(stem.strip('.')) and f'.{suffix.lower()}' in IMAGE_SUFFIXES


def _continues_an_absolute_path(line: str, start: int) -> bool:
    """Is the token at *start* the tail of an absolute path with spaces, inside the span that delimits it?"""
    head = line[:start]
    opener = max(head.rfind(mark) for mark in _OPENERS)
    return opener >= 0 and _ABSOLUTE.match(head[opener + 1 :]) is not None


def relative_images(text: str) -> tuple[str, ...]:
    """Every image *text* names by a path that is not absolute, once each, in order. PURE."""
    found: list[str] = []
    for line in text.splitlines():
        for match in _TOKEN.finditer(line):
            token = match.group().rstrip('.:')
            before = line[match.start() - 1] if match.start() else ''
            if not _image_stem(token) or '$' in token or before in '>}*':
                continue
            if _ABSOLUTE.match(token) or _continues_an_absolute_path(line, match.start()):
                continue
            found.append(token)
    return tuple(dict.fromkeys(found))


def refusal(text: str) -> str | None:
    """The block reason when *text* names an image by a relative path, else ``None``."""
    relative = relative_images(text)
    if not relative:
        return None
    shown = relative[:_SHOWN]
    listed = '; '.join(f'`{path[:_QUOTED_CHARS]}`' for path in shown) + (
        f' (+{len(relative) - len(shown)} more)' if relative[len(shown) :] else ''
    )
    return (
        f'{RULE}: this turn names an image by a relative path ({listed}); it resolves against a working '
        'directory the reader is not in.\n'
        'Name each image by its ABSOLUTE path -- resolved against the checkout it was written in -- and '
        'say it again.\n'
        f'{details_for(RULE)}'
    )
