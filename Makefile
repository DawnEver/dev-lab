.DEFAULT_GOAL := all

# THE SINGLE VERIFY ENTRY POINT. CI calls `verify` and nothing else; a human calls `verify` before
# pushing. A new check belongs in a target here, NEVER inline as a step in a workflow -- the two
# drift the moment they are written twice, and CI then fails on something a local run could not
# have caught.
#
# THE TARGET HEADERS BELOW ARE THE FAMILY BASE (`lab_commons.dev._famconfig_rows.MAKEFILE_BASE`),
# and the base is REQUIRED rather than RENDERED: the names are the family's, every recipe is this
# repo's. Until 2026-09-18 this file held six targets and the kit's own base demanded nine -- the
# repo that publishes the contract was the one repo not meeting it, which is the shape every other
# finding in this family has. `verify` is the exception that proves the mode: its recipe IS the
# base's, because `lab_commons.dev.verify` takes no argument naming a tree and so is portable by
# construction, and this repo shipping it while running a hand-written chain instead was the same
# defect one layer in.

.PHONY: install
install:
	uv pip install -e .

.PHONY: install-dev
install-dev:
	uv pip install -e ".[dev]"
	python -m lab_commons.dev.hook_install --install

.PHONY: lint
lint:
	python -m ruff check .

.PHONY: fmt-check
fmt-check:
	python -m ruff format --check .

.PHONY: fmt
fmt:
	python -m ruff check . --fix
	python -m ruff format .

.PHONY: test
test:
	python -m pytest

.PHONY: test-parallel
test-parallel:
	python -m pytest -n auto

.PHONY: adoption
adoption:
	python -m pytest tests/test_the_adoption_accounts_for_every_rule.py -v

.PHONY: verify
verify:
	python -m lab_commons.dev.verify

.PHONY: clean
clean:
	python -c "import shutil; [shutil.rmtree(d, True) for d in ('dist', 'build', '.verify')]"
	python -c "import shutil; [shutil.rmtree(d, True) for d in ('.pytest_cache', '.ruff_cache')]"
	python -c "import pathlib, shutil; [shutil.rmtree(d, True) for d in pathlib.Path().rglob('__pycache__')]"

.PHONY: all
all: verify
