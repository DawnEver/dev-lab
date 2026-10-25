"""Tier 2 -- family-shared operational supervision (optional import).

Watching a deployed thing, saying what is wrong with it, and doing something about it: health
probes, resource checks, a remedy chain, alert transport, and the deployment algebra that
validates a candidate before it touches production.

WHY THIS IS TIER 2 AND NOT TIER 1. Tier 1 is what every lab needs to read, log and write a file.
Supervision is a different job that happens to be shared -- a lab with nothing deployed has no use
for it. Import it explicitly::

    from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity

The top level does not import this subpackage, and importing :mod:`dev_lab` never pulls it in.
The direction of dependency is one way: this layer may use lab-commons (``log``, ``paths``, ``proc``,
``liveness``, ``resources``) and lab-commons may not use this.

WHAT IS HERE, and the order is the order of dependency

* :mod:`dev_lab.supervise.verdict` -- what a check returns: anomalies, completions, the remedy
  steps and actions a chain is built from.
* :mod:`dev_lab.supervise.state` -- the one state file a run keeps, and the one key scheme.

A HOST IS NOT ASSUMED. Nothing here reads a clock to decide whether a process is alive, calls
``systemctl`` directly, or knows what a project's directories are called. Process hosting is
reached through an abstract process manager, staleness is asked of the OS, and every path is an
argument with no default.

The modules are reached by name rather than re-exported here, so this package's surface is its
module list and nothing is bound twice.
"""

#: Reached by name, like ``dev_lab.dev.netverb``: no re-export, so no name is bound twice.
__all__: list[str] = []
