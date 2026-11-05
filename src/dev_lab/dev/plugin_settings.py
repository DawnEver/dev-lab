"""PLUGINS NO FAMILY SESSION RUNS, declared once and written into every repo's ``.claude/settings.json``.

USER RULING 2026-11-05: the forge's PR review is the ONE review, so the ``sharp-review`` plugin's
Stop-hook review must not fire in daily development. The plugin has no per-project off switch and the
user-global settings enable it; a project ``enabledPlugins`` entry overrides the user's, so each repo's
committed settings turn it off. :func:`dev_lab.dev.agent_guard.wire_settings` writes the entries, and
the guard's wiring check reads a file that enables one -- or omits it -- as STALE.
"""

from __future__ import annotations

import json
from typing import Any, Final

__all__ = ['DISABLED_PLUGINS', 'disable_plugins', 'live_disabled_plugins']

#: Every plugin a family repo's settings must set to ``false``.
DISABLED_PLUGINS: Final = ('sharp-review@cc-market',)


def live_disabled_plugins(settings: dict[str, Any]) -> list[str]:
    """The :data:`DISABLED_PLUGINS` *settings* does not set ``false``. Absent counts: the user's file enables it."""
    declared = settings.get('enabledPlugins')
    declared = declared if isinstance(declared, dict) else {}
    return [plugin for plugin in DISABLED_PLUGINS if declared.get(plugin) is not False]


def disable_plugins(settings: dict[str, Any]) -> dict[str, Any]:
    """A copy of *settings* with every :data:`DISABLED_PLUGINS` set ``false``; a repo's own entries are kept."""
    out = json.loads(json.dumps(settings))
    if not isinstance(out.get('enabledPlugins'), dict):
        out['enabledPlugins'] = {}
    out['enabledPlugins'].update(dict.fromkeys(DISABLED_PLUGINS, False))
    return out
