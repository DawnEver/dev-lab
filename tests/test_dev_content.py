"""``lab_commons.dev.content`` — a content address over the MEASURED paths.

Every test here is about what the address is BLIND to as much as what it sees: it must move when a
measured byte moves, and must not move when anything else does. The second half is what makes it
usable as a verdict's ``tree=`` -- an address that changed for an unmeasured reason would refuse
every cipher on the box, and the honest repair for that is to widen it until it means nothing.
"""

from pathlib import Path

import pytest

from lab_commons.dev.content import content_address, file_digest


@pytest.fixture
def tree(tmp_path) -> Path:
    """A plantable checkout: two measured modules, one unmeasured doc, one cached artefact."""
    (tmp_path / 'src' / 'pkg').mkdir(parents=True)
    (tmp_path / 'src' / 'pkg' / '__init__.py').write_text('A = 1\n', encoding='utf-8')
    (tmp_path / 'src' / 'pkg' / 'core.py').write_text('B = 2\n', encoding='utf-8')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'notes.md').write_text('prose\n', encoding='utf-8')
    (tmp_path / 'src' / 'pkg' / '__pycache__').mkdir()
    (tmp_path / 'src' / 'pkg' / '__pycache__' / 'core.cpython-312.pyc').write_bytes(b'stale bytecode')
    return tmp_path


MEASURED = ('src/pkg',)


class TestWhatTheAddressSees:
    def test_the_address_moves_when_a_measured_file_changes(self, tree) -> None:
        before = content_address(tree, MEASURED)
        (tree / 'src' / 'pkg' / 'core.py').write_text('B = 3\n', encoding='utf-8')
        assert content_address(tree, MEASURED) != before

    def test_the_address_moves_when_a_measured_file_is_DELETED(self, tree) -> None:
        """A walk that only sums what it finds reads a deleted measured file as an unchanged tree."""
        before = content_address(tree, MEASURED)
        (tree / 'src' / 'pkg' / 'core.py').unlink()
        assert content_address(tree, MEASURED) != before

    def test_a_path_that_is_not_there_is_recorded_rather_than_skipped(self, tree) -> None:
        """``absent`` is what a vanished measured path contributes, and it is not a digest."""
        present = content_address(tree, ('src/pkg/core.py',))
        absent = content_address(tree, ('src/pkg/gone.py',))
        assert present != absent
        (tree / 'src' / 'pkg' / 'gone.py').write_text('', encoding='utf-8')
        assert content_address(tree, ('src/pkg/gone.py',)) != absent

    def test_the_path_is_part_of_the_record_not_only_the_bytes(self, tree) -> None:
        """Moving a definition to another module is a change even when no byte of it moved."""
        (tree / 'src' / 'pkg' / 'core.py').write_bytes((tree / 'src' / 'pkg' / '__init__.py').read_bytes())
        assert content_address(tree, ('src/pkg/core.py',)) != content_address(tree, ('src/pkg/__init__.py',))


class TestWhatTheAddressIsBlindTo:
    def test_an_unmeasured_file_does_not_move_the_address(self, tree) -> None:
        before = content_address(tree, MEASURED)
        (tree / 'docs' / 'notes.md').write_text('rewritten prose\n', encoding='utf-8')
        (tree / 'docs' / 'new.md').write_text('a new page\n', encoding='utf-8')
        assert content_address(tree, MEASURED) == before

    def test_an_interpreter_cache_inside_a_measured_dir_does_not_move_the_address(self, tree) -> None:
        """The suite rewrites ``__pycache__`` by RUNNING.

        Measuring it would make an unchanged tree address differently for the sole reason that it
        was measured.
        """
        before = content_address(tree, MEASURED)
        (tree / 'src' / 'pkg' / '__pycache__' / 'core.cpython-312.pyc').write_bytes(b'recompiled')
        (tree / 'src' / 'pkg' / '__pycache__' / 'other.cpython-312.pyc').write_bytes(b'new')
        assert content_address(tree, MEASURED) == before

    def test_the_address_is_a_fact_about_LAYOUT_not_about_where_the_tree_sits(self, tree, tmp_path) -> None:
        """Two checkouts of the same content must address identically, whatever their absolute path."""
        other = tmp_path.parent / f'{tmp_path.name}-elsewhere'
        (other / 'src' / 'pkg').mkdir(parents=True)
        (other / 'src' / 'pkg' / '__init__.py').write_text('A = 1\n', encoding='utf-8')
        (other / 'src' / 'pkg' / 'core.py').write_text('B = 2\n', encoding='utf-8')
        assert content_address(other, MEASURED) == content_address(tree, MEASURED)


class TestTheAddressIsStable:
    def test_target_order_cannot_move_it(self, tree) -> None:
        targets = ('src/pkg', 'docs/notes.md')
        assert content_address(tree, targets) == content_address(tree, tuple(reversed(targets)))

    def test_naming_a_directory_and_naming_its_files_agree(self, tree) -> None:
        assert content_address(tree, ('src/pkg',)) == content_address(tree, ('src/pkg/__init__.py', 'src/pkg/core.py'))

    def test_the_same_tree_twice_gives_the_same_address(self, tree) -> None:
        assert content_address(tree, MEASURED) == content_address(tree, MEASURED)

    def test_the_algorithm_rides_in_the_address(self, tree) -> None:
        """A stored address computed under another algorithm must read as DIFFERENT, not as a mismatch."""
        assert content_address(tree, MEASURED).startswith('sha256:')
        assert content_address(tree, MEASURED, algorithm='sha1').startswith('sha1:')
        assert content_address(tree, MEASURED) != content_address(tree, MEASURED, algorithm='sha1')


class TestTheRefusals:
    def test_a_target_outside_the_root_is_refused(self, tree, tmp_path) -> None:
        """An absolute address is a fact about one machine, and no second reader could check it."""
        outside = tmp_path.parent / 'elsewhere.py'
        outside.write_text('x = 1\n', encoding='utf-8')
        with pytest.raises(ValueError, match='not under'):
            content_address(tree, (outside,))

    def test_addressing_nothing_is_refused_rather_than_folded_into_a_constant(self, tree) -> None:
        """Saying "the tree did not change" and saying "I measured no tree" are different answers."""
        with pytest.raises(ValueError, match='nothing to address'):
            content_address(tree, ())

    def test_a_zero_length_address_is_refused(self, tree) -> None:
        with pytest.raises(ValueError, match='floor'):
            content_address(tree, MEASURED, length=0)

    def test_file_digest_is_the_content(self, tree) -> None:
        first = file_digest(tree / 'src' / 'pkg' / 'core.py')
        (tree / 'src' / 'pkg' / 'core.py').write_text('B = 2 \n', encoding='utf-8')
        assert file_digest(tree / 'src' / 'pkg' / 'core.py') != first
