"""``lab_commons.dev.profile`` — the parameterisation, and the substitution it has to be.

The root-resolution tests matter more than the rest because they are about the ONLY thing that
decides whether adopting this kit costs a line or a rewrite: every guard in a consumer tree reaches
its repo through a ``repo_root()``, and a profile that resolved the root differently would force
every one of those call sites to move.
"""

from pathlib import Path

import pytest

from lab_commons.dev import profile as profile_module
from lab_commons.dev.profile import DEFAULT_LINT_CONFIG, NotACheckout, RepoProfile


@pytest.fixture
def checkout(tmp_path) -> Path:
    """A plantable source checkout: ``<root>/src/<pkg>/`` plus a pyproject beside it."""
    (tmp_path / 'src' / 'widget').mkdir(parents=True)
    (tmp_path / 'src' / 'widget' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'src' / 'widget' / 'core.py').write_text('A = 1\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "widget"\n', encoding='utf-8')
    (tmp_path / 'attic').mkdir()
    (tmp_path / 'attic' / 'old.py').write_text('# archived\n', encoding='utf-8')
    (tmp_path / 'attic2').mkdir()
    (tmp_path / 'attic2' / 'live.py').write_text('# NOT archived\n', encoding='utf-8')
    return tmp_path


def _profile(checkout, **overrides: object) -> RepoProfile:
    fields = {
        'app_name': 'widget',
        'package': 'widget',
        'root': checkout,
        'exempt': {'attic': 'archived code from a migrated repo; read-only by invariant'},
        'pins': {'suppressions': frozenset({'src/widget/core.py'})},
    }
    fields.update(overrides)
    return RepoProfile(**fields)


class TestResolvingTheRoot:
    def test_a_declared_root_is_the_root(self, checkout) -> None:
        assert _profile(checkout).repo_root() == checkout.resolve()

    def test_a_declared_root_that_is_not_a_directory_is_refused(self, checkout) -> None:
        with pytest.raises(NotACheckout, match='not a directory'):
            _profile(checkout, root=checkout / 'nowhere').repo_root()

    def test_the_home_environment_variable_outranks_a_detected_anchor(self, checkout, tmp_path, monkeypatch) -> None:
        """A sandbox that asks for a self-contained tree by NAME must get that tree."""
        elsewhere = tmp_path.parent / f'{tmp_path.name}-sandbox'
        (elsewhere / 'src' / 'widget').mkdir(parents=True)
        anchor = checkout / 'src' / 'widget' / '__init__.py'
        declared = _profile(checkout, root=None, anchor=anchor)
        monkeypatch.setenv('WIDGET_HOME', str(elsewhere))
        assert declared.repo_root() == elsewhere.resolve()

    def test_an_anchor_inside_the_checkout_finds_the_checkout(self, checkout, monkeypatch) -> None:
        """THE SUBSTITUTION, and the measurement that makes the anchor necessary at all.

        ``resolve_home`` anchors its upward search on ``lab_commons/paths.py`` -- its own file --
        so under a non-editable install it never finds a consumer's tree and exposes no way to pass
        a different anchor. This is how a consumer attaches without rewriting its ``repo_root()``.
        """
        monkeypatch.delenv('WIDGET_HOME', raising=False)
        declared = _profile(checkout, root=None, anchor=checkout / 'src' / 'widget' / '__init__.py')
        assert declared.repo_root() == checkout.resolve()

    def test_with_no_root_no_home_and_no_anchor_it_refuses_rather_than_guessing(self, monkeypatch, mocker) -> None:
        """An installed wheel has no source tree, and grading one as though it had is the defect."""
        monkeypatch.delenv('WIDGET_HOME', raising=False)
        mocker.patch.object(profile_module, 'resolve_home', return_value=None)
        bare = RepoProfile(app_name='widget', package='widget')
        with pytest.raises(NotACheckout) as refusal:
            bare.repo_root()
        assert 'WIDGET_HOME' in str(refusal.value)
        assert 'anchor=' in str(refusal.value)

    def test_the_derived_trees_hang_off_the_root(self, checkout) -> None:
        declared = _profile(checkout)
        assert declared.source_root == checkout.resolve() / 'src'
        assert declared.package_root == checkout.resolve() / 'src' / 'widget'
        assert (declared.package_root / 'core.py').is_file()

    def test_the_home_variable_is_named_after_the_app(self) -> None:
        assert RepoProfile(app_name='optimi_lab', package='optimi_lab').home_env_var == 'OPTIMI_LAB_HOME'


class TestTheLintConfigLocation:
    def test_it_defaults_to_the_pyproject_beside_the_source(self, checkout) -> None:
        assert _profile(checkout).lint_config_path == checkout.resolve() / DEFAULT_LINT_CONFIG

    def test_a_relative_override_resolves_under_the_root(self, checkout) -> None:
        (checkout / 'ruff.toml').write_text('line-length = 120\n', encoding='utf-8')
        assert _profile(checkout, lint_config='ruff.toml').lint_config_path == checkout.resolve() / 'ruff.toml'

    def test_an_absolute_override_is_honoured(self, checkout, tmp_path) -> None:
        other = tmp_path.parent / 'shared-ruff.toml'
        assert _profile(checkout, lint_config=other).lint_config_path == other


class TestExemptions:
    def test_an_exempt_directory_covers_everything_under_it(self, checkout) -> None:
        declared = _profile(checkout)
        assert declared.is_exempt(checkout / 'attic' / 'old.py')

    def test_a_path_that_merely_STARTS_with_an_exempt_name_is_not_exempt(self, checkout) -> None:
        """Prefix on the repo-relative path, not on its text: ``attic`` must not cover ``attic2``."""
        declared = _profile(checkout)
        assert not declared.is_exempt(checkout / 'attic2' / 'live.py')

    def test_an_exemption_carries_its_reason(self, checkout) -> None:
        declared = _profile(checkout)
        assert 'read-only by invariant' in declared.exemption_reason(checkout / 'attic' / 'old.py')
        assert declared.exemption_reason(checkout / 'attic2' / 'live.py') == ''

    def test_an_exemption_with_no_reason_is_refused(self, checkout) -> None:
        """A hole whose reason is unrecorded cannot be told from one widened to make a suite green."""
        with pytest.raises(ValueError, match='has no reason'):
            _profile(checkout, exempt={'attic': '  '})

    def test_a_path_outside_the_repo_cannot_be_named_relative_to_it(self, checkout, tmp_path) -> None:
        with pytest.raises(ValueError, match='not inside'):
            _profile(checkout).relative(tmp_path.parent / 'elsewhere.py')


class TestPinsAndNames:
    def test_a_pin_is_a_named_set_not_a_count(self, checkout) -> None:
        """An integer cannot say WHICH row moved.

        The honest repair when it disagrees is to edit the digit -- which has already happened once
        in this family.
        """
        assert _profile(checkout).pin('suppressions') == frozenset({'src/widget/core.py'})

    def test_an_undeclared_pin_reports_nothing_rather_than_raising(self, checkout) -> None:
        """A first attachment reports every row it found; there is no pin to compare against yet."""
        assert _profile(checkout).pin('never-declared') == frozenset()

    def test_a_pin_with_no_name_is_refused(self, checkout) -> None:
        with pytest.raises(ValueError, match='no name'):
            _profile(checkout, pins={'  ': frozenset({'x'})})

    def test_a_package_that_is_not_importable_is_refused(self, checkout) -> None:
        with pytest.raises(ValueError, match='not an importable'):
            _profile(checkout, package='src/widget')

    def test_an_app_name_that_is_empty_is_refused(self, checkout) -> None:
        with pytest.raises(ValueError, match='cannot be empty'):
            _profile(checkout, app_name=' ')
