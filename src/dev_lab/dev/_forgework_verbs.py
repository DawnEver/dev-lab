"""The issue and pull-request verbs a forge :class:`~dev_lab.dev.forgework.Client` offers.

They are written once against the client's one REST door (:meth:`~dev_lab.dev.forgework.Client.call`) and the
repository it names; the client itself -- credential, retries, journal --
is :mod:`dev_lab.dev.forgework`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dev_lab.dev import sessionprs
from dev_lab.dev._forge_journal import LOOKBACK, Durable, Probe, since
from dev_lab.dev._forge_records import Comment, Issue, PullRequest, _issue, comment_of, draft_title, pull_of
from dev_lab.dev._forgebackends import GITHUB, Backend, backend_for
from dev_lab.dev.forgepages import issues
from dev_lab.dev.forgethreads import record_own

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from dev_lab.dev.forge import Forge

__all__ = ['Verbs']


def _recent(door: Verbs, collection: str) -> str:
    return f'{door.repo}/{collection}?state=all&{door.backend.page_param}={LOOKBACK}'


def _stamped(door: Verbs, text: str) -> str:
    return text if door.stamp is None else f'{door.stamp}\n\n{text}'


class Verbs:
    """The issue and pull-request verbs, mixed into :class:`~dev_lab.dev.forgework.Client`, which supplies the rest.

    The client's fields the verbs read are declared here; :meth:`call` is the client's REST door.
    """

    forge: Forge
    stamp: str | None
    clock: Callable[[], datetime]

    if TYPE_CHECKING:

        def call(
            self, method: str, path: str, body: Mapping[str, Any] | None = None, durable: Durable | None = None
        ) -> Any:  # noqa: ANN401 -- JSON
            """One REST call: :meth:`dev_lab.dev.forgework.Client.call`."""
            ...

    @property
    def backend(self) -> Backend:
        """The backend this repository's host selects."""
        return backend_for(self.forge)

    @property
    def repo(self) -> str:
        """The repository's API collection path, which every verb's path starts with."""
        return self.backend.repo_path(self.forge)

    def issue_list(self, *, state: str = 'open', limit: int = 30, labels: Sequence[str] = ()) -> tuple[Issue, ...]:
        """Issues in *state* carrying every one of *labels*, read page by page (:func:`forgepages.issues`)."""
        return issues(self.call, f'{self.repo}/issues?{self.backend.list_query}', state, limit, labels)

    def issue_view(self, number: int) -> Issue:
        """One issue."""
        return _issue(self.call('GET', f'{self.repo}/issues/{number}'))

    def issue_create(self, title: str, body: str) -> Issue:
        """A new issue; the body carries the provenance line."""
        payload = {'title': title, 'body': _stamped(self, body)}
        probe = Probe(_recent(self, 'issues'), payload)
        return _issue(self.call('POST', f'{self.repo}/issues', payload, Durable(probe=probe)))

    def issue_comment(self, number: int, body: str) -> Comment:
        """A comment on an issue (or a PR, which both forges number as an issue)."""
        path, payload = f'{self.repo}/issues/{number}/comments', {'body': _stamped(self, body)}
        probe = Probe(f'{path}?since={since(self.clock())}', payload)
        posted = comment_of(self.call('POST', path, payload, Durable(probe=probe)))
        record_own(f'{self.forge.identity}#{number}')  # TASK-HEARS-ITS-FORGE-EVENTS: own words are never news
        return posted

    def issue_edit(self, number: int, body: str) -> Issue:
        """Replace an issue's body; the body is state, so no provenance line is added."""
        return _issue(self.call('PATCH', f'{self.repo}/issues/{number}', {'body': body}))

    def issue_close(self, number: int) -> Issue:
        """Close an issue; nothing is written but the state."""
        return _issue(self.call('PATCH', f'{self.repo}/issues/{number}', {'state': 'closed'}))

    def pr_create(self, title: str, body: str, *, head: str, base: str, draft: bool) -> PullRequest:
        """A new pull request from *head* into *base*; a *draft* in the forge's own way (:mod:`dev_lab.dev.forgedraft`).

        GitHub takes ``draft: true``; Gitea has no draft field, and reads its ``WIP:`` title prefix as one. Every
        door that opens a PR comes through here, so here it is recorded as the running agent session's
        (TASK-HEARS-ITS-FORGE-EVENTS, :func:`~dev_lab.dev.sessionprs.record_opened`), whatever a shell line printed.
        """
        if draft and self.backend is not GITHUB:
            title = draft_title(title)
        payload: dict[str, Any] = {'title': title, 'body': _stamped(self, body), 'head': head, 'base': base}
        if draft and self.backend is GITHUB:
            payload['draft'] = True
        durable = Durable(probe=Probe(_recent(self, 'pulls'), {'title': title, 'body': payload['body']}))
        made = self.call('POST', f'{self.repo}/pulls', payload, durable)
        return sessionprs.noted(self.forge, pull_of(made), branch=head)

    def pr_view(self, number: int) -> PullRequest:
        """One pull request."""
        return pull_of(self.call('GET', f'{self.repo}/pulls/{number}'))
