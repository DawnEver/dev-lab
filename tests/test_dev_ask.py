"""The one intake of what a person types (D94): shown as typed, checked before anything is spent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import dev_lab
from dev_lab.dev import ask


def test_a_good_value_is_returned_and_only_its_check_line_is_said() -> None:
    said: list[str] = []
    got = ask.value('key', hint='the console', shape='[0-9a-f]{8}', ask=lambda _p: 'deadbeef\n', say=said.append)
    assert got == 'deadbeef'
    assert said == ['  key: 8 characters, hex, matches the declared shape [0-9a-f]{8}']
    assert 'deadbeef' not in said[0]


@pytest.mark.parametrize(
    ('typed', 'why'),
    [('', 'empty'), ('ab\x16cd', 'right-click'), ('ab cd', 'right-click'), ('abc', 'does not match')],
)
def test_a_bad_value_is_refused_naming_its_cause(typed: str, why: str) -> None:
    """PLANTED CONTROL beside the good value above: the same intake says no."""
    with pytest.raises(ask.AskRefused, match=why):
        ask.value('key', shape='[a-z]{4}' if why == 'does not match' else '', ask=lambda _p: typed)


def test_the_prompt_names_the_value_and_its_hint() -> None:
    prompts: list[str] = []
    ask.value('key', hint='where it lives', ask=lambda p: prompts.append(p) or 'x')
    assert prompts == ['key -- where it lives\nkey: ']


def test_a_code_is_six_digits_given_or_asked() -> None:
    assert ask.code(' 123456 ', what='w') == '123456'
    assert ask.code(None, what='w', ask=lambda _p: '654321\n') == '654321'
    with pytest.raises(ask.AskRefused, match='six digits'):
        ask.code('12345', what='w')
    with pytest.raises(ask.AskRefused, match='right-click'):
        ask.code('12\x163456', what='w')


def test_a_code_asked_with_no_stdin_left_is_refused_by_name_never_a_traceback() -> None:
    """Measured 2026-11-23: a headless agent's ``sshhold open`` died in ``EOFError``. PLANTED CONTROL: one typed."""

    def ended(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(ask.AskRefused, match=r'stdin ended .* pass the code the user gave as --code'):
        ask.code(None, what='w', ask=ended)
    assert ask.code(None, what='w', ask=lambda _p: '123456') == '123456'


_CLAIMS_HIDDEN = re.compile(r'not echoed|without echo|no-echo|input hidden|\(hidden\)', re.IGNORECASE)
_SOURCES = sorted(Path(dev_lab.__file__).parent.rglob('*.py'))


def test_no_intake_claims_its_input_is_hidden() -> None:
    """Names match behaviour: every intake shows what is typed, so none may say it does not.

    PLANTED CONTROL: the pattern catches the wording the intakes used to carry.
    """
    for planted in ('Cluster code (not echoed): ', 'token (input hidden): ', 'prompted without echo'):
        assert _CLAIMS_HIDDEN.search(planted)
    assert _SOURCES
    assert [f.name for f in _SOURCES if _CLAIMS_HIDDEN.search(f.read_text(encoding='utf-8'))] == []
