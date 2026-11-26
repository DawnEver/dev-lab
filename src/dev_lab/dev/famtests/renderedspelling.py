"""US-SPELLING-IS-CHECKED over what dev-lab RENDERS: a render that would red a consumer's typos reds here first.

The family's renderers write files into every consumer, and every consumer's verify runs
:mod:`dev_lab.dev.spelling` over them. A rendered file that fails it reds every consumer at once and for a cause
none of them owns (2026-11-26: the deny registry's regex fragments read as misspellings). So the renders are
checked HERE, at their source, under the one family config, at the path each lands on in a consumer -- the
path is what the config's excludes match.

THE CONTROL: :func:`assert_a_planted_render_is_convicted` plants a British spelling at a rendered path that is
checked and asserts the same reader reds, so a green is not a reader that stopped reading.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path

from dev_lab.dev import agentsection, autodoors, codexdeny, spelling
from dev_lab.dev.hook_adoption import HookAdoption, render

__all__ = ['assert_a_planted_render_is_convicted', 'assert_rendered_files_pass_spelling', 'rendered_files']


def rendered_files() -> dict[str, str]:
    """Every family render that needs no consumer tree, by the path it lands on in a consumer."""
    return {
        '.claude/hooks/deny-rules.json': render(HookAdoption(app_name='family')),
        codexdeny.CODEX_DENY_REL: codexdeny.codex_deny_rules(),
        autodoors.CODEX_RULES_REL: autodoors.codex_rules(),
        'AGENTS.md': agentsection.render_section(),
    }


def _findings(files: Mapping[str, str], at: Path) -> tuple[int, str]:
    for rel, text in files.items():
        path = at / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    out = io.StringIO()
    return spelling.check_files(at, tuple(files), handle=out), out.getvalue()


def assert_rendered_files_pass_spelling(at: Path) -> None:
    """Raise unless every :func:`rendered_files` render passes the family spelling check, written under *at*."""
    status, out = _findings(rendered_files(), at)
    if status != spelling.CLEAN:
        msg = (
            f'a family render fails the family spelling check, so every consumer reds on it:\n{out}\n'
            f'Fix the renderer`s text, or -- for machine data that is not prose -- exclude its path in '
            f'{spelling.CONFIG.name} (dev_lab.dev.spelling.CONFIG); never a per-repo ignore.'
        )
        raise AssertionError(msg)


def assert_a_planted_render_is_convicted(at: Path) -> None:
    """THE CONTROL: a British spelling planted into a checked render reds the same reader."""
    planted = {'AGENTS.md': agentsection.render_section() + '\nThe behaviour of the colour.\n'}  # spelling-ignore-line
    status, out = _findings(planted, at)
    if status != spelling.FOUND:
        msg = f'a planted British spelling in a rendered AGENTS.md read {status} ({out!r}), not FOUND'
        raise AssertionError(msg)
