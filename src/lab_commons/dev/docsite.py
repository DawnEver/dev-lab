"""Build a documentation site: one entry, a TABLE of sub-sites, and no silent success.

THREE IMPLEMENTATIONS EXISTED, and the properties were distributed across them rather than shared.
MEASURED 2026-09-16, by reading all three:

======================  ====================  ===================  =======================
property                motronics repo/docs   wdg-lab scripts/docs  optimi-lab scripts/pdoc
======================  ====================  ===================  =======================
``check=True``          yes, via one helper   yes, at 3 call sites  **NO** (``check=False``)
skip-and-SAY-SO         yes, a report row     partial (webui only)  **no skip concept**
``sys.executable -m``   yes                   only as a fallback    yes
a subprocess timeout    yes (1800 s)          no                    no
mutually-exclusive      no                    no                    **yes** -- passes pdoc
``-o`` + ``-h``/``-p``                                              both modes at once
======================  ====================  ===================  =======================

The ``check=False`` row is the one that justifies this module existing. It is the ``dict.get(k, 0.0)``
shape: a pdoc that errored produced an empty ``docs/`` and exit 0, indistinguishable from a real
build at every downstream point -- and combined with the mutually-exclusive-modes row, optimi-lab's
build was invoking pdoc in a way pdoc rejects and reporting success for it.

THE SPLIT THIS MODULE MAKES. The DRIVER is the family's: what a requirement is, what a skip means,
what the portal says about a sub-site that was not built, and that every subprocess is checked and
bounded. The FACTS are the caller's: which packages, which output path, which extra flags, which
logo. A repo supplies :class:`SubSite` rows; nothing here knows what product it is describing.

A SKIP IS ANNOUNCED, NEVER SILENT. Rust is not installed everywhere and a Node toolchain even less
so, so a sub-site whose tool is absent is skipped -- but it is named in the report AND on the portal
page, because silence makes "the Rust docs are missing" and "there are no Rust docs" the same
observation. :attr:`BuildReport.skipped` is a mapping and not a count for the same reason: "3
sub-sites skipped" is the shape of message that lets a permanently-broken toolchain look routine.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lab_commons.dev._docsite_portal import render_portal

__all__ = [
    'DEFAULT_TIMEOUT_S',
    'IMAGE_SUFFIXES',
    'PDOC_FLAGS',
    'BuildReport',
    'Every',
    'Exe',
    'Module',
    'Requirement',
    'SubSite',
    'Tree',
    'build_all',
    'mirror_module_images',
    'open_site',
    'pdoc_argv',
    'pdoc_site',
    'render_portal',
    'run',
]

#: A docs build is a minute or two. The bound is what fails loudly instead of hanging a pre-commit
#: hook nobody is watching -- an unbounded subprocess in a hook is a hang with no exit code.
DEFAULT_TIMEOUT_S: Final = 1800

#: What :func:`mirror_module_images` carries next to the generated pages. pdoc references images by
#: their in-package relative path but does not copy them, so without this every diagram in a
#: docstring renders as a broken link.
IMAGE_SUFFIXES: Final = frozenset({'.svg', '.png', '.jpg', '.jpeg'})

#: The pdoc flags all three repos passed identically, kept as data so a caller adds to them rather
#: than restating them. ``-h``/``-p`` are deliberately ABSENT: they select pdoc's SERVE mode, which
#: is mutually exclusive with ``-o``, and one caller was passing both.
PDOC_FLAGS: Final[tuple[str, ...]] = (
    '--include-undocumented',
    '--math',
    '--mermaid',
    '--search',
    '--show-source',
)


@dataclass(frozen=True)
class Exe:
    """A requirement satisfied by an executable on ``PATH`` (or an absolute path)."""

    name: str

    def present(self) -> bool:
        """Whether the executable resolves on PATH, or exists as the absolute path given."""
        return shutil.which(self.name) is not None or Path(self.name).exists()

    @property
    def absent_kind(self) -> str:
        """What its absence MEANS, so the reader is sent to install rather than to clone."""
        return 'not on PATH'


@dataclass(frozen=True)
class Module:
    """A requirement satisfied by an importable Python module.

    Distinct from :class:`Exe` because ``shutil.which`` answers a different question and would
    report a perfectly installed library as missing. One field meaning two things, disambiguated by
    convention, is the shape this family keeps finding drifted.
    """

    name: str

    def present(self) -> bool:
        """Whether the module is importable in THIS interpreter."""
        return importlib.util.find_spec(self.name) is not None

    @property
    def absent_kind(self) -> str:
        """What its absence MEANS: an install into this interpreter, not a PATH entry."""
        return 'not importable'


@dataclass(frozen=True)
class Tree:
    """A requirement satisfied by a path that EXISTS -- a sibling checkout, a manifest.

    A third kind rather than an ``Exe`` pointed at a directory, for the reason :class:`Module` is a
    second kind: the ABSENT_KIND is what the reader acts on, and "not on PATH" is the wrong remedy
    for a repository that was never cloned.
    """

    name: str

    def present(self) -> bool:
        """Whether the path exists at all -- a sibling checkout, a manifest."""
        return Path(self.name).exists()

    @property
    def absent_kind(self) -> str:
        """What its absence MEANS: a tree that was never cloned or written."""
        return 'not present'


@dataclass(frozen=True)
class Every:
    """Every one of several requirements -- a sub-site can need a toolchain AND a checkout.

    The absent kind NAMES the missing parts rather than saying "something is missing", because a
    composite that only reports its own absence sends the reader to check all of them.
    """

    parts: tuple[Requirement, ...]

    @property
    def name(self) -> str:
        """The composite name: every part, joined, so the reader sees all of them."""
        return ' + '.join(part.name for part in self.parts)

    def present(self) -> bool:
        """Whether EVERY part is present; one missing part makes the composite absent."""
        return all(part.present() for part in self.parts)

    @property
    def absent_kind(self) -> str:
        """What is missing, PART BY PART, so the reader is not sent to check all of them."""
        missing = ', '.join(f'{part.name} ({part.absent_kind})' for part in self.parts if not part.present())
        return f'missing {missing}'


Requirement = Exe | Module | Tree | Every


@dataclass(frozen=True)
class SubSite:
    """One documentation sub-site: what it is, what it needs, how to build it.

    Attributes:
        slug: Directory under the output root, and the portal link target.
        title: Human-readable name on the portal page.
        requires: What must be installed. Absence is a SKIP, never a failure --- but always an
            announced one.
        absent_means: What the reader LOSES when ``requires`` is unmet. Shown on the portal in
            place of the link, so a gap reads as a gap rather than as a sub-site nobody intended.
        build: ``(repo_root, out_dir) -> None``. Raises on failure; the caller does not interpret
            exit codes.
        blurb: Optional prose for the portal card.
        entry: The page inside the sub-site the portal links to, and the file
            :func:`build_all` requires a successful build to have produced.
        sub_links: Optional ``(label, href)`` pairs rendered under the card.

    """

    slug: str
    title: str
    requires: Requirement
    absent_means: str
    build: Callable[[Path, Path], None]
    blurb: str = ''
    entry: str = 'index.html'
    sub_links: tuple[tuple[str, str], ...] = ()


@dataclass
class BuildReport:
    """What actually happened --- the return value the caller reports from."""

    built: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """The build outcome as text: what was built, then every skip with its reason."""
        parts = [f'built {len(self.built)}: {", ".join(self.built) or "-"}']
        parts.extend(f'SKIPPED {slug} -- {reason}' for slug, reason in self.skipped.items())
        return '\n'.join(parts)


def run(cmd: Sequence[str], *, cwd: Path, timeout: int = DEFAULT_TIMEOUT_S) -> None:
    """Run a build command, failing loudly.

    ``check=True`` is the whole point of this helper existing; see the module docstring's table. Do
    NOT add a ``check`` parameter -- the one implementation that had it set to ``False`` is the
    defect this module was extracted to end.
    """
    subprocess.run(list(cmd), cwd=cwd, check=True, timeout=timeout)


def pdoc_argv(
    modules: Sequence[str],
    out_dir: Path | str,
    *,
    docstring_style: str = 'google',
    edit_url: str | None = None,
    favicon: str | None = None,
    footer_text: str | None = None,
    logo: str | None = None,
    logo_link: str | None = None,
    extra: Sequence[str] = (),
) -> list[str]:
    """The pdoc command line, built around THIS interpreter.

    ``sys.executable -m pdoc``, NOT a bare ``pdoc`` as ``argv[0]``. A bare name resolves only when
    the venv is ACTIVATED, so it worked from an activated shell and on CI (which activates) and
    raised ``FileNotFoundError`` under every invocation that calls the interpreter by absolute path
    -- which is how the family's verify entry point runs, and how an agent runs anything. MEASURED
    2026-09-16 in optimi-lab: ``pdoc.exe`` was present in ``.venv/Scripts/`` the whole time, so the
    failure read as a missing dependency while the dependency was installed. ``-m`` resolves through
    the interpreter already running and cannot disagree with it.
    """
    argv = [sys.executable, '-m', 'pdoc', *modules, '-o', str(out_dir), '-d', docstring_style]
    for flag, value in (
        ('--edit-url', edit_url),
        ('--favicon', favicon),
        ('--footer-text', footer_text),
        ('--logo', logo),
        ('--logo-link', logo_link),
    ):
        if value:
            argv += [flag, value]
    argv += [*PDOC_FLAGS, *extra]
    return argv


def mirror_module_images(root: Path, module: str, out_dir: Path) -> None:
    """Copy in-package images next to the generated pages, preserving their relative path.

    Looks under ``<root>/src/<module>`` first and ``<root>/<module>`` second, so a src-layout and a
    flat-layout package are both found without the caller having to say which it is.
    """
    module_path = root / 'src' / module
    if not module_path.is_dir():
        module_path = root / module
    if not module_path.is_dir():
        return
    for file_path in module_path.rglob('*'):
        if not (file_path.is_file() and file_path.suffix.lower() in IMAGE_SUFFIXES):
            continue
        dest_dir = out_dir / module / file_path.parent.relative_to(module_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / file_path.name
        if not dest.exists() or file_path.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(file_path, dest)


def pdoc_site(root: Path, out_dir: Path, modules: Sequence[str], **options: object) -> None:
    """Render *modules* with pdoc into *out_dir*, then mirror their images.

    Keyword options are :func:`pdoc_argv`'s. Raises ``CalledProcessError`` on a failed pdoc, which
    is the property two of the three predecessors did not have.
    """
    run(pdoc_argv(modules, out_dir, **options), cwd=root)  # type: ignore[arg-type]
    for module in modules:
        mirror_module_images(root, module, out_dir)


def build_all(
    subsites: Sequence[SubSite],
    root: Path,
    out_root: Path,
    *,
    title: str,
    version: str,
    logo: str | None = None,
    favicon: str | None = None,
) -> BuildReport:
    """Build every sub-site whose tool is present, skip and RECORD the rest, write the portal."""
    out_root.mkdir(parents=True, exist_ok=True)
    report = BuildReport()
    for site in subsites:
        if not site.requires.present():
            report.skipped[site.slug] = (
                f'{site.requires.name!r} {site.requires.absent_kind}; without it you lose {site.absent_means}'
            )
            continue
        site_out = out_root / site.slug
        site.build(root, site_out)
        # The portal links to `<slug>/<entry>` for every BUILT sub-site, so a build that does not
        # produce that page ships a dead front-page link. Checked here rather than per-builder: it
        # is a property of the CONTRACT between build_all and render_portal, and a per-builder check
        # would have to be remembered once per row.
        if not (site_out / site.entry).is_file():
            msg = (
                f'{site.slug!r} built but wrote no {site.entry}; the portal links to '
                f'{site.slug}/{site.entry} and would 404'
            )
            raise FileNotFoundError(msg)
        report.built.append(site.slug)

    portal = render_portal(report, subsites, title=title, version=version, logo=logo, favicon=favicon)
    (out_root / 'index.html').write_text(portal, encoding='utf-8')
    return report


def open_site(page: Path) -> None:
    """Open a built page in a browser. NEVER the default anywhere, and mocked in every test.

    A test that opens a browser pops a window on every run, reported twice by this family's user as
    an interruption to normal development -- and it gives no feedback back to the test, since a
    human has to be watching to learn anything from it. So the branch exists, is covered, and every
    suite patches ``lab_commons.dev.docsite.webbrowser.open``; no caller may default it to on.
    """
    webbrowser.open(page.resolve().as_uri())
