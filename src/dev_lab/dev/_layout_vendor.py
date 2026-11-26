"""The VENDOR-JOB half of :mod:`dev_lab.dev.layout`: an agent never hand-writes a named program's job tree.

A program in ``vendor_jobs`` of ``layout.toml`` (D95, 2026-11-25) owns ``output/logs/<yy>/<mm>/<dd>/vendor/<program>/``
(:meth:`~dev_lab.dev._layout_table.Layout.in_vendor_job`): it reads the model and driver scripts its driver emits
there (``.py`` for AEDT, ``.lua`` for FEMM, ``.m`` for MATLAB) beside its own files, so the layout scan leaves the
tree unjudged. The write hook sees an AGENT's tool call and never the driver writing at run time, so it cannot
admit per writer; it refuses every agent Write/Edit there, whatever the suffix, naming the driver as the door.

Split out of :mod:`dev_lab.dev.layout` (MODULE-SIZE-ALARM) along its own seam: that module judges a tree against the
rows; this one owns the one refusal the scan's vendor exemption leaves to the write hook.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev._layout_table import RULE_ID, declared_at
from dev_lab.dev.codeplace import LAYOUT_FILE
from dev_lab.dev.disclosure import details_for

__all__ = ['refuse_vendor_job', 'vendor_refusal']


def refuse_vendor_job(path: Path) -> str | None:
    """The refusal of an agent's write of *path* into a named program's job tree; ``None`` for any other path.

    The write hook asks it BEFORE OUTPUT-HOLDS-NO-CODE, so an emitted script's refusal names its driver as the door;
    :func:`dev_lab.dev.layout.refuse_layout` gives the same refusal through :func:`vendor_refusal`.
    """
    if 'vendor' not in Path(path).parts or (declared := declared_at(path)) is None:
        return None
    root, layout, rel = declared
    return vendor_refusal(root, rel) if layout.in_vendor_job(rel) else None


def vendor_refusal(root: Path, rel: str) -> str:
    """Why an agent never writes *rel* (inside a declared job tree of the checkout *root*), and the door."""
    return (
        f'{RULE_ID}: {rel} -- a vendor job (output/logs/<yy>/<mm>/<dd>/vendor/<program>/, named in vendor_jobs '
        f"of {root.name}/{LAYOUT_FILE}) is emitted by the program's driver at run time; an agent never "
        f"hand-writes a vendor job. Change the program's driver (or its template) and rerun the job.\n"
        f'{details_for(RULE_ID)}'
    )
