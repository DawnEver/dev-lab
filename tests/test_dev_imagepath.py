"""IMAGES-BY-ABSOLUTE-PATH: a final message that delivers an image by a relative path is sent back at Stop.

User ruling 2026-11-22: an image delivered to the user is named by its ABSOLUTE path. Planted both ways.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import walls
from dev_lab.dev.disclosure import details_for, problems
from dev_lab.dev.handback import main
from dev_lab.dev.imagepath import IMAGE_SUFFIXES, RULE, refusal, relative_images


@pytest.mark.parametrize(
    ('text', 'found'),
    [
        ('![torque ripple](output/logs/26/11/16/plot/ripple.png)', 'output/logs/26/11/16/plot/ripple.png'),
        ('The figure is at `output/logs/26/11/22/plot/mesh.svg`.', 'output/logs/26/11/22/plot/mesh.svg'),
        ('Saved the plot to ./ripple.PNG for you.', './ripple.PNG'),
        ('See ..\\plots\\flux.jpeg', '..\\plots\\flux.jpeg'),
        ('Figure: mesh.png', 'mesh.png'),
        ('\u56fe\u7247\u5728 output/plot/b-field.webp\u3002', 'output/plot/b-field.webp'),
        ('- ~/plots/a.gif', '~/plots/a.gif'),
    ],
)
def test_an_image_named_by_a_relative_path_is_found(text: str, found: str) -> None:
    assert relative_images(text) == (found,)
    reason = refusal(text)
    assert reason is not None
    assert found in reason


@pytest.mark.parametrize(
    'text',
    [
        '![torque ripple](D:/work/repo/output/logs/26/11/16/plot/ripple.png)',
        r'The figure is at `C:\work\repo\output\plot\mesh.svg`.',
        'Saved to /srv/work/repo/output/logs/26/11/22/plot/ripple.png',
        'Git Bash spells it /d/work/repo/output/plot/ripple.png',
        r'On the share: \\server\share\plots\flux.jpg',
        '![logo](https://example.org/img/logo.png) and file:///D:/work/a.png',
        '![inline](data:image/png;base64,AAAA)',
        'Figures regenerate as *.png; the folder keeps no .svg and no `<name>.png`.',
        'The suffix set is png/jpg/svg; `IMAGE_SUFFIXES` holds .png and .jpeg.',
        'Done: 12 passed. No image delivered.',
        'The report is docs-src/dev/worktrees.md and the data output/x.csv',
        'The template `{stem}.png` is rendered per case under $OUT/plot.png',
    ],
)
def test_an_absolute_path_a_url_a_pattern_or_no_image_is_let_through(text: str) -> None:
    """The other side: a wall that refused these would be routed around."""
    assert relative_images(text) == ()
    assert refusal(text) is None


def test_the_suffixes_are_images_only() -> None:
    """A NAMED SET: a data or document suffix here would refuse every report that cites a file."""
    assert frozenset({'.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}) == IMAGE_SUFFIXES


def test_the_refusal_names_the_path_and_the_door_and_fits_the_budget() -> None:
    reason = refusal('![a](a.png) ![b](plots/b.png) and `c.svg`')
    assert reason is not None
    assert reason.startswith(f'{RULE}: ')
    assert '`a.png`' in reason
    assert '`plots/b.png`' in reason
    assert '(+1 more)' in reason
    assert 'ABSOLUTE path' in reason
    assert problems(reason, 'refusal') == []
    assert reason.splitlines()[-1] == details_for(RULE)


def _run(payload: dict) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(stdin=io.StringIO(json.dumps(payload))) == 0
    return out.getvalue()


def test_the_stop_hook_blocks_a_relative_image_once_and_records_the_wall(tmp_path: Path) -> None:
    """Through the REAL Stop hook: blocked once, an absolute path let through, the wall in the ledger."""
    base = {'cwd': str(tmp_path), 'session_id': 's'}
    assert _run({**base, 'last_assistant_message': 'Figure: `D:/work/repo/output/plot/ripple.png`'}) == ''
    assert not walls.ledger(tmp_path).exists()
    decision = json.loads(_run({**base, 'last_assistant_message': 'Figure: `plot/ripple.png`'}))
    assert decision['decision'] == 'block'
    assert decision['reason'].startswith(f'{RULE}: ')
    [line] = [json.loads(raw) for raw in walls.ledger(tmp_path).read_text(encoding='utf-8').splitlines()]
    assert (line['rule'], line['remedy_present'], line['session']) == (RULE, True, 's')
    assert _run({**base, 'last_assistant_message': 'Figure: `plot/ripple.png`', 'stop_hook_active': True}) == ''


def test_a_handed_command_is_still_the_first_refusal() -> None:
    """One block per stop: the command hand-back keeps its own rule; the image is caught on the next stop."""
    decision = json.loads(_run({'last_assistant_message': 'Please run `git push origin main`; see plot/a.png'}))
    assert decision['reason'].startswith('AGENT-RUNS-ITS-OWN-COMMANDS: ')
