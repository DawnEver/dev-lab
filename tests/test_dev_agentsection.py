"""AGENTS.md IS THE ONE AGENT ENTRY (user ruling 2026-11-24): dev-lab renders the family section between markers.

Each arm plants the refusal beside the acceptance: a hand edit inside the markers, a missing section, doubled
markers, and a workflow citation of a rule the registry does not hold.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agentsection
from dev_lab.dev.agentsection import AGENTS_REL, BEGIN, END, WORKFLOW_RULES, held_section, render_section, splice
from dev_lab.dev.famtests.agentsection import assert_agents_section_is_rendered
from dev_lab.dev.principles import PRINCIPLES
from dev_lab.dev.rules import RULES

ROOT = Path(__file__).resolve().parents[1]


def test_the_section_carries_every_principle_and_every_cited_workflow_rule() -> None:
    """Derived, not restated: each principle id and each cited rule id appears, the rule ids exist."""
    section = render_section()
    assert section.startswith(BEGIN)
    assert section.endswith(END + '\n')
    assert all(f'(`{one.id}`)' in section for one in PRINCIPLES)
    assert set(WORKFLOW_RULES) <= {rule.id for rule in RULES}
    assert all(f'`{rule_id}`:' in section for rule_id in WORKFLOW_RULES)


def test_splice_keeps_the_repo_text_and_is_idempotent() -> None:
    """The repo writes the rest: text before and after the markers survives a re-render byte for byte."""
    held = f'# repo\n\nbefore\n\n{BEGIN}\nold\n{END}\n\nafter\n'
    once = splice(held)
    assert once.startswith('# repo\n\nbefore\n\n')
    assert once.endswith(f'{END}\n\nafter\n')
    assert splice(once) == once
    assert held_section(once) == render_section()


def test_a_planted_hand_edit_inside_the_markers_reds(tmp_path: Path) -> None:
    """PLANTED CONTROL: rendered greens; one changed word inside the markers reds; outside it does not."""
    path = tmp_path / AGENTS_REL
    path.write_text(splice('# repo\n'), encoding='utf-8')
    assert_agents_section_is_rendered(root=tmp_path)
    path.write_text(path.read_text(encoding='utf-8').replace('# repo', '# our repo'), encoding='utf-8')
    assert_agents_section_is_rendered(root=tmp_path)
    path.write_text(path.read_text(encoding='utf-8').replace('## Family workflow', '## Workflow'), encoding='utf-8')
    with pytest.raises(AssertionError, match='hand-edited or is stale'):
        assert_agents_section_is_rendered(root=tmp_path)


@pytest.mark.parametrize(
    ('text', 'needle'),
    [('# repo\n', 'holds no dev-lab family section'), (f'{BEGIN}\n{BEGIN}\n{END}\n', 'exactly one')],
)
def test_a_missing_or_doubled_section_reds(tmp_path: Path, text: str, needle: str) -> None:
    """No section and two BEGIN markers are each refused by name."""
    (tmp_path / AGENTS_REL).write_text(text, encoding='utf-8')
    with pytest.raises(AssertionError, match=needle):
        assert_agents_section_is_rendered(root=tmp_path)


def test_a_citation_of_a_rule_the_registry_lacks_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a workflow list naming a retired or misspelt ID cannot render."""
    monkeypatch.setattr(agentsection, 'WORKFLOW_RULES', (*WORKFLOW_RULES, 'NO-SUCH-RULE'))
    with pytest.raises(KeyError, match='NO-SUCH-RULE'):
        agentsection.render_section()


def test_the_kit_commits_the_render() -> None:
    """THE ADOPTION, run by the kit on the kit."""
    assert_agents_section_is_rendered(root=ROOT)
