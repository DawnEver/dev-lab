"""Run a ``python -m <module>`` hook row IN this interpreter, as the subprocess would have run it.

The runner (:mod:`dev_lab.dev.githooks.runner`) hands a row here when it is a ``python -m`` row not declaring
``isolate``, so one interpreter serves a whole stage: a stage of seven Python rows was eight interpreter starts.

THE CONTRACT IS THE SUBPROCESS'S, piece by piece, so a row cannot tell the difference:

* argv -- ``sys.argv`` is ``[<file>, *args]``; the module runs as ``__main__`` (a package as its ``__main__``
  module), so its ``if __name__ == '__main__'`` block is what runs, exactly as under ``-m``;
* cwd -- the row's, and ``sys.path[0]`` is that cwd, as ``-m`` puts it there;
* env -- ``os.environ`` plus the row's own;
* stdin -- the text the runner pipes (pre-push: git's ref lines), else the inherited one, as a child inherits it;
* output -- stdout and stderr captured together into one stream, as the subprocess runner merges them;
* exit -- ``SystemExit``'s code (``None`` is 0, a message is printed and is 1), and an uncaught exception is
  1 with its traceback, the interpreter's own rule.

Every piece of process state is restored afterwards, whatever the row did, so the next row starts clean.

WHY NOT ``runpy``: it needs the finder's loader to hand it the code (``get_code``), and a meta-path finder may own a
module without that -- pytest's assertion rewriter claims dev_lab's modules under test, and every row then failed
there. The code is read off the finder's loader when it can give it, else compiled from the spec's source file.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import traceback
import types
from collections.abc import Iterator, Mapping
from importlib.abc import InspectLoader
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import override

from lab_commons.log import emit

__all__ = ['run']


@contextlib.contextmanager
def _as_python_m(cwd: Path, module: str, args: list[str], stdin: str | None, env: Mapping[str, str]) -> Iterator[None]:
    """The process state ``python -m`` would start *module* with, restored afterwards."""
    saved_env, saved_cwd = dict(os.environ), Path.cwd()
    saved = sys.argv, sys.path[:], sys.stdin, sys.stdout, sys.stderr
    try:
        os.environ.update(env)
        os.chdir(cwd)
        sys.argv = [module, *args]
        sys.path.insert(0, str(cwd))
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        yield
    finally:
        sys.argv, sys.path[:], sys.stdin, sys.stdout, sys.stderr = saved
        os.chdir(saved_cwd)
        for key in set(os.environ) - set(saved_env):
            del os.environ[key]
        os.environ.update(saved_env)


def _main_spec(module: str) -> ModuleSpec:
    """*module*'s spec, or its ``__main__``'s when it is a package -- what ``python -m`` runs."""
    spec = importlib.util.find_spec(module)
    if spec is None:
        msg = f'No module named {module}'
        raise ModuleNotFoundError(msg, name=module)
    return _main_spec(f'{module}.__main__') if spec.submodule_search_locations is not None else spec


class _Compiled(InspectLoader):
    """A loader holding one code object, so the stdlib's ``exec_module`` runs it in a module's own namespace."""

    def __init__(self, code: types.CodeType) -> None:
        self._code = code

    @override
    def get_code(self, fullname: str) -> types.CodeType:
        return self._code

    @override
    def get_source(self, fullname: str) -> None:
        return None


def _code(spec: ModuleSpec) -> types.CodeType | None:
    """The code ``python -m`` would run: the finder's loader's when it can give it, else compiled from the source."""
    loader = spec.loader
    if isinstance(loader, InspectLoader):
        return loader.get_code(spec.name)
    return SourceFileLoader(spec.name, str(spec.origin)).get_code(spec.name)


def _run_as_main(module: str) -> None:
    """Execute *module* as ``__main__``, the way ``python -m`` does, with ``sys.modules['__main__']`` its namespace."""
    spec = _main_spec(module)
    code = _code(spec)
    if code is None:
        msg = f'No code object available for {spec.name}'
        raise ImportError(msg, name=spec.name)
    main = types.ModuleType('__main__')
    main.__file__, main.__spec__, main.__loader__, main.__package__ = spec.origin, spec, spec.loader, spec.parent
    saved = sys.modules.get('__main__')
    sys.modules['__main__'], sys.argv[0] = main, str(spec.origin)
    try:
        _Compiled(code).exec_module(main)
    finally:
        if saved is not None:
            sys.modules['__main__'] = saved


def _exit_code(module: str) -> int:
    """Run *module* as ``__main__``; its exit code as the interpreter would report it."""
    try:
        _run_as_main(module)
    except SystemExit as stop:
        if stop.code is None or isinstance(stop.code, int):
            return stop.code or 0
        emit(stop.code, err=True)
        return 1
    except Exception:  # noqa: BLE001 -- an uncaught exception is the interpreter's exit 1, with its traceback
        traceback.print_exc()
        return 1
    return 0


def run(module: str, args: list[str], cwd: Path, stdin: str | None, env: Mapping[str, str]) -> tuple[int, str]:
    """Run ``python -m <module> <args>`` in this interpreter: ``(exit code, stdout and stderr together)``."""
    raw = _Kept()
    sink = io.TextIOWrapper(raw, encoding='utf-8', errors='replace', write_through=True)
    with _as_python_m(cwd, module, args, stdin, env):
        sys.stdout = sys.stderr = sink
        code = _exit_code(module)
    if not sink.closed:  # a row that closed its stdout already flushed it (write_through), as a subprocess would
        sink.flush()
    return code, raw.getvalue().decode('utf-8', errors='replace')


class _Kept(io.BytesIO):
    """The capture buffer: a row closing ``sys.stdout`` closes the wrapper, never what it already wrote (#677)."""

    def close(self) -> None:
        """Keep the bytes: the runner reads them after the row returns."""
