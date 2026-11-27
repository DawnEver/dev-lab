"""SHARE-FOLDER-HOLDS-DATA, as the assertion a consumer runs over the synced share folders it declares.

A synced share folder (a meeting folder in a cloud drive) is shared mutable state with a live human on the other
end. It keeps DATA (csv/json/xlsx/npz) and, for every figure, the production command that regenerates it; it never
keeps the rendered png/jpg/svg -- that regenerates under the checkout's ``output/`` tree. A source image nothing can
regenerate (a teardown photo, a measurement screenshot) is INPUT and stays, declared by name.

THE DECLARATION is one file per folder, :data:`MANIFEST`::

    inputs = ["teardown.jpg"]                                    # images that are INPUT, kept
    [figures]
    "torque.png" = "uv run <cli> case run cases/x --plot"        # each figure -> the command regenerating it

THE REPO-SHAPED FACT ARRIVES AS AN ARGUMENT WITH NO DEFAULT: the folders to read. The assertion only READS them.

WHAT THIS DOES NOT PROVE: that a declared command actually reproduces the figure -- only that one is named.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ['IMAGE_SUFFIXES', 'MANIFEST', 'RULE', 'assert_every_share_folder_holds_data', 'share_folder_problems']

RULE: Final = 'SHARE-FOLDER-HOLDS-DATA'
#: The per-folder declaration of input images and figure commands.
MANIFEST: Final = 'share.toml'
#: A rendered image, by suffix (case-insensitive).
IMAGE_SUFFIXES: Final = frozenset({'.png', '.jpg', '.jpeg', '.svg', '.gif', '.bmp', '.tif', '.tiff', '.webp'})
_DOOR: Final = (
    'delete the rendered file and name the production command that regenerates it under [figures] in '
    f'{MANIFEST} (it renders under output/); a source image nothing can regenerate is listed in `inputs`'
)


def share_folder_problems(folder: Path) -> list[str]:
    """Every way *folder* breaks the rule, each naming its file and the door; ``[]`` when it holds."""
    try:
        data = tomllib.loads((folder / MANIFEST).read_text(encoding='utf-8'))
    except OSError:
        return [f'{RULE}: {folder} has no {MANIFEST} naming the command behind each figure -- {_DOOR}']
    except tomllib.TOMLDecodeError as broken:
        return [f'{RULE}: {folder / MANIFEST} is not TOML ({broken})']
    inputs: object = data.get('inputs', [])
    figures: object = data.get('figures', {})
    if not isinstance(inputs, list) or not isinstance(figures, dict):
        return [f'{RULE}: {folder / MANIFEST} needs `inputs` a list and `[figures]` a table']
    figures = cast('dict[str, object]', figures)
    kept = {str(one) for one in cast('list[object]', inputs)}
    problems = [
        f'{RULE}: figure {name!r} in {folder / MANIFEST} names no regenerating command'
        for name, command in figures.items()
        if not isinstance(command, str) or not command.strip()
    ]
    for path in sorted(folder.rglob('*')):
        rel = path.relative_to(folder).as_posix()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and rel not in kept:
            problems.append(f'{RULE}: {folder} holds the rendered image {rel} -- {_DOOR}')
    return problems


def assert_every_share_folder_holds_data(folders: Sequence[Path]) -> None:
    """Fail naming every rendered image or command-less figure across *folders*; an empty list is refused."""
    if not folders:
        msg = f'{RULE}: no share folder was declared, so the scan would read green on nothing'
        raise AssertionError(msg)
    found = [one for folder in folders for one in share_folder_problems(folder)]
    if found:
        raise AssertionError('\n'.join(found))
