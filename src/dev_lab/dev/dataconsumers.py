"""A data repo's pull request is judged by its CONSUMERS' tests, run at the PR head.

A data repo (:mod:`dev_lab.dev.datadeps`) has no tests of its own worth the name: what makes a recipe good is
what its consumer's code does with it. So a PR on the data repo is judged by each consumer's tests with that
consumer's pin replaced, for that one run, by the PR head.

ONE SOURCE. Nothing declares "who consumes me": a consumer is a family member (``[repos]``) whose
``[tool.dev_lab.data.<name>]`` row names the data repo's url. The consumer's tree is never edited -- the PR head
reaches it only through :data:`datadeps.OVERRIDE` in the run's environment, which :func:`datadeps.relock` never
reads, so it can never become the consumer's own pin.

:func:`runs` is the plan: one :class:`ConsumerRun` per consumer, posted as ``tests/consumer:<member>`` on the PR.
A data PR no member consumes posts nothing. ``python -m dev_lab.dev.dataconsumers plan --url U --head SHA``
prints it for this machine's ``[repos]``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.home import repos
from lab_commons.log import emit

from dev_lab.dev import datadeps

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ['CONTEXT', 'ConsumerRun', 'main', 'runs', 'same_repo']

#: The status a consumer's run posts on the data PR, ``tests/consumer:<member>``.
CONTEXT: Final = 'tests/consumer:'
_VERIFY: Final = ('python', '-m', 'dev_lab.dev.verify')


@dataclass(frozen=True)
class ConsumerRun:
    """One consumer's run for a data PR: where, with what environment, which command, posted under which status."""

    context: str
    root: Path
    env: Mapping[str, str]
    argv: tuple[str, ...]


def same_repo(left: str, right: str) -> bool:
    """Whether two urls name one repo: case, a trailing slash and ``.git`` aside."""

    def bare(url: str) -> str:
        return url.strip().rstrip('/').removesuffix('.git').lower()

    return bare(left) == bare(right)


def runs(url: str, head: str, members: Mapping[str, Path]) -> tuple[ConsumerRun, ...]:
    """The consumer runs a PR at *head* on the data repo at *url* needs, derived from *members*' declarations."""
    planned = []
    for member, root in sorted(members.items()):
        for dep in datadeps.declared(root, overridden=False):
            if same_repo(dep.url, url):
                argv = (*_VERIFY, '--', *dep.tests) if dep.tests else _VERIFY
                planned.append(ConsumerRun(f'{CONTEXT}{member}', root, {datadeps.OVERRIDE: f'{dep.name}={head}'}, argv))
    return tuple(planned)


def main(argv: Sequence[str] | None = None) -> int:
    """``plan --url U --head SHA``: print the consumer runs of a data PR for this machine's ``[repos]``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.dataconsumers', description=__doc__.split('\n', 1)[0])
    parser.add_argument('verb', choices=('plan',))
    parser.add_argument('--url', required=True)
    parser.add_argument('--head', required=True)
    args = parser.parse_args(argv)
    try:
        planned = runs(args.url, args.head, repos())
    except datadeps.DataRefused as refused:
        emit(f'[data] refused: {refused}', err=True)
        return 2
    if not planned:
        emit('[data] no family member consumes this repo; nothing to post')
    for run in planned:
        env = ' '.join(f'{key}={value}' for key, value in run.env.items())
        emit(f'{run.context}: in {run.root}: {env} {" ".join(run.argv)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
