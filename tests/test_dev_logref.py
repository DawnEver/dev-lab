"""``lab_commons.dev.logref`` — the log a verdict carries, and the reader that re-derives it.

The property under test is not "the digest is computed". It is that a log which MOVED after the
verdict was stamped is refused, while a log that merely grew after it is not -- because the stamped
line is appended to the log it describes, and a digest that transitively covered its own line
would be a fixed point nobody could compute.
"""

import re

import pytest

from lab_commons.dev.logref import _STAMPED, MARKER, Citation, LogRef, UnverifiableLog, stamp_line, verify_log
from lab_commons.dev.verdict import Outcome, Proof, Result, Selector, Verdict

SELECTOR = Selector('gate:integrate/main', ('t/a.py::test_one',))


def _verdict(log: LogRef) -> Verdict:
    return Verdict(
        tree='sha256:deadbeef',
        env='c0ffee',
        selector=SELECTOR,
        result=Result.settled(proof=Proof.of(SELECTOR, SELECTOR.node_ids)),
        log=log,
    )


@pytest.fixture
def log(tmp_path):
    path = tmp_path / 'run.log'
    path.write_text('collected 1 item\nit ran\n', encoding='utf-8')
    return LogRef.of(path)


class TestTheReference:
    def test_a_reference_carries_the_path_the_line_count_and_the_digest(self, log):
        assert log.path.name == 'run.log'
        assert log.lines == 2
        assert log.digest.startswith('sha256:')

    def test_an_empty_log_is_refused(self, tmp_path):
        """An empty log is a run that said nothing, which is not a run that found nothing wrong."""
        empty = tmp_path / 'empty.log'
        empty.write_text('', encoding='utf-8')
        with pytest.raises(UnverifiableLog, match='empty'):
            LogRef.of(empty)

    def test_a_missing_log_is_refused(self, tmp_path):
        with pytest.raises(UnverifiableLog, match='cannot be read'):
            LogRef.of(tmp_path / 'nowhere.log')


class TestTheReader:
    def test_a_stamped_verdict_reads_back(self, log):
        _verdict(log).stamp()
        citation = verify_log(log.path)
        assert isinstance(citation, Citation)
        assert (citation.result, citation.tree, citation.env) == (Outcome.PASS.value, 'sha256:deadbeef', 'c0ffee')
        assert citation.spec == SELECTOR.spec

    def test_a_log_with_no_stamp_is_refused(self, log):
        """A run that produced results wrote no verdict -- which is a state, not a pass."""
        with pytest.raises(UnverifiableLog, match='WROTE NO VERDICT'):
            verify_log(log.path)

    def test_a_log_that_grew_AFTER_the_stamp_still_verifies(self, log):
        """The stamp is appended to the log it describes, so the digest covers the PREFIX only."""
        _verdict(log).stamp()
        with log.path.open('a', encoding='utf-8') as handle:
            handle.write('teardown noise that arrived after the conclusion\n')
        assert verify_log(log.path).result == Outcome.PASS.value

    def test_a_log_whose_EARLIER_lines_were_edited_is_refused(self, log):
        """The evidence a verdict names moved, so the verdict describes a log that no longer exists."""
        _verdict(log).stamp()
        original = log.path.read_text(encoding='utf-8')
        log.path.write_text(original.replace('it ran', 'it probably ran'), encoding='utf-8')
        with pytest.raises(UnverifiableLog, match='has been changed since it was stamped'):
            verify_log(log.path)

    def test_a_stamp_a_text_editor_wrote_from_nothing_is_refused(self, tmp_path):
        """Finding the marker and stopping is believing a line anybody could have typed."""
        forged = tmp_path / 'forged.log'
        forged.write_text(
            'VERDICT result=pass tree=sha256:deadbeef env=c0ffee log=sha256:00@1 selector=gate\n',
            encoding='utf-8',
        )
        with pytest.raises(UnverifiableLog, match='has been changed since it was stamped'):
            verify_log(forged)

    def test_the_last_stamp_wins(self, log):
        """Two verdicts in one log is a re-run; a reader must get the conclusion, not the first try."""
        _verdict(log).stamp()
        first = verify_log(log.path)
        second = LogRef.of(log.path)
        _verdict(second).stamp()
        assert verify_log(log.path).log.lines == first.log.lines + 1


class TestTheGrammarHasONEspelling:
    """The reader and the writer of the stamp are one module's business, and drift is refused.

    ``_STAMPED`` used to spell ``^VERDICT `` as a regex literal while ``Verdict.line`` pasted
    ``MARKER`` into an f-string of its own. Both were correct, and nothing obliged either to follow
    the other -- the shape motronics measured on 2026-08-21, when a consumer still grepping the
    previous stamp matched NOTHING and reported "no verdict" for every commit.
    """

    def test_the_reader_is_built_from_the_marker_the_writer_writes(self):
        """Change ``MARKER`` and the reader follows, because it is not a second spelling of it."""
        assert _STAMPED.pattern.startswith('^' + re.escape(MARKER))
        assert stamp_line(result='pass', tree='t', env='e', digest='sha256:00', lines=1, spec='gate').startswith(MARKER)

    def test_every_field_the_writer_writes_round_trips_through_the_reader(self):
        """Two-sided: the pair accepts what it accepted, field for field and not merely as a match."""
        written = stamp_line(
            result='inconclusive',
            tree='sha256:abc',
            env='c0ffee',
            digest='sha256:def',
            lines=17,
            spec='gate tests/unit/a.py tests/unit/b.py',
        )
        match = _STAMPED.match(written)
        assert match is not None
        assert match.group('result') == 'inconclusive'
        assert match.group('tree') == 'sha256:abc'
        assert match.group('env') == 'c0ffee'
        assert match.group('digest') == 'sha256:def'
        assert match.group('lines') == '17'
        # LAST AND GREEDY: a spec with spaces round-trips with no quoting rule a reader must know.
        assert match.group('spec') == 'gate tests/unit/a.py tests/unit/b.py'

    def test_a_line_that_is_not_a_stamp_is_still_refused(self):
        """The other side of the move: the reader did not widen while acquiring its producer."""
        assert _STAMPED.match('collected 3 items') is None
        assert _STAMPED.match('VERDICT it went fine') is None
        # A stamp that is not at the START of the line is prose QUOTING one, not a conclusion.
        prose = 'see: ' + stamp_line(result='pass', tree='t', env='e', digest='d', lines=1, spec='g')
        assert _STAMPED.match(prose) is None

    def test_the_verdict_object_writes_exactly_what_the_reader_expects(self, log):
        """Reader-next-to-writer stated as a measurement rather than as a comment."""
        verdict = _verdict(log)
        assert _STAMPED.match(verdict.line()) is not None
        assert verdict.line() == stamp_line(
            result='pass',
            tree='sha256:deadbeef',
            env='c0ffee',
            digest=log.digest,
            lines=log.lines,
            spec=SELECTOR.spec,
        )
