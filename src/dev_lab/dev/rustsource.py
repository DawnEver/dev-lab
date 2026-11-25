"""A static reader of Rust source for the family's Rust checks: what a file uses, and what its free functions do.

No parser dependency and nothing compiled: a small lexer blanks comments and string/char literals (newlines kept,
so offsets stay lines), keeping only an ``extern "<abi>"`` literal, and blanks every ``#[cfg(test)]`` item -- test
code may use what the crate may not. On that code:

* :func:`paths_used` -- every path the file names: each ``use`` tree expanded (``std::sync::{Arc, Mutex}`` is two
  paths, a glob ends ``::*``) and every inline ``a::b`` path resolved through the names ``use`` binds; ``core::``
  and ``alloc::`` read as ``std::``.
* :func:`has_token` -- a token sequence (``unsafe``, ``extern "C"``) outside comments and literals.
* :func:`free_functions` -- each top-level ``pub fn``: its parameter names and its body, and whether the file has
  any other public item (``pub use`` re-exports excepted).

WHAT IT CANNOT SEE: macro bodies are read as code; a path reached through a ``type`` alias or a re-export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ['FreeFn', 'Items', 'bindings', 'code_of', 'free_functions', 'has_token', 'paths_used', 'split_top']

_EXTERN_ABI: Final = re.compile(r'\bextern\s*"[\w-]*"')
_RAW: Final = re.compile(r'(?:b|c)?r(#*)"')
_CFG_TEST: Final = re.compile(r'#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]')
_USE: Final = re.compile(r'(?<![\w:])use\s+')
_PATH: Final = re.compile(r'(?<![\w:])(?:::\s*)?([A-Za-z_]\w*(?:\s*::\s*(?:[A-Za-z_]\w*|\*))+)')
_PUB_FN: Final = re.compile(r'\bpub\s+(?:(?:const|async|unsafe|extern\s*"[\w-]*")\s+)*fn\s+([A-Za-z_]\w*)')
_PUB_OTHER: Final = re.compile(r'\bpub\s+(?:struct|enum|trait|type|static|mod|union|const\s+(?!fn\b))')
_IDENT: Final = re.compile(r'[A-Za-z_]\w*')
_OPEN: Final = {'(': ')', '[': ']', '{': '}', '<': '>'}


@dataclass(frozen=True, slots=True)
class FreeFn:
    """One top-level ``pub fn``: its name, each parameter's simple name (``None`` for a pattern), its body."""

    name: str
    params: tuple[str | None, ...]
    body: str


@dataclass(frozen=True, slots=True)
class Items:
    """A file's top-level public surface: its ``pub fn`` items, and whether it has any other public item."""

    functions: tuple[FreeFn, ...]
    other_public: bool


def _blank(text: str) -> str:
    return re.sub(r'[^\n]', ' ', text)


def _literal_end(text: str, i: int) -> int:
    """The index past the string literal starting at *i* (a ``"`` or a raw-string prefix)."""
    raw = _RAW.match(text, i)
    if raw and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == '_')):
        close = text.find('"' + raw.group(1), raw.end())
        return len(text) if close < 0 else close + 1 + len(raw.group(1))
    j = i + 1
    while j < len(text) and text[j] != '"':
        j += 2 if text[j] == '\\' else 1
    return j + 1


def _lex(text: str) -> str:
    """*text* with comments and literals blanked, newlines kept; an ``extern "<abi>"`` literal is kept."""
    keep = {m.end() - len(m.group().split('"')[1]) - 2 for m in _EXTERN_ABI.finditer(text)}
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
        elif text.startswith('/*', i):
            depth, j = 1, i + 2
            while j < n and depth:
                step = text[j : j + 2]
                depth += 1 if step == '/*' else -1 if step == '*/' else 0
                j += 2 if step in {'/*', '*/'} else 1
        elif c == '"' or (c in 'rbc' and _RAW.match(text, i) and (i == 0 or not text[i - 1].isalnum())):
            j = _literal_end(text, i)
            if i in keep:
                out.append(text[i:j])
                i = j
                continue
        elif c == "'" and i + 1 < n and text[i + 1] == '\\':
            j = text.find("'", i + 3) + 1 or n
        elif c == "'" and i + 2 < n and text[i + 2] == "'":
            j = i + 3
        else:
            out.append(c)
            i += 1
            continue
        out.append(_blank(text[i:j]))
        i = j
    return ''.join(out)


def _match(code: str, i: int) -> int:
    """The index past the bracket closing the one at *i*, counting that bracket kind only (``<`` ignores ``->``).

    Literals and comments are already blank, so one kind balances on its own; counting every kind would let a
    ``a < b`` comparison inside a body swallow its closing brace.
    """
    opener, closer, depth = code[i], _OPEN[code[i]], 0
    for j in range(i, len(code)):
        c = code[j]
        if c == opener:
            depth += 1
        elif c == closer and not (closer == '>' and code[j - 1] in '-='):
            depth -= 1
            if depth == 0:
                return j + 1
    return len(code)


def _item_end(code: str, i: int) -> int:
    """The index past the item starting at *i*: through its ``;`` or its braced body, whichever comes first."""
    j, depth = i, 0
    while j < len(code):
        c = code[j]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and c == ';':
            return j + 1
        elif depth == 0 and c == '{':
            return _match(code, j)
        j += 1
    return len(code)


def code_of(text: str) -> str:
    """The code of a Rust file: :func:`_lex` of *text*, then every ``#[cfg(test)]`` item blanked."""
    code = _lex(text)
    while (m := _CFG_TEST.search(code)) is not None:
        end = _item_end(code, m.end())
        code = code[: m.start()] + _blank(code[m.start() : end]) + code[end:]
    return code


def split_top(text: str, sep: str = ',') -> list[str]:
    """*text* split at each *sep* outside brackets, each part stripped, empty parts dropped."""
    parts, depth, start = [], 0, 0
    for j, c in enumerate(text):
        if c in '([{<':
            depth += 1
        elif c in ')]}>' and not (c == '>' and text[j - 1 : j] in {'-', '='}):
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:j])
            start = j + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _join(prefix: str, path: str) -> str:
    return f'{prefix}::{path}' if prefix and path else prefix or path


def _expand(prefix: str, tree: str) -> list[tuple[str, str | None]]:
    """``(full path, the local name it binds or None for a glob)`` for each leaf of the use tree *tree*."""
    tree = re.sub(r'\s+', ' ', tree).strip().removeprefix('::').strip()
    if (brace := tree.find('{')) >= 0:
        head = tree[:brace].strip().removesuffix('::').strip()
        inner = tree[brace + 1 : _match(tree, brace) - 1]
        return [leaf for part in split_top(inner) for leaf in _expand(_join(prefix, head), part)]
    path, _, alias = (s.strip() for s in tree.partition(' as '))
    path = re.sub(r'\s*::\s*', '::', path)
    if path.endswith('::self') or path == 'self':
        path = _join(prefix, path.removesuffix('self').removesuffix('::'))
        return [(path, alias or path.rpartition('::')[2])]
    full = _join(prefix, path)
    return [(full, None if path.endswith('*') else alias or full.rpartition('::')[2])]


def _normalized(path: str) -> str:
    head, sep, rest = path.partition('::')
    return f'std{sep}{rest}' if head in {'core', 'alloc'} else path


def bindings(code: str) -> dict[str, str]:
    """Every local name a ``use`` binds -> the full path it stands for (``core``/``alloc`` read as ``std``)."""
    return {name: _normalized(path) for path, name in _uses(code) if name is not None and name != '_'}


def _use_spans(code: str) -> list[tuple[int, int]]:
    return [(m.start(), _item_end(code, m.end())) for m in _USE.finditer(code)]


def _uses(code: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for start, end in _use_spans(code):
        tree = code[start:end].strip().removeprefix('use').rstrip().removesuffix(';')
        out += _expand('', tree)
    return out


def paths_used(code: str) -> frozenset[str]:
    """Every path *code* names: each ``use`` leaf and each inline path resolved through :func:`bindings`."""
    bound = bindings(code)
    found = {_normalized(path) for path, _ in _uses(code)}
    rest = code
    for start, end in _use_spans(code):
        rest = rest[:start] + _blank(rest[start:end]) + rest[end:]
    for m in _PATH.finditer(rest):
        head, _, rest = re.sub(r'\s*::\s*', '::', m.group(1)).partition('::')
        found.add(_normalized(f'{bound.get(head, head)}::{rest}'))
    return frozenset(found)


def has_token(code: str, token: str) -> bool:
    """Whether the token sequence *token* (words split on whitespace) occurs in *code* as whole tokens."""
    body = r'\s*'.join(re.escape(word) for word in token.split())
    return re.search(rf'(?<![\w]){body}(?![\w])', code) is not None


def _depths(code: str) -> list[int]:
    depth, out = 0, []
    for c in code:
        out.append(depth)
        depth += 1 if c == '{' else -1 if c == '}' else 0
    return out


def _param_name(param: str) -> str | None:
    pattern = split_top(param, ':')[0] if ':' in param else param
    pattern = pattern.removeprefix('mut ').strip()
    return pattern if _IDENT.fullmatch(pattern) else None


def free_functions(code: str) -> Items:
    """The top-level ``pub fn`` items of *code* (a :func:`code_of` result) and whether any other item is public."""
    depth = _depths(code)
    functions: list[FreeFn] = []
    for m in _PUB_FN.finditer(code):
        if depth[m.start()]:
            continue
        j = m.end()
        while j < len(code) and code[j].isspace():
            j += 1
        if j < len(code) and code[j] == '<':
            j = _match(code, j)
        start = code.find('(', j)
        close = _match(code, start)
        params = tuple(_param_name(p) for p in split_top(code[start + 1 : close - 1]))
        brace = code.find('{', close)
        semi = code.find(';', close)
        if brace < 0 or 0 <= semi < brace:
            continue
        functions.append(FreeFn(m.group(1), params, code[brace + 1 : _match(code, brace) - 1].strip()))
    other = any(not depth[m.start()] for m in _PUB_OTHER.finditer(code))
    return Items(tuple(functions), other)
