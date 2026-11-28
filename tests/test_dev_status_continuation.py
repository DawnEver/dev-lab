"""A STATUS DESCRIPTION PAST ITS FORGE'S LIMIT CONTINUES -- ``dev_lab.dev.forgestatus`` against a REAL loopback.

THE DEFECT (user, 2026-11-27): GitHub cuts a commit status ``description`` at 140 characters. A document-lab
part names 11 handed parts in ``hands=``, so its ``env=``/``policy=`` fell off, :func:`parsed` matched nothing and
every reader read an all-green part as undetermined -- silently. Measured on the forge: ``tests/base`` posted
``scope=full ran=1100 hands=cargo:3,corpus:140,...,windows:19 env=d6f8975a`` (exactly 140, no policy).

Evidence is what the server RECORDED: every description sent fits the backend's declared limit, and the
statuses read back parse to the very part posted. PLANTED: the forge's own cut and a missing or stale
continuation are each NAMED by the reader, never read as a part.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest
from _forge_fake import Loopback, Recorder, answer, client, serve

from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgestatus import CommitStatus, status_history, status_list, status_post
from dev_lab.dev.partfacts import RESULT, Part, parsed
from dev_lab.dev.platformparts import parts_of
from dev_lab.dev.statuscontinuation import DESCRIPTION_LIMIT, FORGE_CUT, continued

_SHA = 'a' * 40
_GITHUB = Forge('github.com', 'o', 'r')
_GITEA = Forge('forge.example.org', 'o', 'r')

#: document-lab's parts on 2026-11-27, then padded to 30 need-sets.
_DOCUMENT_LAB = (
    'cargo',
    'corpus',
    'formula',
    'gpu',
    'linux',
    'macos',
    'ocr',
    'papers',
    'reference',
    'vendor',
    'windows',
)


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _part(classes: int) -> Part:
    names = [*_DOCUMENT_LAB, *(f'gpu+linux+r{n}' for n in range(classes - len(_DOCUMENT_LAB)))][:classes]
    return Part(
        platform='base',
        scope='full',
        result=RESULT['success'],
        ran=13188,
        hands={name: 1000 + index for index, name in enumerate(names)},
        kept={'0123456789ab': 900},
        env='3036290d',
        policy='c87a6ce1',
    )


def test_the_backends_declare_their_limits_and_the_tightest_is_the_one_status_budget() -> None:
    assert (GITHUB.description_limit, GITEA.description_limit) == (140, None)
    assert (FORGE_CUT, DESCRIPTION_LIMIT) == (140, 139)  # one short: a whole text never reads as cut


@pytest.mark.parametrize('classes', [11, 30])
def test_a_part_of_many_classes_posts_within_githubs_limit_and_reads_back_exactly(server, classes) -> None:
    part = _part(classes)
    description = part.description()
    assert len(description) > DESCRIPTION_LIMIT  # the planted precondition: it does NOT fit one status
    answer('POST', f'/repos/o/r/statuses/{_SHA}', (201, {'context': 'tests/base', 'state': 'success'}))
    status_post(client(_GITHUB, Loopback(server)), _SHA, context='tests/base', state='success', description=description)
    sent = [one['body'] for one in Recorder.received]
    assert all(len(body['description']) < FORGE_CUT for body in sent)
    assert [body['context'] for body in sent][-1] == 'tests/base'  # the head is posted LAST
    listed = [{**body, 'id': index + 1} for index, body in enumerate(sent)]
    answer('GET', f'/repos/o/r/commits/{_SHA}/statuses', (200, listed))
    (only,) = status_list(client(_GITHUB, Loopback(server)), _SHA)
    assert only.context == 'tests/base'  # no continuation surfaces as a context of its own
    assert parsed(only) == part


def test_gitea_stores_any_length_so_nothing_continues(server) -> None:
    description = _part(30).description()
    answer('POST', f'/api/v1/repos/o/r/statuses/{_SHA}', (201, {'context': 'tests/base', 'status': 'success'}))
    status_post(client(_GITEA, Loopback(server)), _SHA, context='tests/base', state='success', description=description)
    assert [one['body']['description'] for one in Recorder.received] == [description]


def test_every_piece_continued_builds_fits_and_joins_back() -> None:
    for length in range(FORGE_CUT - 3, 20 * FORGE_CUT):
        text = ''.join(chr(ord('a') + n % 26) for n in range(length))
        head, rest = continued(text, FORGE_CUT)
        assert all(len(piece) < FORGE_CUT for piece in (head, *rest)), length
        if length <= DESCRIPTION_LIMIT:
            assert (head, rest) == (text, ())
        else:
            assert head.rsplit(' >>', 1)[0] + ''.join(rest) == text, length


def _read(server: ThreadingHTTPServer, listed: list[dict[str, Any]]) -> tuple[CommitStatus, ...]:
    answer('GET', f'/repos/o/r/commits/{_SHA}/statuses', (200, listed))
    return status_list(client(_GITHUB, Loopback(server)), _SHA)


def test_a_description_the_forge_cut_is_named_never_read_as_a_part(server) -> None:
    """PLANTED: what GitHub stored for document-lab's ``tests/base`` before this fix."""
    cut = _part(11).description()[:FORGE_CUT]
    statuses = _read(server, [{'id': 1, 'context': 'tests/base', 'state': 'success', 'description': cut}])
    parts, problems = parts_of(statuses)
    assert parts == {}
    assert len(problems) == 1
    assert 'cut at 140 characters' in problems[0]


def _posted(server: ThreadingHTTPServer, description: str) -> list[dict[str, Any]]:
    answer('POST', f'/repos/o/r/statuses/{_SHA}', (201, {'context': 'tests/base', 'state': 'success'}))
    status_post(client(_GITHUB, Loopback(server)), _SHA, context='tests/base', state='success', description=description)
    posted = [{**one['body'], 'id': index + 1} for index, one in enumerate(Recorder.received)]
    Recorder.received.clear()
    return posted


def test_a_head_whose_continuation_is_missing_is_named(server) -> None:
    posted = _posted(server, _part(11).description())
    head = [one for one in posted if one['context'] == 'tests/base']
    _, problems = parts_of(_read(server, head))
    assert len(problems) == 1
    assert 'continuation status(es)' in problems[0]


def test_a_head_never_joins_a_continuation_of_another_post(server) -> None:
    """PLANTED: a newer post's continuation landed, its head not yet -- the older head stays whole and true."""
    old = _posted(server, _part(11).description())
    new = _posted(server, _part(30).description())
    renumbered = [{**one, 'id': one['id'] + len(old)} for one in new if one['context'] != 'tests/base']
    (only,) = _read(server, [*old, *renumbered])
    assert parsed(only) == _part(11)  # the newer continuations came AFTER this head: never read into it
    history = status_history(client(_GITHUB, Loopback(server)), _SHA)
    assert [parsed(one) for one in history] == [_part(11)]


def test_a_stale_continuation_fails_the_digest_and_is_named(server) -> None:
    old = _posted(server, _part(11).description())
    new = _posted(server, _part(12).description())
    head = next(one for one in old if one['context'] == 'tests/base')
    stale = [{**one, 'id': 1} for one in new if one['context'] != 'tests/base']
    _, problems = parts_of(_read(server, [*stale, {**head, 'id': 99}]))
    assert len(problems) == 1
    assert 'do not match digest' in problems[0]


def test_a_whole_text_of_exactly_the_limit_continues_on_every_backend_so_it_is_never_read_as_cut(server) -> None:
    """PLANTED: 140 characters is what a cut leaves, so a whole text of that length is never posted alone."""
    part = _part(11)
    whole = part.description()
    text = whole[:FORGE_CUT]
    assert len(text) == FORGE_CUT
    answer('POST', f'/api/v1/repos/o/r/statuses/{_SHA}', (201, {'context': 'tests/base', 'status': 'success'}))
    status_post(client(_GITEA, Loopback(server)), _SHA, context='tests/base', state='success', description=text)
    sent = [one['body'] for one in Recorder.received]
    assert len(sent) == 2
    assert all(len(body['description']) < FORGE_CUT for body in sent)
    listed = [{**body, 'status': body['state'], 'id': index + 1} for index, body in enumerate(sent)]
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (200, listed))
    (only,) = status_list(client(_GITEA, Loopback(server)), _SHA)
    assert only.description == text


def test_a_free_text_cut_to_the_one_status_limit_is_one_status_on_github(server) -> None:
    """PLANTED (CI 46070439811): a refusal cut to the old 140 posted a head and a ``#1``; cut to the limit it is one."""
    text = ('refused: ' * 40)[:DESCRIPTION_LIMIT]
    answer('POST', f'/repos/o/r/statuses/{_SHA}', (201, {'context': 'tests/base', 'state': 'error'}))
    status_post(client(_GITHUB, Loopback(server)), _SHA, context='tests/base', state='error', description=text)
    assert [one['body']['description'] for one in Recorder.received] == [text]
