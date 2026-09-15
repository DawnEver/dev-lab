"""``RepoProfile`` -- the parameterisation every dev-time mechanism takes.

ADOPTION MUST BE A SUBSTITUTION, NOT A REWRITE, and that decides this module's whole shape. Every
guard in the tree this kit is extracted from reaches its repo through a ``repo_root()`` that is a
thin wrapper over ``lab_commons.paths.resolve_home(app_name)``, and the three consumer repos already
depend on this package. So a profile that RESOLVED the root some other way would force every one of
those call sites to be rewritten, and the cost of attaching would be paid before any mechanism
shipped. :meth:`RepoProfile.repo_root` is therefore the same wrapper, and attaching is one line per
repo: declare the profile.

WHAT A ROOT IS FOR, AND WHY THERE IS NO FALLBACK. ``resolve_home`` answers ``None`` when the package
is installed as a third-party wheel with no home environment set. That is correct for a runtime
primitive and WRONG here: a dev-time guarantee is a statement about a SOURCE TREE, and there is no
tree to guarantee inside ``site-packages``. Falling back to a platform directory would make every
mechanism quietly verify a directory that contains nothing, which is the vacuous-green shape one
level below where it usually appears -- so this RAISES, and the refusal names both remedies.

AND THE ANCHOR, which is the half of "adoption is a substitution" that does NOT hold as designed.
MEASURED 2026-09-15, on this box, with ``lab-commons`` installed non-editable::

    resolve_home('motronics')                                       -> None
    _detect_repo_root(start=<a file in the motronics checkout>)      -> D:\\...\\motronics-studio

``resolve_home``'s auto-detection anchors its upward search on ``lab_commons/paths.py`` -- ITS OWN
file -- so under any install where that file lives in ``site-packages`` it never finds a consumer's
checkout, and it exposes no way to pass a different anchor. The consumer's own ``repo_root()`` was
therefore NOT a thin wrapper: motronics imports the private ``_detect_repo_root`` and calls it with
``start=Path(__file__)``, and that is exactly the workaround :attr:`RepoProfile.anchor` makes
explicit instead of leaving each adopter to rediscover.

EVERY EXEMPTION CARRIES ITS REASON, as a mapping and not a set. An exempt path with no recorded
reason is indistinguishable from a hole somebody widened during a red suite, and the honest-looking
repair when a ratchet disagrees is to widen the exemption. ``{'path': 'why'}'`` makes that repair a
sentence somebody has to write.

EVERY PIN IS A NAMED SET, never a count. ``.claude/rules/rem/integration.md`` records the measured
consequence of the alternative: an integer pin read "mec transient: 2", a merge silently dropped a
restriction, the table delivered one, and the pin was lowered to one with a note explaining why.
The pin was right and the table was wrong, and an integer could not say so.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# `_detect_repo_root` is PRIVATE and is imported here ON PURPOSE. The alternative is a second copy
# of the upward `src/`-checkout search inside this module, and a second definition of where a repo
# root is -- which is the defect this whole subpackage exists to remove -- would be the cost of not
# reaching for it. This is the SAME package's private helper, not another package's, and the public
# `resolve_home` cannot serve the purpose: it anchors on this file's own directory.
from lab_commons.paths import _detect_repo_root, resolve_home

__all__ = ['NotACheckout', 'RepoProfile']

#: The config file a lint config lives in when a repo keeps none of its own. Named rather than
#: inlined because the PLACE a repo declares its lint rules is per-repo data -- one tree in this
#: family has no ``ruff.toml`` at all -- and a mechanism that assumed one path would need a
#: per-repo branch instead of a per-repo value.
DEFAULT_LINT_CONFIG: Final = 'pyproject.toml'


class NotACheckout(RuntimeError):
    """There is no source tree for this profile, so nothing about one can be guaranteed.

    Raised rather than defaulted. A dev-time mechanism pointed at ``site-packages`` verifies
    nothing and reports success, and that report is indistinguishable from a real one -- which is
    precisely the defect class this subpackage exists to remove.
    """


@dataclass(frozen=True, slots=True)
class RepoProfile:
    """One repository, as the data every mechanism reads instead of hardcoding.

    *app_name* is what :func:`lab_commons.paths.resolve_home` keys on (``MOTRONICS_HOME`` and the
    like); *package* is the importable top-level name, which is a DIFFERENT string in general (a
    repo may be named for its subject and its package for its API). Both are required because
    a mechanism that walked the tree would have to guess the second from the first.

    *root* overrides resolution entirely -- for a worktree the environment cannot describe, and for
    a test that plants a tree. When it is given it must EXIST: a profile pointing at a path that is
    not there would make every mechanism below it report on nothing.

    *anchor* is any file INSIDE the source tree -- the repo's own ``conftest.py`` is the natural
    choice -- and it is what the auto-detection cannot supply for itself. See the module docstring
    for the measurement that makes it necessary rather than convenient.
    """

    app_name: str
    package: str
    root: Path | None = None
    anchor: Path | None = None
    exempt: Mapping[str, str] = field(default_factory=dict)
    lint_config: Path | None = None
    pins: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.app_name.strip():
            msg = 'app_name keys the home environment variable and the run directories, so it cannot be empty.'
            raise ValueError(msg)
        if not self.package.isidentifier():
            msg = f'package={self.package!r} is not an importable top-level name.'
            raise ValueError(msg)
        for path, reason in self.exempt.items():
            if not path.strip() or not reason.strip():
                msg = (
                    f'exemption {path!r} has no reason. An exempt path whose reason is not recorded '
                    f'cannot be told from a hole widened to make a red suite green, and it is the '
                    f'exemption that gets widened because it is the cheaper repair.'
                )
                raise ValueError(msg)
        for name in self.pins:
            if not name.strip():
                msg = 'a pin with no name cannot be reported as the thing that disagreed.'
                raise ValueError(msg)

    @property
    def home_env_var(self) -> str:
        """``<APP_NAME>_HOME`` -- the same name :func:`lab_commons.paths.resolve_home` defaults to."""
        return f'{self.app_name.upper()}_HOME'

    def repo_root(self) -> Path:
        """The source tree, by the family's own precedence: **root, then HOME, then anchor**.

        The order is not invented here: the consumer this profile must be substitutable for
        resolves an EXPLICIT home above everything, precisely so a sandbox asking for a
        self-contained tree gets one -- so the environment has to outrank a detected anchor, and a
        declared root has to outrank both.

        Raises:
            NotACheckout: nothing resolved, or a declared *root* is not a directory.

        """
        if self.root is not None:
            resolved = Path(self.root).expanduser().resolve()
            if not resolved.is_dir():
                msg = f'{self.app_name}: declared root {resolved} is not a directory, so no tree can be checked there.'
                raise NotACheckout(msg)
            return resolved
        explicit = os.environ.get(self.home_env_var)
        if explicit:
            return Path(explicit).expanduser().resolve()
        if self.anchor is not None:
            anchored = _detect_repo_root(start=Path(self.anchor))
            if anchored is not None:
                return Path(anchored).resolve()
        detected = resolve_home(self.app_name)
        if detected is None:
            msg = (
                f'{self.app_name}: no source checkout was detected, ${self.home_env_var} is unset, '
                f'and no anchor= was declared, so there is no tree for a dev-time guarantee to '
                f'describe. Point ${self.home_env_var} at the checkout, declare anchor=<a file '
                f'inside it>, or pass root= explicitly -- an installed wheel has no source tree and '
                f'MUST NOT be graded as though it had.'
            )
            raise NotACheckout(msg)
        return Path(detected).expanduser().resolve()

    @property
    def source_root(self) -> Path:
        """``<repo_root>/src`` -- where an importable tree lives, for a mechanism that imports."""
        return self.repo_root() / 'src'

    @property
    def package_root(self) -> Path:
        """``<repo_root>/src/<package>`` -- the package's own files, not the repo's."""
        return self.source_root / self.package

    @property
    def lint_config_path(self) -> Path:
        """Where the lint rules live: *lint_config*, else ``<repo_root>/pyproject.toml``.

        A path and not a flag, because the location is per-repo data: one tree in this family keeps
        its rules in ``ruff.toml``, another in ``pyproject.toml``, and a mechanism that hardcoded
        either would need a branch per repo instead of a value.
        """
        if self.lint_config is not None:
            return (
                Path(self.lint_config) if Path(self.lint_config).is_absolute() else self.repo_root() / self.lint_config
            )
        return self.repo_root() / DEFAULT_LINT_CONFIG

    def relative(self, path: Path) -> str:
        """*path* as a POSIX-style path relative to the repo root -- how an exemption is keyed.

        Posix separators because an exemption list is DATA, and a list written on Windows must
        match on Linux. Raises for a path outside the repo, since a path that cannot be named
        relative to the root is not something an exemption can cover.
        """
        resolved = Path(path).resolve()
        base = self.repo_root()
        if resolved != base and base not in resolved.parents:
            msg = f'{path} is not inside {base}, so it is not something a repo-relative rule can exempt or name.'
            raise ValueError(msg)
        return resolved.relative_to(base).as_posix()

    def is_exempt(self, path: Path) -> bool:
        """Whether *path* sits under a recorded exemption, by PREFIX on the repo-relative path.

        Prefix rather than equality so one entry can cover a directory, and it is stated here
        because the difference decides whether ``'attic/'`` exempts ``attic/x/y.py``.
        """
        relative = self.relative(path)
        return any(relative == prefix or relative.startswith(f'{prefix.rstrip("/")}/') for prefix in self.exempt)

    def exemption_reason(self, path: Path) -> str:
        """Why *path* is exempt, or ``''``. The reason is the exemption's whole value."""
        relative = self.relative(path)
        for prefix, reason in self.exempt.items():
            if relative == prefix or relative.startswith(f'{prefix.rstrip("/")}/'):
                return reason
        return ''

    def pin(self, name: str) -> frozenset[str]:
        """The NAMED SET pinned for *name*, or the empty set -- never a count, never a default.

        An absent pin returns empty rather than raising: a mechanism whose pin has not been
        declared yet should report every row it found, which is what a first attachment needs. The
        asymmetry is deliberate and is why this is not a ``[]`` lookup.
        """
        return self.pins.get(name, frozenset())
