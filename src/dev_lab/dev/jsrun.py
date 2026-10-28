"""THE FAMILY'S ONE JS TEST RUNTIME: a pinned Node from the lock, never whatever ``node`` the host has.

TEST/DEV TOOLING ONLY (user ruling 2026-10-28): the engine is the ``test`` extra of dev-lab, which a
consumer takes in its DEV extra as ``dev-lab[test]``; no runtime dependency or product extra carries it,
and :func:`dev_lab.dev.famtests.hostnode.assert_engine_is_dev_only` refuses one that does.

A test that runs client JavaScript -- or drives the agent-guard engine (:mod:`dev_lab.dev.agenthooks`) --
needs an engine, and ``shutil.which('node')`` makes that an
UNDECLARED HOST DEPENDENCY: the cluster verdict host carries no Node (user ruling 2026-10-28: it must
not install one), so the test reds there for a reason the lock never stated. The engine is instead
``nodejs-wheel-binaries``, so every family repo that installs ``dev-lab[test]`` gets the same Node
binary from its own lock on every host the wheel covers (Windows, manylinux_2_28, musllinux, macOS).

WHY NODE AND NOT AN EMBEDDED ENGINE. Measured 2026-10-28 against wdg-lab's review-report JS and its
tests and dev-lab's own hook engines: the guard engine needs ``require``/``fs``/``process``, the review
code decodes payloads with ``DecompressionStream``, ``Response``/``Blob``,
``TextDecoder`` and ``atob``, waits on ``setTimeout``, and its harnesses report through
``process.exitCode`` and ``console.error``. QuickJS and a bare V8 isolate (``mini-racer``) provide
none of those, so either would mean shimming a web platform in the test -- a second runtime to keep
honest. Node is the smallest engine that meets the need as it stands.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Final

from lab_commons.launch import run

__all__ = [
    'DEFAULT_TIMEOUT_S',
    'ENGINE_DISTRIBUTIONS',
    'ENGINE_PACKAGE',
    'JS_EXTRA',
    'JsFailed',
    'NoEngine',
    'node_path',
    'run_js',
]

#: The distributions that ship the engine; none may appear outside a dev extra (``famtests.hostnode``).
ENGINE_DISTRIBUTIONS: Final = frozenset({'nodejs-wheel-binaries', 'nodejs-wheel'})

#: The import package the engine distribution installs.
ENGINE_PACKAGE: Final = 'nodejs_wheel'

#: dev-lab's extra that carries the engine; a consumer requires ``dev-lab[test]`` in its dev extra.
JS_EXTRA: Final = 'test'

#: The wall a JS test program gets before it is killed, in seconds.
DEFAULT_TIMEOUT_S: Final = 60.0


class NoEngine(LookupError):
    """The engine is not installed: this environment lacks dev-lab's ``test`` extra."""


class JsFailed(AssertionError):
    """A JS program exited nonzero; the message carries its exit code and stderr."""


def node_path() -> Path:
    """The locked Node binary inside the installed ``nodejs_wheel`` package.

    Raises:
        NoEngine: the ``test`` extra is not installed here.

    """
    # LOCATED, NOT IMPORTED: the engine is a dev extra, never a declared base dependency, so this
    # layer names it only as a spec (tests/test_dev_gate.py reads the import statements).
    spec = importlib.util.find_spec(ENGINE_PACKAGE)
    if spec is None or spec.origin is None:
        msg = f'no JS engine: install dev-lab[{JS_EXTRA}] in the dev extra (never a runtime dependency)'
        raise NoEngine(msg)
    root = Path(spec.origin).parent
    return root / 'node.exe' if os.name == 'nt' else root / 'bin' / 'node'


def run_js(program: str, *flags: str, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """Run *program* (fed on stdin) under the locked Node with *flags*; return its stdout.

    Raises:
        JsFailed: the program exited nonzero (a throw, a rejected top-level promise, or a set
            ``process.exitCode``).

    """
    result = run(
        [str(node_path()), *flags],
        input=program,
        encoding='utf-8',
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode:
        msg = f'JS program failed (exit {result.returncode}):\n{result.stderr}{result.stdout}'
        raise JsFailed(msg)
    return result.stdout
