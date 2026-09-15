"""``lab_commons.dev.logref`` — the log a verdict carries, and the reader that re-derives it.

The property under test is not "the digest is computed". It is that a log which MOVED after the
verdict was stamped is refused, while a log that merely grew after it is not -- because the stamped
line is appended to the log it describes, and a digest that transitively covered its own line
would be a fixed point nobody could compute.
"""

import pytest

from lab_commons.dev.logref import Citation, LogRef, UnverifiableLog, verify_log
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
