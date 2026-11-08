"""``dev_lab.ops.disk``: ``disk`` only reads; ``clean`` frees only what regenerates, never what Gitea cannot rebuild."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.ops.disk import CACHES, PROTECTED, clean, measure, refuse_protected


def _fake(ran: list[list[str]]):  # noqa: ANN202
    def runner(argv: Sequence[str]) -> tuple[int, str]:
        ran.append(list(argv))
        if argv[:2] == ['df', '--output=target']:
            return 0, 'Mounted on\n/'
        if argv[0] == 'du':
            return 0, '1048576\t/var/lib/docker\n2097152\t/var/log\nbad\tline'
        return 0, ''

    return runner


def _gitea(tmp_path: Path) -> Path:
    data = tmp_path / 'data'
    for name in (*CACHES, *PROTECTED[:3]):
        (data / name / 'sub').mkdir(parents=True)
        (data / name / 'sub' / 'f.bin').write_bytes(b'x' * 1024)
    return data


def test_disk_only_reads(capsys: pytest.CaptureFixture[str]) -> None:
    ran: list[list[str]] = []
    assert measure('/var/lib/gitea/data', runner=_fake(ran), has_docker=True) == 0
    verbs = {argv[0] for argv in ran}
    assert verbs == {'df', 'du', 'journalctl', 'docker'}
    assert ['journalctl', '--disk-usage'] in ran
    assert ['docker', 'system', 'df'] in ran
    out = capsys.readouterr().out
    assert out.index('/var/log') < out.index('/var/lib/docker'), 'largest first'


def test_clean_empties_the_caches_and_never_touches_what_gitea_cannot_rebuild(tmp_path: Path) -> None:
    data = _gitea(tmp_path)
    ran: list[list[str]] = []
    assert clean(str(data), 300, runner=_fake(ran), has_docker=True) == 0
    for name in CACHES:
        assert (data / name).is_dir(), 'the cache directory stays'
        assert list((data / name).iterdir()) == [], 'its contents go'
    for name in PROTECTED[:3]:
        assert (data / name / 'sub' / 'f.bin').is_file(), f'{name} is never touched'
    assert ['journalctl', '--vacuum-size=300M'] in ran
    assert ['apt-get', 'clean'] in ran
    assert ['docker', 'builder', 'prune', '-f'] in ran
    assert ['docker', 'image', 'prune', '-f'] in ran
    assert not any('-a' in argv or '--all' in argv for argv in ran), 'only dangling images, never all'
    assert [argv[0] for argv in ran].count('df') == 2, 'df before and after'


@pytest.mark.parametrize(
    'cache',
    ['gitea-repositories', 'lfs/objects', '.', '../elsewhere', 'tmp/../attachments'],
)
def test_a_cache_that_overlaps_protected_data_or_leaves_the_data_dir_is_refused(tmp_path: Path, cache: str) -> None:
    """PLANTED CONTROLS: each would delete what Gitea cannot regenerate, or something outside its data."""
    data = _gitea(tmp_path)
    assert refuse_protected(data, data / cache) is not None


def test_the_declared_caches_are_admitted(tmp_path: Path) -> None:
    data = _gitea(tmp_path)
    assert all(refuse_protected(data, data / name) is None for name in CACHES)
