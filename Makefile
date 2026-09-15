.DEFAULT_GOAL := verify

# THE SINGLE VERIFY ENTRY POINT. CI calls `verify` and nothing else; a human calls `verify` before
# pushing. A new check belongs in a target here, NEVER inline as a step in a workflow -- the two
# drift the moment they are written twice, and CI then fails on something a local run could not
# have caught.

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

.PHONY: adoption
adoption:
	python -m pytest tests/test_the_adoption_accounts_for_every_rule.py -v

.PHONY: verify
verify: lint fmt-check test
