"""Labels by name: resolved to an id on Gitea (which drops an unknown name silently), created on demand."""

from __future__ import annotations

import pytest

from dev_lab.dev._forgebackends import GITEA, GITHUB, Backend
from dev_lab.dev.forgelabels import LabelMissing, add_label, ensure_labels


class _Client:
    def __init__(self, backend: Backend, labels: dict[str, int]) -> None:
        self.backend, self.repo, self.labels, self.calls = backend, '/r', dict(labels), []

    def call(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        self.calls.append((method, path, body))
        if method == 'GET':
            return [{'name': n, 'id': i} for n, i in self.labels.items()] if 'page=1' in path else []
        if path == '/r/labels':
            self.labels[body['name']] = len(self.labels) + 1
            return {'id': self.labels[body['name']]}
        return {}


def test_a_label_is_put_on_an_issue_by_id_on_gitea_and_by_name_on_github() -> None:
    gitea = _Client(GITEA, {'request:done': 7})
    add_label(gitea, 9, 'request:done')
    assert gitea.calls[-1] == ('POST', '/r/issues/9/labels', {'labels': [7]})
    hub = _Client(GITHUB, {'request:done': 7})
    add_label(hub, 9, 'request:done')
    assert hub.calls[-1] == ('POST', '/r/issues/9/labels', {'labels': ['request:done']})


def test_a_missing_label_is_refused_by_name_unless_ensured() -> None:
    """PLANTED (live): Gitea answered 201 to an unknown label name and the request never queued."""
    client = _Client(GITEA, {})
    with pytest.raises(LabelMissing, match='forge:request'):
        add_label(client, 9, 'forge:request')
    assert ensure_labels(client, ['forge:request']) == {'forge:request': 1}
    assert ensure_labels(client, ['forge:request']) == {'forge:request': 1}, 'created once'
