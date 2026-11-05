"""WHAT A ROLE SERVES: its repos, and the ONE credential each of their forges names -- refused at load when it lies.

Break-glass, the probe and the judge each declare their own ``repos`` (clone or web URLs on any forge) and, per forge
host, a token file; the judge may name a GitHub App instead (``[ops.judge.apps]``, :mod:`dev_lab.dev.forgeapp`).
An empty set, one repository twice, a forge with no credential, a credential no repo uses, a forge credentialed twice
and a malformed App are refused here, once, for every role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dev_lab.dev.forge import forge_of_url

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['served', 'served_by']


def served(repos: tuple[str, ...], tokens: Mapping[str, str], where: str) -> None:
    """Refuse an empty repo set, one identity twice, a forge with no token, or a token no repo uses."""
    if not repos:
        msg = f'{where} serves no repo: declare repos = ["https://<forge>/<owner>/<name>.git", ...]'
        raise ValueError(msg)
    identities = [forge_of_url(url).identity for url in repos]
    if len(set(identities)) != len(identities):
        msg = f'{where} repos name one repository twice: {identities}'
        raise ValueError(msg)
    hosts = {forge_of_url(url).host for url in repos}
    if untokened := sorted(hosts - set(tokens)):
        msg = f'{where} forge {", ".join(untokened)} names no token: add it to {where[:-1]}.tokens]'
        raise ValueError(msg)
    if unused := sorted(set(tokens) - hosts):
        msg = f'{where[:-1]}.tokens] {", ".join(unused)} serves no repo in {where} repos'
        raise ValueError(msg)


def _app_entry(app: Mapping[str, Any]) -> bool:
    """Whether *app* is exactly ``{app_id = <positive integer>, key_file = "<path>"}``."""
    app_id, key_file = app.get('app_id'), app.get('key_file')
    shaped = set(app) == {'app_id', 'key_file'} and isinstance(key_file, str) and bool(key_file)
    return shaped and type(app_id) is int and app_id > 0


def served_by(
    repos: tuple[str, ...], tokens: Mapping[str, str], apps: Mapping[str, Mapping[str, Any]], where: str
) -> None:
    """:func:`served` over a token OR an App per forge: a forge named by both, or an App not ``{app_id, key_file}``."""
    if twice := sorted(set(tokens) & set(apps)):
        msg = f'{where} forge {", ".join(twice)} names both a token and an app: one identity per forge'
        raise ValueError(msg)
    for host, app in apps.items():
        if not _app_entry(app):
            msg = f'{where[:-1]}.apps] {host} must be {{app_id = <positive integer>, key_file = "<path>"}}: {app}'
            raise ValueError(msg)
    served(repos, {**tokens, **dict.fromkeys(apps, '')}, where)
