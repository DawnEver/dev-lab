"""ONE ALERT, READ AT A GLANCE: a structured notice, written once as Markdown, rendered per channel.

A person glancing at a phone lock screen learns from the FIRST LINE what is wrong, where, how bad (severity in
words, the value against its threshold) and -- from the second -- whether to act; the context (repository, PR,
branch, commit, run, service, since/last, the biggest consumers, the exact remedy) follows as a compact field
list. :class:`Notice` is the model; :func:`markdown` is the ONE text, and every channel derives from it:

* the agent hook and an email's plain-text part carry :func:`markdown` as it is;
* :func:`telegram_html` and :func:`email_html` render that same Markdown to HTML (:func:`_html`), so no channel
  words its own message. :func:`headline` is the first line without markup: the email subject.

EVERY INTERPOLATED VALUE IS UNTRUSTED (a path, a process name, a PR title): :func:`_md` backslash-escapes what
Markdown would read as markup, a code span cannot hold a backtick, a link is ``http(s)`` only with its
delimiters percent-encoded, and the HTML renderer escapes every character it emits. Telegram's limit is kept by
dropping WHOLE findings before rendering, so a cut never lands inside a tag.
"""

from __future__ import annotations

import html
import re
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final

from lab_commons.config import section

from dev_lab.supervise.verdict import Severity

__all__ = [
    'TELEGRAM_LIMIT',
    'Context',
    'Notice',
    'email_html',
    'headline',
    'host_label',
    'markdown',
    'telegram_html',
]

#: Telegram's ``sendMessage`` text limit, in characters.
TELEGRAM_LIMIT: Final = 4096

#: How many characters of one title, field or finding are kept, so no single value can fill a message.
_ITEM_KEPT: Final = 400

#: The separator between the first line's parts.
_SEP: Final = ' \N{MIDDLE DOT} '

#: Said when *action* is empty: the second thing a reader learns is that nothing is asked of them.
_NO_ACTION: Final = 'No action needed.'

#: What Markdown (and the renderer here) would read as markup inside running text.
_MARKUP: Final = re.compile(r'([\\`*_\[\]<>&~|])')

#: The email's headline-bar colour per severity word.
_COLOURS: Final = {'CRITICAL': '#c62828', 'WARNING': '#ef6c00', 'INFO': '#1565c0', 'TEST': '#6a1b9a'}


@dataclass(frozen=True)
class Context:
    """Where an alert happened -- every field optional, and an absent one is omitted, never ``None``.

    Attributes:
        repo: the repository (``owner/name`` or its URL).
        pr: the pull request's number; *pr_title* and *pr_url* name and link it.
        branch: the branch concerned.
        sha: the commit; shown short, linked by *sha_url*.
        run_url: the workflow or run to open.
        service: the service or systemd unit concerned.

    """

    repo: str = ''
    pr: int | None = None
    pr_title: str = ''
    pr_url: str = ''
    branch: str = ''
    sha: str = ''
    sha_url: str = ''
    run_url: str = ''
    service: str = ''


@dataclass(frozen=True)
class Notice:
    """One thing to tell a human (and an agent), as fields -- never as a sentence a channel has to parse.

    Attributes:
        title: what is wrong, short (``disk /``); with *value* it is the metric the value reads.
        severity: how loudly it reads.
        host: the host as a person names it (:func:`host_label`), never an opaque cloud name.
        value: the measured value (``91%``), when there is one.
        threshold: the bar it crossed (``90%``), when there is one.
        since: when it was first seen (ISO 8601 or display text).
        last: when it was last seen; omitted when equal to *since*.
        context: the repository, PR, branch, commit, run and service it concerns.
        findings: the detail lines (the biggest consumers, a body), each one untrusted.
        findings_title: what the findings ARE (for an agent: data, not instructions).
        action: what the reader must do; empty means no action is needed.
        commands: the exact remedy commands, shown verbatim and never run for anyone.
        test: a test of the channels, not an alarm.

    """

    title: str
    severity: Severity = Severity.WARNING
    host: str = ''
    value: str = ''
    threshold: str = ''
    since: str = ''
    last: str = ''
    context: Context = field(default_factory=Context)
    findings: tuple[str, ...] = ()
    findings_title: str = 'Details'
    action: str = ''
    commands: tuple[str, ...] = ()
    test: bool = False


def host_label(table: Mapping[str, object] | None = None, *, default: str = '') -> str:
    """The host as a person names it: ``[notify] host_label`` of *table* (default the machine file).

    Absent, *default* (the name a caller already knows the host by), else the hostname.
    """
    notify = section('notify') if table is None else table
    return str(notify.get('host_label') or default or socket.gethostname())


def _clip(text: object) -> str:
    text = ''.join(ch if ch.isprintable() else ' ' for ch in str(text))  # one line: a newline cannot start a block
    return text if len(text) <= _ITEM_KEPT else text[: _ITEM_KEPT - 1] + '~'


def _md(text: object) -> str:
    """Untrusted *text* as Markdown that reads as exactly that text."""
    return _MARKUP.sub(r'\\\1', _clip(text))


def _code(text: object) -> str:
    """Untrusted *text* as a code span: a backtick cannot close it early."""
    return '`' + _clip(text).replace('`', "'") + '`'


def _link(label: str, url: str) -> str:
    """*label* (already Markdown) linked to *url*; only ``http(s)``, its delimiters encoded, else the label alone."""
    if not re.match(r'https?://', url):
        return label
    safe = ''.join(f'%{ord(ch):02X}' if ch in ' ()<>"\'`\\' or not ch.isprintable() else ch for ch in _clip(url))
    return f'[{label}]({safe})'


def _severity(notice: Notice) -> str:
    return 'TEST' if notice.test else notice.severity.value.upper()


def _what(notice: Notice) -> list[str]:
    reading = f'{notice.title} {notice.value}' if notice.value else notice.title
    bar = f' (threshold {notice.threshold})' if notice.threshold else ''
    return [part for part in (notice.host, f'{reading}{bar}') if part]


def headline(notice: Notice) -> str:
    """The first line without markup: what a lock screen shows, and the email's subject."""
    return _SEP.join([_severity(notice), *(_clip(part) for part in _what(notice))])


def _when(stamp: str) -> str:
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')


def _fields(notice: Notice) -> list[tuple[str, str]]:
    """The context as ``(name, Markdown value)`` pairs, absent ones omitted."""
    c = notice.context
    out: list[tuple[str, str]] = []
    if c.repo:
        out.append(('Repository', _md(c.repo)))
    if c.pr is not None:
        label = f'\\#{c.pr}' + (f' {_md(c.pr_title)}' if c.pr_title else '')
        out.append(('PR', _link(label, c.pr_url)))
    if c.branch:
        out.append(('Branch', _code(c.branch)))
    if c.sha:
        out.append(('Commit', _link(_code(c.sha[:12]), c.sha_url)))
    if c.run_url:
        out.append(
            ('Run', _link('open', c.run_url) if c.run_url.startswith(('https://', 'http://')) else _md(c.run_url))
        )
    if c.service:
        out.append(('Service', _code(c.service)))
    since, last = (_when(s) if s else '' for s in (notice.since, notice.last))
    if since and last and since != last:
        out += [('Since', _md(since)), ('Last', _md(last))]
    elif since or last:
        out.append(('At', _md(since or last)))
    return out


def markdown(notice: Notice) -> str:
    """THE text of *notice*: the agent hook and the email's plain part carry it; the HTML channels render it."""
    first = _SEP.join([f'**{_severity(notice)}**', *(_md(part) for part in _what(notice))])
    action = _md(notice.action) if notice.action else _md(_NO_ACTION + (' This is a test.' if notice.test else ''))
    out = [first, '', f'**Action:** {action}']
    if fields := _fields(notice):
        out += ['', *(f'- **{name}:** {value}' for name, value in fields)]
    if notice.findings:
        out += ['', f'**{_md(notice.findings_title)}**', *(f'- {_md(one)}' for one in notice.findings)]
    if notice.commands:
        fence = [_clip(one).replace('`', "'") for one in notice.commands]
        out += ['', '**Remedy**', '```', *fence, '```']
    return '\n'.join(out)


def _inline(text: str) -> str:
    """One line of :func:`markdown`'s Markdown as HTML: escapes, ``**bold**``, code spans, ``[label](url)``."""
    out: list[str] = []
    bold, i = False, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            out.append(html.escape(text[i + 1]))
            i += 2
        elif text.startswith('**', i):
            out.append('</b>' if bold else '<b>')
            bold, i = not bold, i + 2
        elif ch == '`' and (end := text.find('`', i + 1)) > i:
            out.append(f'<code>{html.escape(text[i + 1 : end])}</code>')
            i = end + 1
        elif ch == '[' and (found := _link_at(text, i)):
            label, url, i = found
            out.append(f'<a href="{html.escape(url, quote=True)}">{_inline(label)}</a>')
        else:
            out.append(html.escape(ch))
            i += 1
    return ''.join(out) + ('</b>' if bold else '')


def _link_at(text: str, start: int) -> tuple[str, str, int] | None:
    """The ``[label](url)`` opening at *start*, as ``(label, url, end)``; ``None`` when it is not one."""
    i, in_code = start + 1, False
    while i < len(text):
        ch = text[i]
        if ch == '\\' and not in_code:
            i += 2
            continue
        in_code ^= ch == '`'
        if ch == ']' and not in_code:
            close = text.find(')', i)
            if text.startswith('(', i + 1) and close > i:
                return text[start + 1 : i], text[i + 2 : close], close + 1
            return None
        i += 1
    return None


def _html(text: str, *, item: str, paragraph: str, code: str, first: str, blank: str | None) -> str:
    """:func:`markdown`'s Markdown as HTML: each block wrapped by its ``{}`` template; a blank line as *blank*."""
    out: list[str] = []
    items: list[str] = []
    fenced: list[str] | None = None
    for index, line in enumerate(text.split('\n')):
        if fenced is not None:
            if line == '```':
                out.append(code.format(html.escape('\n'.join(fenced))))
                fenced = None
            else:
                fenced.append(line)
            continue
        if line.startswith('- '):
            items.append(item.format(_inline(line[2:])))
            continue
        if items:
            out.append('\n'.join(items))
            items = []
        if line == '```':
            fenced = []
        elif line:
            out.append((first if index == 0 else paragraph).format(_inline(line)))
        elif blank is not None:
            out.append(blank)
    if items:
        out.append('\n'.join(items))
    return '\n'.join(out)


def _fit(notice: Notice, render: Callable[[Notice], str], limit: int) -> str:
    """*render* of *notice*, dropping whole findings, then commands, until it fits *limit*."""
    findings, commands = list(notice.findings), list(notice.commands)
    while True:
        dropped = len(notice.findings) - len(findings) + len(notice.commands) - len(commands)
        shown = (*findings, f'{dropped} more line(s) not shown') if dropped else tuple(findings)
        text = render(replace(notice, findings=shown, commands=tuple(commands)))
        if len(text) <= limit:
            return text
        if not (findings or commands):
            return render(Notice(title=headline(notice)[: limit // 8], test=notice.test, severity=notice.severity))
        (findings or commands).pop()


def telegram_html(notice: Notice, limit: int = TELEGRAM_LIMIT) -> str:
    """Telegram ``parse_mode=HTML``, rendered from :func:`markdown`, within *limit* characters."""

    def render(one: Notice) -> str:
        return _html(markdown(one), item='\N{BULLET} {}', paragraph='{}', code='<pre>{}</pre>', first='{}', blank='')

    return _fit(notice, render, limit)


def email_html(notice: Notice) -> str:
    """The email's HTML part, rendered from :func:`markdown`: a coloured headline bar, then the same blocks."""
    colour = _COLOURS[_severity(notice)]
    body = _html(
        markdown(notice),
        item='<li>{}</li>',
        paragraph='<p>{}</p>',
        code='<pre style="background:#f4f4f4;padding:8px">{}</pre>',
        first=f'<h2 style="margin:0;padding:10px 14px;color:#fff;background:{colour}">{{}}</h2>',
        blank=None,
    )
    body = re.sub(r'((?:<li>.*</li>\n?)+)', lambda m: f'<ul>\n{m.group(1).rstrip()}\n</ul>\n', body).rstrip()
    page = '<html><body style="font-family:sans-serif;font-size:14px;color:#222">'
    return f'<!DOCTYPE html>\n{page}\n{body}\n</body></html>'
