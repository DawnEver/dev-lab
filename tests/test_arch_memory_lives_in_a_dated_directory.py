"""MEMORY-SHAPE: every memory entry sits under `YYYY/MM/DD/`, and carries frontmatter.

WHY A SHAPE AND NOT A CONVENTION. A memory tree's index is GENERATED from what is on disk, so the
path is the only key a reader has: a file that names itself `.claude/memory/notes/foo.md` still gets
listed, still reads as a record, and is unreachable by date forever after. Downstream this exact
failure is on record -- a writer composed `.claude/memory/lanes/<lane>.md`, grew a seventeen-file
parallel tree with its own bookkeeping, and survived for days because the layout was a documented
instruction and NOTHING CHECKED THE SHAPE. A documented instruction is not a control.

THE FIRST THREE PARTS ARE THE DATE, and nothing below them is this guard's business: an
`attachments/` directory under a dated path is fine, and nesting is not the defect. What is refused
is a first segment that is not a year -- the route by which a second tree starts.

FRONTMATTER IS THE SECOND HALF, and it is one rule rather than two: the dated path makes an entry
findable by WHEN, the frontmatter makes it findable by WHAT. An entry with neither is a file in a
directory. The check is deliberately structural (a `---` fence opening the file with a `name:` and a
`description:` inside it) rather than a schema: this guard says an entry declares itself, not what
it declared.

THE FLOOR IS ONE, and that number is the point of the guard rather than a weakness in it. This tree
had NO `.claude/memory/` at all until 2026-09-15, which is why the rule was declared absent instead
of enforced -- a shape guard over a directory that does not exist passes, and reads as protection.
`MEMORY_FLOOR` in `_arch_corpus` is what turns that pass back into a refusal.
"""

from __future__ import annotations

from pathlib import Path

from _arch_corpus import MEMORY_FLOOR, ROOT, assert_floor, memory_entries

#: `YYYY / MM / DD` -- the three leading parts of every memory path, below `.claude/memory/`.
DATE_DEPTH = 3

#: The frontmatter keys an entry must declare. Two, because they are the two axes an index is built
#: on: `name` is the key, `description` is what a reader decides on without opening the file.
REQUIRED_KEYS = ('name:', 'description:')


#: The memory root of this tree. Passed EXPLICITLY into the predicate rather than read from it, so
#: the planted control below drives the real function over a real temporary tree instead of a mock.
MEMORY_ROOT = ROOT / '.claude' / 'memory'


def misshapen_entries(paths: tuple[Path, ...], memory_root: Path) -> tuple[str, ...]:
    """Every entry under *memory_root* that is not dated or declares no frontmatter -- pure."""
    out: list[str] = []
    for path in paths:
        inner = path.relative_to(memory_root)
        parts = inner.parts[:DATE_DEPTH]
        dated = len(inner.parts) > DATE_DEPTH and all(part.isdigit() for part in parts)
        name = inner.as_posix()
        if not dated:
            out.append(
                f'{name} does not sit under a YYYY/MM/DD directory: an index generated from the tree '
                f'will list it, and no reader can reach it by date'
            )
        text = path.read_text(encoding='utf-8')
        if not text.startswith('---'):
            out.append(f'{name} opens with no frontmatter fence, so it declares nothing about itself')
            continue
        head = text.split('---', 2)[1] if text.count('---') >= 2 else ''
        missing = [key for key in REQUIRED_KEYS if key not in head]
        if missing:
            out.append(f'{name} frontmatter declares no {", ".join(missing)}')
    return tuple(out)


def test_every_memory_entry_is_dated_and_declares_itself() -> None:
    """THE CHECK, over the tracked memory tree."""
    entries = memory_entries()
    assert_floor(len(entries), MEMORY_FLOOR, 'memory')
    problems = misshapen_entries(entries, MEMORY_ROOT)
    assert problems == (), 'these memory entries are not the shape the index assumes:\n  ' + '\n  '.join(problems)


def test_a_planted_misshapen_entry_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: four entries through the REAL predicate, one of each failure and one clean."""
    frontmatter = '---\nname: x\ndescription: y\n---\n\n# X\n'

    def plant(relative: str, body: str) -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        return path

    undated = plant('lanes/a-fork.md', frontmatter)
    bare = plant('2026/09/15/no-frontmatter.md', '# just a heading\n')
    partial = plant('2026/09/15/half-declared.md', '---\nname: x\n---\n\n# X\n')
    clean = plant('2026/09/15/good.md', frontmatter)

    problems = misshapen_entries((undated, bare, partial, clean), tmp_path)
    assert any('a-fork.md' in p and 'YYYY/MM/DD' in p for p in problems), 'an undated entry must be refused'
    assert any('no-frontmatter.md' in p and 'declares nothing' in p for p in problems)
    assert any('half-declared.md' in p and 'description:' in p for p in problems)
    assert not any('good.md' in p for p in problems), 'a dated, declared entry must pass'
