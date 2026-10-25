"""The one configuration a supervision target has, and the one way it is overridden.

ONE FILE, PLUS THE ENVIRONMENT. The predecessor carried two files -- ``config.yaml`` for structure
and a gitignored ``config.local.yaml`` for secrets -- merged in a four-step precedence. The second
file bought nothing the environment does not: a secret is something a deployment injects, and
systemd already has ``EnvironmentFile=`` for exactly that, with the file mode to match. So the
precedence here is two steps, and there is one file a reader has to open::

    environment  >  <config>.toml  >  the defaults below

TOML rather than YAML, which drops a dependency rather than adding one -- ``rtoml`` is already
tier 1 and the family's configs are already TOML. A YAML parser for one file was a second
serialisation format to keep working.

WHY A MISSING FILE IS NOT AN ERROR. A daemon that refuses to start because its config has not been
written yet cannot report that fact, which is the one thing it is for. It starts on the defaults
instead and supervises nothing -- and the loop refuses to call a run with no components enabled
`healthy`, because a scan that read nothing is not a clean scan. The refusal lives where it can be
reported, not where it would be silent.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Final

from lab_commons.file_io import read_toml

__all__ = ['DEFAULTS', 'ENV_LEVEL', 'ENV_PREFIX', 'load_config']

#: A LIST-VALUED KEY IS SET AS A COMMA-SEPARATED LIST, because that is the only way an
#: environment variable can carry one.
#: The prefix an override variable carries. A project that runs two supervisors sets a different
#: one rather than sharing a namespace.
ENV_PREFIX: Final = 'SUPERVISE_'

#: The whole default configuration. Every key a module reads must appear here, so the shape of a
#: config is one place rather than the union of every reader's assumptions.
DEFAULTS: Final[dict[str, Any]] = {
    'target': {'name': 'unknown'},
    'cycle': {
        'interval': 300,
        'check_timeout': 60,
        'quiet_after': 3,
        #: The ceiling every remedy command runs under. A remedy is a one-off process on a small
        #: host -- a reinstall, a build, a migration -- and it is exactly the work that forks and
        #: takes the box with it. Bounded by the kernel rather than by a number in a comment.
        'command_ceiling': '400M',
    },
    'state': {'file': ''},
    #: WHAT THIS SUPERVISOR IS, for the one thing a running process cannot notice by itself. Add
    #: the files that define it -- the unit that starts it and the config it was handed -- and the
    #: daemon re-takes their signature every cycle, so a deployment that changed either makes it
    #: exit and let the manager start one that reads what is there now. The kit's own version is
    #: always part of the signature and is not listed here, because no config can know it.
    #:
    #: AN EMPTY LIST IS NOT THE SAFE DEFAULT. It leaves the kit-version half working, which covers
    #: the upgrade case and not the unit case, and it is the unit case that ships a supervisor
    #: enforcing settings nobody reviewed.
    'daemon': {'definition': []},
    'alerts': {
        'suppress_after_identical': 3,
        'cooldown': 600,
        'email': {
            'enabled': False,
            'method': 'smtp',
            'host': 'localhost',
            'port': 25,
            'use_tls': False,
            'username': '',
            'password': '',
            'api_key': '',
            'sender': '',
            'recipients': [],
            'subject_prefix': '[supervise]',
        },
        'telegram': {'enabled': False, 'token': '', 'chat': ''},
        'webhook': {'enabled': False, 'url': '', 'headers': {}},
    },
    'process': {'manager': 'systemd'},
    'remedies': {},
    'components': {},
}


def _deep_merge(base: MutableMapping[str, Any], override: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Merge *override* into *base*, recursing into mappings.

    Args:
        base: the mapping to merge into, mutated in place.
        override: the mapping whose values win.

    Returns:
        *base*, for chaining.

    """
    for key, value in override.items():
        current = base.get(key)
        if isinstance(current, MutableMapping) and isinstance(value, Mapping):
            _deep_merge(current, value)
        else:
            base[key] = value
    return base


def _cast(text: str, like: object = None) -> object:
    """Coerce an environment string to the type the default at that key already has.

    A LIST IS SPLIT ON COMMAS, and that is not a convenience: an environment variable can only hold
    a string, so without this a list-valued key can never be set from one. ``recipients`` would
    arrive as the string ``"a@x, b@y"`` and the mail path -- which joins it -- would iterate its
    CHARACTERS and address the message to ``a, @, x, ...``. A value that looks set and is garbage is
    worse than one that is missing, because nothing reports it.

    Args:
        text: the raw value.
        like: the default at this key, whose type decides the reading. ``None`` when the key is new.

    Returns:
        A list when the default is one, a bool for ``true``/``false``, an int or float when the text
        is exactly one, and the text otherwise.

    """
    if isinstance(like, list):
        return [piece.strip() for piece in text.split(',') if piece.strip()]
    lowered = text.strip().lower()
    if lowered in ('true', 'false'):
        return lowered == 'true'
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


#: What separates one level of a nested key from the next in an override variable name. A DOUBLE
#: underscore, because a single one is already IN the key names -- ``check_timeout``,
#: ``suppress_after_identical``, ``subject_prefix``. The predecessor split on the single
#: underscore, so ``WATCH_CYCLE_CHECK_TIMEOUT`` addressed ``cycle.check.timeout``: a key that does
#: not exist, silently created beside the one that does, leaving the real setting untouched and the
#: override looking applied. A separator that can appear inside a key is not a separator.
ENV_LEVEL: Final = '__'


def _env_override(config: MutableMapping[str, Any], environ: Mapping[str, str], prefix: str) -> None:
    """Fold every ``<prefix>...`` variable into *config* as a nested key path.

    Args:
        config: the mapping to mutate.
        environ: the environment to read.
        prefix: the variable prefix, e.g. ``SUPERVISE_``.

    """
    for name, raw in environ.items():
        if not name.startswith(prefix):
            continue
        parts = [piece for piece in name[len(prefix) :].lower().split(ENV_LEVEL) if piece]
        if not parts:
            continue
        node: MutableMapping[str, Any] = config
        default: Any = DEFAULTS
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, MutableMapping):
                child = {}
                node[part] = child
            node = child
            default = default.get(part, {}) if isinstance(default, Mapping) else {}
        node[parts[-1]] = _cast(raw, default.get(parts[-1]) if isinstance(default, Mapping) else None)


def load_config(path: Path, *, environ: Mapping[str, str] | None = None, prefix: str = ENV_PREFIX) -> dict[str, Any]:
    """Read the configuration for one target.

    Args:
        path: the TOML file. No default -- where a target's config lives is the adopting
            project's fact, and a default would silently read another project's.
        environ: the environment to fold in. Defaults to ``os.environ``; a test passes its own
            rather than mutating the process's.
        prefix: the override variable prefix.

    Returns:
        The merged configuration, always carrying every key in :data:`DEFAULTS`.

    Raises:
        ValueError: the file exists and is not parseable as TOML.

    """
    config: dict[str, Any] = _deep_merge(_copy_defaults(), {})
    if path.is_file():
        loaded = read_toml(path)
        if not isinstance(loaded, dict):
            msg = f'{path} does not hold a TOML table at its top level'
            raise ValueError(msg)
        _deep_merge(config, loaded)
    config['_config_path'] = str(path)
    _env_override(config, os.environ if environ is None else environ, prefix)
    _validate(config)
    return config


def _copy_defaults() -> dict[str, Any]:
    """Return a deep copy of :data:`DEFAULTS`, so a load cannot mutate the module constant.

    ``copy.deepcopy`` rather than :func:`_deep_merge`: the merge assigns a non-mapping value by
    reference, so it would hand out ``DEFAULTS``' OWN list objects. A caller appending a recipient
    would then have appended it for every later load in the process -- a live config mutated by a
    run that has already finished.

    Returns:
        A fresh nested structure with the default values.

    """
    return deepcopy(DEFAULTS)


def _validate(config: Mapping[str, Any]) -> None:
    """Refuse a configuration whose parts contradict each other.

    Only cross-field contradictions are checked here -- a single field's absence is the reader's
    business, but two fields that cannot both be honoured is a configuration that would run and
    silently do the wrong thing.

    Args:
        config: the merged configuration.

    Raises:
        ValueError: a contradiction was found.

    """
    email = config.get('alerts', {}).get('email', {})
    if email.get('enabled') and email.get('method') == 'smtp' and not email.get('sender'):
        msg = 'alerts.email is enabled over smtp but names no sender; a relay will refuse it'
        raise ValueError(msg)
    if email.get('enabled') and not email.get('recipients'):
        msg = 'alerts.email is enabled but names no recipients, so every alert would be dropped'
        raise ValueError(msg)
    telegram = config.get('alerts', {}).get('telegram', {})
    if telegram.get('enabled') and not (telegram.get('token') and telegram.get('chat')):
        msg = 'alerts.telegram is enabled but is missing its token or its chat'
        raise ValueError(msg)
    webhook = config.get('alerts', {}).get('webhook', {})
    if webhook.get('enabled') and not str(webhook.get('url', '')).startswith('https://'):
        msg = (
            'alerts.webhook is enabled over a URL that is not https; its configured headers carry '
            'a secret and the channel will not send them in clear'
        )
        raise ValueError(msg)
    interval = config.get('cycle', {}).get('interval', 0)
    if not isinstance(interval, int) or interval <= 0:
        msg = f'cycle.interval must be a positive integer, not {interval!r}'
        raise ValueError(msg)
