"""WHAT A CHECKOUT NEEDS ON THIS HOST BEFORE ITS ENVIRONMENT CAN BUILD, each gap named with its remedy.

``dep --bootstrap`` prints :func:`diagnose` before it syncs, so a cold box learns every missing tool at once rather
than one wall at a time; ``python -m dev_lab.dev.toolchain [--root ROOT] [--probe-linker]`` prints it alone.

* ``git`` and ``uv`` -- every family checkout needs both;
* a Python fitting the TARGET's ``requires-python`` (``uv python find <spec>``), never the caller's;
* ``cargo`` -- only when the checkout holds a ``Cargo.toml``; rustup's ``~/.cargo/bin`` counts, since the shell that
  just ran rustup does not have it on PATH yet;
* a C LINKER -- ``--probe-linker`` builds a trivial cdylib under the checkout's own ``rust-toolchain.toml``: rustup on
  Windows installs no linker, so cargo exists, every Rust-only check passes, and the first real build fails at link
  time. The probe turns that wall into one named remedy (VS Build Tools, or without admin rights a portable MSVC).

A gap is DATA (:class:`Gap`), never an exit: the caller decides what blocks.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['Gap', 'diagnose', 'main', 'probe_linker']

_WINDOWS: Final = sys.platform == 'win32'
_EXE: Final = '.exe' if _WINDOWS else ''
_REMEDIES: Final[dict[str, str]] = {
    'git': 'winget install --id Git.Git -e' if _WINDOWS else 'install git with the system package manager',
    'uv': 'winget install --id astral-sh.uv -e' if _WINDOWS else 'curl -LsSf https://astral.sh/uv/install.sh | sh',
    'cargo': ('install rustup (https://rustup.rs) with --default-toolchain none; the checkout pins its own toolchain'),
    'linker': (
        'winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add '
        'Microsoft.VisualStudio.Workload.VCTools --includeRecommended"; without admin rights, a portable MSVC '
        '(https://gist.github.com/mmozeiko/7f3162ec2988e81e56d5c4e22cde9977) wired into ~/.cargo/config.toml'
        if _WINDOWS
        else ('xcode-select --install' if sys.platform == 'darwin' else 'install build-essential (gcc, make)')
    ),
}
_PROBE_TIMEOUT_S: Final = 600
_FIND_TIMEOUT_S: Final = 60


@dataclass(frozen=True)
class Gap:
    """One missing prerequisite: what, why it is needed here, and the remedy."""

    tool: str
    why: str
    remedy: str

    def line(self) -> str:
        """The gap as one ``toolchain: MISSING`` line."""
        return f'toolchain: MISSING {self.tool} -- {self.why}. Remedy: {self.remedy}'


def _requires_python(root: Path) -> str:
    manifest = root / 'pyproject.toml'
    project = tomllib.loads(manifest.read_text(encoding='utf-8')).get('project', {}) if manifest.is_file() else {}
    return str(project.get('requires-python') or '')


def _cargo(which: Callable[[str], str | None], home: Path) -> str | None:
    rustup = home / '.cargo' / 'bin' / f'cargo{_EXE}'
    return which('cargo') or (str(rustup) if rustup.is_file() else None)


def _python_found(uv: str, spec: str) -> bool:
    done = _door.run(
        [uv, 'python', 'find', spec],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_FIND_TIMEOUT_S,
    )
    return done.returncode == 0


#: Trees never searched for a Cargo manifest: environments, build outputs, VCS state.
_PRUNED: Final = frozenset({'.git', '.venv', '.venvs', 'target', 'node_modules', 'output', '.claude'})


def _holds_rust(root: Path) -> bool:
    for _here, dirs, files in os.walk(root):
        if 'Cargo.toml' in files:
            return True
        dirs[:] = [name for name in dirs if name not in _PRUNED]
    return False


def diagnose(
    root: Path,
    *,
    which: Callable[[str], str | None] = shutil.which,
    home: Path | None = None,
    python_found: Callable[[str, str], bool] = _python_found,
) -> list[Gap]:
    """Every prerequisite *root* needs that this host lacks, in install order."""
    gaps = [
        Gap(tool, 'every family checkout needs it', _REMEDIES[tool]) for tool in ('git', 'uv') if which(tool) is None
    ]
    uv, spec = which('uv'), _requires_python(root)
    if uv is not None and spec and not python_found(uv, spec):
        gaps.append(Gap(f'python {spec}', f'{root} declares requires-python {spec}', f'{uv} python install "{spec}"'))
    if _holds_rust(root) and _cargo(which, home or Path.home()) is None:
        gaps.append(Gap('cargo', f'{root} holds a Rust workspace', _REMEDIES['cargo']))
    return gaps


def probe_linker(
    root: Path, cargo: str, *, run: Callable[..., tuple[int, str]] | None = None, work: Path | None = None
) -> Gap | None:
    """Build a trivial cdylib with *cargo* under *root*'s ``rust-toolchain.toml``; the linker gap, or ``None``."""

    def default(argv: list[str]) -> tuple[int, str]:
        done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=_PROBE_TIMEOUT_S)
        return done.returncode, done.stderr

    with tempfile.TemporaryDirectory(prefix='dev-lab-linker-') as scratch:
        probe = (work or Path(scratch)) / 'linker_probe'
        (probe / 'src').mkdir(parents=True, exist_ok=True)
        (probe / 'Cargo.toml').write_text(
            '[package]\nname = "linker_probe"\nversion = "0.0.0"\nedition = "2021"\n[lib]\ncrate-type = ["cdylib"]\n',
            encoding='utf-8',
        )
        (probe / 'src' / 'lib.rs').write_text(
            '#[no_mangle]\npub extern "C" fn probe() -> i32 { 42 }\n', encoding='utf-8'
        )
        pin = root / 'rust-toolchain.toml'
        if pin.is_file():  # the probe sits outside the checkout, where its pin would not apply
            shutil.copyfile(pin, probe / 'rust-toolchain.toml')
        code, stderr = (run or default)([cargo, 'build', '--manifest-path', str(probe / 'Cargo.toml')])
    if code == 0:
        return None
    said = stderr.strip().splitlines()[-1] if stderr.strip() else 'no stderr'
    return Gap('linker', f'cargo is present but cannot link (probe said: {said})', _REMEDIES['linker'])


def main(argv: Sequence[str] | None = None) -> int:
    """Print every gap; exit 1 when any, else 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.toolchain', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout (default: cwd)')
    parser.add_argument('--probe-linker', action='store_true', help='also build a trivial cdylib to prove a linker')
    args = parser.parse_args(argv)
    gaps = diagnose(args.root)
    cargo = _cargo(shutil.which, Path.home())
    if args.probe_linker and cargo is not None and (linker := probe_linker(args.root, cargo)) is not None:
        gaps.append(linker)
    for gap in gaps:
        emit(gap.line())
    if not gaps:
        emit(f'toolchain: {args.root} has every prerequisite this host can check')
    return 1 if gaps else 0


if __name__ == '__main__':
    raise SystemExit(main())
