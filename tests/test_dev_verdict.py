"""``lab_commons.dev.verdict`` — the algebra, and the promotion it refuses.

THE DECISIVE TEST IS THE ONE THAT TRIES TO LIE: a run that selected three node ids, reported two,
and asks to be called a PASS. Every construction path that could produce that is exercised here,
including the direct one, because a dataclass whose guards live only in its classmethods is a
declaration the constructor does not enforce.
"""

import pytest

from lab_commons.dev.logref import LogRef, UnverifiableLog
from lab_commons.dev.verdict import IncompleteRun, Outcome, Proof, Result, Selector, Verdict


@pytest.fixture
def selector():
    return Selector(spec='gate:integrate/main', node_ids=('t/a.py::test_one', 't/a.py::test_two'))


@pytest.fixture
def proof(selector):
    return Proof.of(selector, selector.node_ids)


@pytest.fixture
def log(tmp_path):
    path = tmp_path / 'run.log'
    path.write_text('collected 2 items\nthe run is happening\n', encoding='utf-8')
    return LogRef.of(path)


class TestTheSelector:
    def test_a_selector_that_expands_to_nothing_is_refused(self):
        """ "Found nothing" must never be the same value as "found nothing wrong"."""
        with pytest.raises(ValueError, match='expands to nothing'):
            Selector(spec='gate', node_ids=())

    def test_a_selector_with_no_spec_is_refused(self):
        with pytest.raises(ValueError, match='no spec'):
            Selector(spec='   ', node_ids=('t/a.py::test_one',))

    def test_the_expansion_is_named_and_sorted(self):
        """A count cannot say WHICH node went missing, so the ids are carried, not their number."""
        built = Selector(spec='x', node_ids=('b', 'a', 'b'))
        assert built.node_ids == ('a', 'b')


class TestTheProof:
    def test_a_covered_run_is_complete(self, selector):
        assert Proof.of(selector, selector.node_ids).complete

    def test_a_silent_node_makes_the_proof_incomplete_and_is_named(self, selector):
        partial = Proof.of(selector, ('t/a.py::test_one',))
        assert not partial.complete
        assert partial.silent == ('t/a.py::test_two',)
        assert 't/a.py::test_two' in partial.refusal

    def test_a_node_that_reported_without_being_selected_makes_it_incomplete(self, selector):
        """A selector that does not describe what ran cannot be re-issued by the reader."""
        wider = Proof.of(selector, (*selector.node_ids, 't/b.py::test_extra'))
        assert not wider.complete
        assert wider.unexpected == ('t/b.py::test_extra',)

    def test_a_truncation_makes_it_incomplete_and_names_itself(self, selector):
        """A flag could not distinguish "the wall" from "collection failed"; a named set can."""
        cut = Proof.of(selector, selector.node_ids, truncated=('wall:30min',))
        assert not cut.complete
        assert cut.shortfall == ('truncated by wall:30min',)

    def test_a_skip_is_silent_not_reported(self, selector):
        """The suite-side spelling of "a known failure is an xfail with its residual, never a skip".

        A skipped test told nobody anything, so it is a hole in the run -- and it belongs in
        ``silent`` because ``reported`` is where the caller puts node ids that produced an outcome.
        """
        with_skip = Proof.of(selector, ('t/a.py::test_one',))
        assert with_skip.silent == ('t/a.py::test_two',)

    def test_a_complete_proof_refuses_nothing(self, proof):
        assert proof.refusal == ''
        assert proof.shortfall == ()


class TestPromotionIsRefusedWithoutProof:
    def test_two_covered_nodes_and_a_clean_proof_is_a_pass(self, proof):
        settled = Result.settled(proof=proof)
        assert settled.outcome is Outcome.PASS
        assert not settled.failures

    def test_SETTLED_DERIVES_FAIL_FROM_THE_FAILURES_NAMED(self, proof):
        settled = Result.settled(proof=proof, failures=('t/a.py::test_two',))
        assert settled.outcome is Outcome.FAIL
        assert settled.failures == ('t/a.py::test_two',)

    def test_a_pass_cannot_be_constructed_without_a_proof(self):
        """THE DECISIVE ONE, through the CONSTRUCTOR rather than the classmethod."""
        with pytest.raises(IncompleteRun, match='requires PROOF of completeness'):
            Result(outcome=Outcome.PASS)

    def test_a_pass_cannot_be_constructed_over_a_partial_proof(self, selector):
        partial = Proof.of(selector, ('t/a.py::test_one',))
        with pytest.raises(IncompleteRun, match='silent'):
            Result.settled(proof=partial)

    def test_a_fail_needs_a_proof_as_much_as_a_pass_does(self):
        """A crash at 30 % does not know a FAIL either -- it knows nothing, which is the point."""
        with pytest.raises(IncompleteRun, match='requires PROOF of completeness'):
            Result(outcome=Outcome.FAIL, failures=('t/a.py::test_one',))

    def test_a_fail_that_names_no_failure_is_refused(self, proof):
        """A red verdict that cannot say which test was red is the refusal a count pin is."""
        with pytest.raises(IncompleteRun, match='names no failure'):
            Result(outcome=Outcome.FAIL, proof=proof)

    def test_a_failure_that_never_reported_is_refused(self, proof):
        with pytest.raises(IncompleteRun, match='never reported'):
            Result.settled(proof=proof, failures=('t/a.py::test_absent',))

    def test_a_pass_carrying_failures_is_refused(self, proof):
        with pytest.raises(IncompleteRun, match='absence of failures'):
            Result(outcome=Outcome.PASS, proof=proof, failures=('t/a.py::test_two',))


class TestTheInconclusiveDefault:
    def test_inconclusive_needs_no_proof(self):
        result = Result.inconclusive('3 collection errors; 0 of 307 node ids reported')
        assert result.outcome is Outcome.INCONCLUSIVE
        assert not result.outcome.settled

    def test_inconclusive_must_say_why(self):
        """ "Cannot say" is only information once it says what it cannot say."""
        with pytest.raises(ValueError, match='no reason'):
            Result.inconclusive('  ')

    def test_inconclusive_may_carry_the_incomplete_proof_as_evidence(self, selector):
        partial = Proof.of(selector, ('t/a.py::test_one',))
        result = Result.inconclusive(partial.refusal, proof=partial)
        assert result.proof is partial

    def test_inconclusive_OVER_A_COMPLETE_PROOF_is_refused(self, proof):
        """The ratchet's other side: a result that will not conclude on sufficient evidence lies."""
        with pytest.raises(IncompleteRun, match='COMPLETE proof'):
            Result.inconclusive('I refuse anyway', proof=proof)

    def test_inconclusive_cannot_carry_failures(self):
        """Named through the CONSTRUCTOR, because the classmethod does not offer the field at all."""
        with pytest.raises(IncompleteRun, match='names 1 failure'):
            Result(outcome=Outcome.INCONCLUSIVE, reason='not sure', failures=('t/a.py::test_one',))

    def test_the_rendered_line_is_the_outcome_and_the_proof_is_elsewhere(self):
        assert Result.inconclusive('interrupted: 0 of 307 reported').render().startswith('inconclusive ')
        assert Result.settled(proof=Proof.of(Selector('x', ('a',)), ('a',))).render() == 'pass'


class TestTheVerdict:
    def test_a_verdict_carries_all_five_and_renders_them(self, selector, proof, log):
        verdict = Verdict(
            tree='sha256:deadbeef',
            env='c0ffee',
            selector=selector,
            result=Result.settled(proof=proof),
            log=log,
        )
        line = verdict.line()
        assert line.startswith('VERDICT result=pass tree=sha256:deadbeef env=c0ffee')
        assert f'log={log.digest}@{log.lines}' in line
        assert line.endswith(f'selector={selector.spec}')

    def test_a_verdict_that_names_no_tree_is_refused(self, selector, proof, log):
        """A different tree means the verdict does not EXIST, so it cannot be filled in later."""
        with pytest.raises(ValueError, match='name the tree'):
            Verdict(tree='  ', env='c0ffee', selector=selector, result=Result.settled(proof=proof), log=log)

    def test_a_verdict_that_names_no_environment_is_refused(self, selector, proof, log):
        with pytest.raises(ValueError, match='name the tree'):
            Verdict(tree='sha256:deadbeef', env='', selector=selector, result=Result.settled(proof=proof), log=log)

    def test_stamping_writes_the_verdict_into_its_own_log(self, selector, proof, log):
        verdict = Verdict(
            tree='sha256:deadbeef', env='c0ffee', selector=selector, result=Result.settled(proof=proof), log=log
        )
        verdict.stamp()
        assert verdict.line() in log.path.read_text(encoding='utf-8').splitlines()

    def test_stamping_refuses_when_the_log_moved_under_the_verdict(self, selector, proof, log):
        """THE MID-RUN MOVE, which is the limitation the ``HEAD + "-dirty"`` stamp was measured to
        have: the lines the verdict read are no longer the lines on disk."""
        verdict = Verdict(
            tree='sha256:deadbeef', env='c0ffee', selector=selector, result=Result.settled(proof=proof), log=log
        )
        log.path.write_text('collected 2 items\nit was still going when I concluded\n', encoding='utf-8')
        with pytest.raises(UnverifiableLog, match='no longer hashes'):
            verdict.stamp()

    def test_stamping_TOLERATES_a_log_that_grew_after_the_reference_was_taken(self, selector, proof, log):
        """The asymmetry that makes stamping possible at all: the verdict line is APPENDED to the
        log it describes, so growth past the covered prefix cannot invalidate it -- and a digest of
        a file containing its own digest would be a fixed point nobody could compute."""
        verdict = Verdict(
            tree='sha256:deadbeef', env='c0ffee', selector=selector, result=Result.settled(proof=proof), log=log
        )
        with log.path.open('a', encoding='utf-8') as handle:
            handle.write('one more line of transcript\n')
        verdict.stamp()
        assert verdict.line() in log.path.read_text(encoding='utf-8')
