"""A CLUSTER PART ASKS ONE LIGHT TASK, never the grant's whole ceiling (dev-lab #586).

The incident: a consumer's ``base`` part asked 309.827 GB -- its grant's ceiling, 317264 MB / 1024 -- on every
PR and was never admitted (13.8-50.2 GB free). Its ``slurm|`` row's peak was the worst file its run's PLAN had not
yet named heavy (209.617 GB, learned mid-run by OOM growth), so ``task_gb`` asked 209.617 x 1.5 = 314.4 GB,
held to the 309.827 GB ceiling. A file whose task asks more than ``HEAVY_SHARE`` of the ceiling is heavy by
definition and runs packed alone, so ONE light task never asks above that bar: the part's claim is held there.
"""

from __future__ import annotations

from lab_commons.compute import learned
from lab_commons.compute.measured import HEAVY_SHARE

from dev_lab.dev.forgedemand import part_demand

REPO = 'https://g/part-ask.git'
CEILING_GB = 317264 / 1024  # the grant's quota, as grantable_gb reads it
PEAK_GB = 214647.8 / 1024  # the stale row's worst "light" file


def _row(peak_gb: float) -> None:
    learned.record_run(REPO, learned.SLURM, (), learned.Run(peak_gb, 1.0, 1.0, files=1.0), ended=learned.EXITED)


def test_the_bare_cluster_ask_is_the_whole_ceiling() -> None:
    """The reproduction: the row as learned asks the ceiling itself, 309.827 GB."""
    _row(PEAK_GB)
    assert round(learned.cluster_demand(REPO, ceiling_gb=CEILING_GB)(frozenset())['mem_gb'], 3) == 309.828


def test_a_part_claims_at_most_one_light_task() -> None:
    _row(PEAK_GB)
    asked = part_demand(REPO, ceiling_gb=CEILING_GB)(frozenset())['mem_gb']
    assert asked == HEAVY_SHARE * CEILING_GB  # 77.457 GB: a light task's most


def test_a_light_row_asks_what_it_measured() -> None:
    """PLANTED CONTROL: a row under the bar keeps its own ask -- the hold never lowers a light need."""
    _row(20.0)
    asked = part_demand(REPO, ceiling_gb=CEILING_GB)(frozenset())['mem_gb']
    assert asked == learned.cluster_demand(REPO, ceiling_gb=CEILING_GB)(frozenset())['mem_gb'] == 30.0


def test_no_ceiling_holds_nothing() -> None:
    """With no ceiling there is no grant to share, so no file is heavy and the ask stands."""
    _row(PEAK_GB)
    assert (
        part_demand(REPO, ceiling_gb=None)(frozenset())['mem_gb'] == learned.cluster_demand(REPO)(frozenset())['mem_gb']
    )
