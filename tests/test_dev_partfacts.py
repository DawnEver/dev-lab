"""A part's status description always fits the forge's 140 characters and always reads back (dev-lab#1083).

THE PLANTED CONTROL is document-lab #157's own part: eleven parts made ``hands=`` push ``policy=`` past the cap, the
forge cut it, and the part read as "not a settled part" -- so every part stood INCONCLUSIVE and no merge settled.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
from collections import Counter
from typing import TYPE_CHECKING, cast

import pytest
from lab_commons.outcomes import Conclusion

from dev_lab.dev import parthands, platformparts
from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT, CommitStatus
from dev_lab.dev.partfacts import Part, parsed

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

#: document-lab #157's hands, as tests/linux posted them at ecb0027778d9.
_ELEVEN = {
    'base': 1100,
    'cargo': 3,
    'corpus': 140,
    'formula': 8,
    'gpu': 1,
    'macos': 16,
    'ocr': 19,
    'papers': 35,
    'reference': 8,
    'vendor': 3,
    'windows': 19,
}
_URL = 'https://forge.example/records/run-linux.json.gz'


def _linux(**changes: object) -> Part:
    part = Part('linux', 'full', Conclusion.PASS, 16, hands=dict(_ELEVEN), env='728295fd', policy='0123abcd')
    return dataclasses.replace(part, **changes)


def _status(part: Part, description: str | None = None, url: str = _URL) -> CommitStatus:
    return CommitStatus(
        f'tests/{part.platform}', part.state, part.description() if description is None else description, url
    )


def test_an_eleven_part_description_overflowed_the_forge_and_now_fits_and_reads_back() -> None:
    part = _linux()
    hands = ','.join(f'{name}:{count}' for name, count in sorted(_ELEVEN.items()))
    before = f'scope=full ran=16 hands={hands} env=728295fd policy=0123abcd'  # the layout #157 posted
    assert len(before) > DESCRIPTION_LIMIT, 'PLANTED CONTROL: the old layout does not fit'
    assert parsed(_status(part, before[:DESCRIPTION_LIMIT])) is None, 'PLANTED CONTROL: the forge cut never read back'
    said = part.description()
    assert len(said) <= DESCRIPTION_LIMIT
    back = parsed(_status(part))
    assert back is not None
    assert (back.scope, back.ran, back.env, back.policy, back.result) == (
        'full',
        16,
        '728295fd',
        '0123abcd',
        part.result,
    )
    assert len(back.hands) + back.hands_more == len(_ELEVEN), 'a cut is counted, never silent'
    assert back.hands_more > 0
    assert f',+{back.hands_more} ' in said
    assert all(_ELEVEN[name] == count for name, count in back.hands.items())


def test_a_carried_part_with_kept_runs_and_twenty_parts_still_fits_and_reads_back() -> None:
    twenty = {f'part{index:02d}': index + 1 for index in range(20)}
    kept = {'a' * 12: 3, 'b' * 12: 4, 'c' * 12: 5}
    part = _linux(hands=twenty, kept=kept, carried='d' * 12)
    said = part.description()
    assert len(said) <= DESCRIPTION_LIMIT
    back = parsed(_status(part))
    assert back is not None
    assert (back.carried, back.env, back.policy) == ('d' * 12, '728295fd', '0123abcd')
    assert len(back.hands) + back.hands_more == 20
    assert len(back.kept) + back.kept_more == 3


def test_a_part_that_fits_is_said_whole() -> None:
    part = _linux(hands={'jmag': 3})
    assert part.description() == 'scope=full ran=16 hands=jmag:3 env=728295fd policy=0123abcd'
    back = parsed(_status(part))
    assert back is not None
    assert (back.hands, back.hands_more) == ({'jmag': 3}, 0)


def test_a_status_posted_before_the_cut_marker_reads_as_it_did() -> None:
    """The grammar only GAINED ``+N``: every part already on the forge is a description of today's grammar."""
    old = (
        'scope=full ran=2 hands=jmag:3 env=0123abcd policy=89abcdef kept=aaaaaaaaaaaa:4 '
        'carried from bbbbbbbbbbbb: docs-only'
    )
    back = parsed(CommitStatus('tests/femm', 'success', old, ''))
    assert back is not None
    assert (back.hands, back.env, back.policy, back.kept, back.carried) == (
        {'jmag': 3},
        '0123abcd',
        '89abcdef',
        {'a' * 12: 4},
        'b' * 12,
    )


@pytest.mark.parametrize(
    'description',
    [
        'scope=full ran=2',  # no hands
        'scope=full ran=2 hands=- hands=-',  # a field twice
        'scope=full ran=2 hands=- color=red',  # a field no part says
        'scope=full ran=2 env=0123abcd hands=-',  # fields out of the one order a part is said in
        'scope=full ran=two hands=-',  # a value off its grammar
        'claim machine=G',
    ],
)
def test_a_description_that_is_not_a_part_reads_as_none(description: str) -> None:
    assert parsed(CommitStatus('tests/base', 'success', description, '')) is None


def test_a_description_that_would_not_read_back_is_refused_before_it_is_posted() -> None:
    """THE SEAM: :meth:`Part.description` reads its own answer back. PLANTED CONTROL: the same part, well-formed."""
    with pytest.raises(ValueError, match='cannot be said in 140 characters that read back'):
        _linux(scope='not one word').description()
    assert parsed(_status(_linux())) is not None


def test_a_cut_part_said_again_keeps_the_count_it_could_not_hold() -> None:
    """A carried re-post starts from the PARSED part (forgecarry): its ``+N`` survives, never a smaller list."""
    back = parsed(_status(_linux()))
    assert back is not None
    again = parsed(_status(back, dataclasses.replace(back, carried='e' * 12).description()))
    assert again is not None
    assert len(again.hands) + again.hands_more == len(_ELEVEN)


class _Records:
    """A forge client that serves one run record by url, counting downloads."""

    def __init__(self, records: dict[str, bytes]) -> None:
        self.records, self.downloads = records, Counter[str]()

    def download(self, url: str) -> bytes:
        self.downloads[url] += 1
        if url not in self.records:
            raise OSError(url)
        return self.records[url]


def _record(handed: dict[str, int]) -> bytes:
    owners = {f'tests/test_{name}.py::t{index}': name for name, count in handed.items() for index in range(count)}
    return gzip.compress(json.dumps({'platform': 'linux', 'handed': owners}).encode('utf-8'))


def test_a_cut_hands_is_completed_from_the_record_its_status_links_and_every_part_is_derived() -> None:
    """THE DISCOVERY, whole: a part no description could name is still wanted, read off ``handed`` once."""
    parthands._HANDS_READ.clear()
    records = _Records({_URL: _record(_ELEVEN)})
    client = cast('Client', records)  # the fake serves download only
    statuses = [_status(_linux())]
    cut = platformparts.derived(statuses)
    assert set(cut) < {'linux', *_ELEVEN}, 'PLANTED CONTROL: the cut description alone names fewer parts'
    whole = parthands.complete_hands(client, statuses)
    assert set(platformparts.derived(whole)) == {'linux', *_ELEVEN}
    parthands.complete_hands(client, statuses)
    assert records.downloads[_URL] == 1, 'a record never changes: it is read once'


def test_a_cut_no_record_completed_is_named_and_never_passes() -> None:
    """Never a silently smaller set: the standing says which part's list was cut and how to complete it."""
    parthands._HANDS_READ.clear()
    unread = parthands.complete_hands(cast('Client', _Records({})), [_status(_linux())])
    read = platformparts.standing(unread, head='h', waived=frozenset(_ELEVEN) - {'base'})
    assert read.result is not Conclusion.PASS
    assert any('tests/linux hands' in problem and 'parthands' in problem for problem in read.problems)
