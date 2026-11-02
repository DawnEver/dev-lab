"""ONE ALERT, READ AT A GLANCE: one model, one Markdown text, rendered per channel; every value escaped."""

from __future__ import annotations

import html
import re

import pytest

from dev_lab.supervise.notice import (
    INVESTIGATE,
    TELEGRAM_LIMIT,
    Context,
    Notice,
    email_html,
    headline,
    host_label,
    markdown,
    telegram_html,
)
from dev_lab.supervise.verdict import Severity

DOORS = ('python -m dev_lab.dev.branchset --apply', 'python -m dev_lab.dev.retention --apply')
FORGE = 'https://git.example.org/DawnEver/motronics-studio'
CASES = {
    'critical': Notice(
        title='disk /',
        severity=Severity.CRITICAL,
        host='Gitea',
        value='4.2 GB free',
        threshold='10 GB',
        since='2026-11-01T10:00:00+00:00',
        last='2026-11-01T12:00:00+00:00',
        findings=('"/srv/runner/lane"  41.00 GB  owned',),
        findings_title='Biggest consumers',
        action='Free disk space now.',
        commands=DOORS,
    ),
    'warning': Notice(
        title='disk /',
        severity=Severity.WARNING,
        host='Gitea',
        value='91%',
        threshold='90%',
        since='2026-11-01T10:00:00+00:00',
        last='2026-11-01T12:00:00+00:00',
        findings=('"/srv/runner/lane"  41.00 GB  owned', '"/var/lib/gitea"  12.50 GB  not owned, never touched'),
        findings_title='Biggest consumers',
        action='Free disk space with a cleanup command below.',
        commands=DOORS,
    ),
    'info': Notice(
        title='nightly backup finished',
        severity=Severity.INFO,
        host='Gitea',
        since='2026-11-01T12:00:00+00:00',
        last='2026-11-01T12:00:00+00:00',
    ),
    'forge': Notice(
        title='review blocks 3f2a9c81d7e4 (#5443)',
        severity=Severity.CRITICAL,
        host='Gitea',
        context=Context(
            repo='DawnEver/motronics-studio',
            pr=5443,
            pr_title='feat(mesh): band rules own the MeshSpec',
            pr_url=f'{FORGE}/pulls/5443',
            branch='pr/meshspec-band-rules',
            sha='3f2a9c81d7e4b5a6c7d8e9f00112233445566778',
            sha_url=f'{FORGE}/commit/3f2a9c81d7e4b5a6c7d8e9f00112233445566778',
            run_url=f'{FORGE}/actions/runs/812',
        ),
        findings=('review blocks the merge on F-2a7e8020c00a',),
        action='Fix the finding, or claim it is not a defect.',
        commands=('python -m dev_lab.dev.forge review dispose 5443 F-2a7e8020c00a',),
    ),
    'test': Notice(
        title='alert channels reached',
        severity=Severity.INFO,
        host='Gitea',
        since='2026-11-02T00:08:56+00:00',
        findings=('sent by: root@iZd7o3pitw8km72ti2wkrwZ', 'channels attempted: email, telegram'),
        commands=('python -m dev_lab.dev.hostalarm test',),
        test=True,
    ),
}
RENDERERS = {'telegram_html': telegram_html, 'markdown': markdown, 'email_html': email_html, 'headline': headline}

#: THE GOLDENS: each channel of each alert, rendered. A change to any wording is a change here.
GOLDEN = {
    'critical': {
        'telegram_html': (
            '<b>CRITICAL</b> · Gitea · disk / 4.2 GB free (threshold 10 GB)\n'
            '\n'
            '<b>Action:</b> Free disk space now.\n'
            '\n'
            '• <b>Since:</b> 2026-11-01 10:00 UTC\n'
            '• <b>Last:</b> 2026-11-01 12:00 UTC\n'
            '\n'
            '<b>Biggest consumers</b>\n'
            '• &quot;/srv/runner/lane&quot;  41.00 GB  owned\n'
            '\n'
            '<b>Remedy</b>\n'
            '<pre>python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply</pre>'
        ),
        'markdown': (
            '**CRITICAL** · Gitea · disk / 4.2 GB free (threshold 10 GB)\n'
            '\n'
            '**Action:** Free disk space now.\n'
            '\n'
            '- **Since:** 2026-11-01 10:00 UTC\n'
            '- **Last:** 2026-11-01 12:00 UTC\n'
            '\n'
            '**Biggest consumers**\n'
            '- "/srv/runner/lane"  41.00 GB  owned\n'
            '\n'
            '**Remedy**\n'
            '```\n'
            'python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply\n'
            '```'
        ),
        'email_html': (
            '<!DOCTYPE html>\n'
            '<html><body style="font-family:sans-serif;font-size:14px;color:#222">\n'
            '<h2 style="margin:0;padding:10px 14px;color:#fff;background:#c62828"><b>CRITICAL</b> · Gitea · disk / 4.2 GB free (threshold 10 GB)</h2>\n'  # noqa: E501
            '<p><b>Action:</b> Free disk space now.</p>\n'
            '<ul>\n'
            '<li><b>Since:</b> 2026-11-01 10:00 UTC</li>\n'
            '<li><b>Last:</b> 2026-11-01 12:00 UTC</li>\n'
            '</ul>\n'
            '<p><b>Biggest consumers</b></p>\n'
            '<ul>\n'
            '<li>&quot;/srv/runner/lane&quot;  41.00 GB  owned</li>\n'
            '</ul>\n'
            '<p><b>Remedy</b></p>\n'
            '<pre style="background:#f4f4f4;padding:8px">python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply</pre>\n'
            '</body></html>'
        ),
        'headline': ('CRITICAL · Gitea · disk / 4.2 GB free (threshold 10 GB)'),
    },
    'warning': {
        'telegram_html': (
            '<b>WARNING</b> · Gitea · disk / 91% (threshold 90%)\n'
            '\n'
            '<b>Action:</b> Free disk space with a cleanup command below.\n'
            '\n'
            '• <b>Since:</b> 2026-11-01 10:00 UTC\n'
            '• <b>Last:</b> 2026-11-01 12:00 UTC\n'
            '\n'
            '<b>Biggest consumers</b>\n'
            '• &quot;/srv/runner/lane&quot;  41.00 GB  owned\n'
            '• &quot;/var/lib/gitea&quot;  12.50 GB  not owned, never touched\n'
            '\n'
            '<b>Remedy</b>\n'
            '<pre>python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply</pre>'
        ),
        'markdown': (
            '**WARNING** · Gitea · disk / 91% (threshold 90%)\n'
            '\n'
            '**Action:** Free disk space with a cleanup command below.\n'
            '\n'
            '- **Since:** 2026-11-01 10:00 UTC\n'
            '- **Last:** 2026-11-01 12:00 UTC\n'
            '\n'
            '**Biggest consumers**\n'
            '- "/srv/runner/lane"  41.00 GB  owned\n'
            '- "/var/lib/gitea"  12.50 GB  not owned, never touched\n'
            '\n'
            '**Remedy**\n'
            '```\n'
            'python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply\n'
            '```'
        ),
        'email_html': (
            '<!DOCTYPE html>\n'
            '<html><body style="font-family:sans-serif;font-size:14px;color:#222">\n'
            '<h2 style="margin:0;padding:10px 14px;color:#fff;background:#ef6c00"><b>WARNING</b> · Gitea · disk / 91% (threshold 90%)</h2>\n'  # noqa: E501
            '<p><b>Action:</b> Free disk space with a cleanup command below.</p>\n'
            '<ul>\n'
            '<li><b>Since:</b> 2026-11-01 10:00 UTC</li>\n'
            '<li><b>Last:</b> 2026-11-01 12:00 UTC</li>\n'
            '</ul>\n'
            '<p><b>Biggest consumers</b></p>\n'
            '<ul>\n'
            '<li>&quot;/srv/runner/lane&quot;  41.00 GB  owned</li>\n'
            '<li>&quot;/var/lib/gitea&quot;  12.50 GB  not owned, never touched</li>\n'
            '</ul>\n'
            '<p><b>Remedy</b></p>\n'
            '<pre style="background:#f4f4f4;padding:8px">python -m dev_lab.dev.branchset --apply\n'
            'python -m dev_lab.dev.retention --apply</pre>\n'
            '</body></html>'
        ),
        'headline': ('WARNING · Gitea · disk / 91% (threshold 90%)'),
    },
    'info': {
        'telegram_html': (
            '<b>INFO</b> · Gitea · nightly backup finished\n'
            '\n'
            '<b>Action:</b> No action needed.\n'
            '\n'
            '• <b>At:</b> 2026-11-01 12:00 UTC'
        ),
        'markdown': (
            '**INFO** · Gitea · nightly backup finished\n'
            '\n'
            '**Action:** No action needed.\n'
            '\n'
            '- **At:** 2026-11-01 12:00 UTC'
        ),
        'email_html': (
            '<!DOCTYPE html>\n'
            '<html><body style="font-family:sans-serif;font-size:14px;color:#222">\n'
            '<h2 style="margin:0;padding:10px 14px;color:#fff;background:#1565c0"><b>INFO</b> · Gitea · nightly backup finished</h2>\n'  # noqa: E501
            '<p><b>Action:</b> No action needed.</p>\n'
            '<ul>\n'
            '<li><b>At:</b> 2026-11-01 12:00 UTC</li>\n'
            '</ul>\n'
            '</body></html>'
        ),
        'headline': ('INFO · Gitea · nightly backup finished'),
    },
    'forge': {
        'telegram_html': (
            '<b>CRITICAL</b> · Gitea · review blocks 3f2a9c81d7e4 (#5443)\n'
            '\n'
            '<b>Action:</b> Fix the finding, or claim it is not a defect.\n'
            '\n'
            '• <b>Repository:</b> DawnEver/motronics-studio\n'
            '• <b>PR:</b> <a href="https://git.example.org/DawnEver/motronics-studio/pulls/5443">#5443 feat(mesh): band rules own the MeshSpec</a>\n'  # noqa: E501
            '• <b>Branch:</b> <code>pr/meshspec-band-rules</code>\n'
            '• <b>Commit:</b> <a href="https://git.example.org/DawnEver/motronics-studio/commit/3f2a9c81d7e4b5a6c7d8e9f00112233445566778"><code>3f2a9c81d7e4</code></a>\n'
            '• <b>Run:</b> <a href="https://git.example.org/DawnEver/motronics-studio/actions/runs/812">open</a>\n'
            '\n'
            '<b>Details</b>\n'
            '• review blocks the merge on F-2a7e8020c00a\n'
            '\n'
            '<b>Remedy</b>\n'
            '<pre>python -m dev_lab.dev.forge review dispose 5443 F-2a7e8020c00a</pre>'
        ),
        'markdown': (
            '**CRITICAL** · Gitea · review blocks 3f2a9c81d7e4 (#5443)\n'
            '\n'
            '**Action:** Fix the finding, or claim it is not a defect.\n'
            '\n'
            '- **Repository:** DawnEver/motronics-studio\n'
            '- **PR:** [\\#5443 feat(mesh): band rules own the MeshSpec](https://git.example.org/DawnEver/motronics-studio/pulls/5443)\n'
            '- **Branch:** `pr/meshspec-band-rules`\n'
            '- **Commit:** [`3f2a9c81d7e4`](https://git.example.org/DawnEver/motronics-studio/commit/3f2a9c81d7e4b5a6c7d8e9f00112233445566778)\n'
            '- **Run:** [open](https://git.example.org/DawnEver/motronics-studio/actions/runs/812)\n'
            '\n'
            '**Details**\n'
            '- review blocks the merge on F-2a7e8020c00a\n'
            '\n'
            '**Remedy**\n'
            '```\n'
            'python -m dev_lab.dev.forge review dispose 5443 F-2a7e8020c00a\n'
            '```'
        ),
        'email_html': (
            '<!DOCTYPE html>\n'
            '<html><body style="font-family:sans-serif;font-size:14px;color:#222">\n'
            '<h2 style="margin:0;padding:10px 14px;color:#fff;background:#c62828"><b>CRITICAL</b> · Gitea · review blocks 3f2a9c81d7e4 (#5443)</h2>\n'  # noqa: E501
            '<p><b>Action:</b> Fix the finding, or claim it is not a defect.</p>\n'
            '<ul>\n'
            '<li><b>Repository:</b> DawnEver/motronics-studio</li>\n'
            '<li><b>PR:</b> <a href="https://git.example.org/DawnEver/motronics-studio/pulls/5443">#5443 feat(mesh): band rules own the MeshSpec</a></li>\n'  # noqa: E501
            '<li><b>Branch:</b> <code>pr/meshspec-band-rules</code></li>\n'
            '<li><b>Commit:</b> <a href="https://git.example.org/DawnEver/motronics-studio/commit/3f2a9c81d7e4b5a6c7d8e9f00112233445566778"><code>3f2a9c81d7e4</code></a></li>\n'
            '<li><b>Run:</b> <a href="https://git.example.org/DawnEver/motronics-studio/actions/runs/812">open</a></li>\n'
            '</ul>\n'
            '<p><b>Details</b></p>\n'
            '<ul>\n'
            '<li>review blocks the merge on F-2a7e8020c00a</li>\n'
            '</ul>\n'
            '<p><b>Remedy</b></p>\n'
            '<pre style="background:#f4f4f4;padding:8px">python -m dev_lab.dev.forge review dispose 5443 F-2a7e8020c00a</pre>\n'  # noqa: E501
            '</body></html>'
        ),
        'headline': ('CRITICAL · Gitea · review blocks 3f2a9c81d7e4 (#5443)'),
    },
    'test': {
        'telegram_html': (
            '<b>TEST</b> · Gitea · alert channels reached\n'
            '\n'
            '<b>Action:</b> No action needed. This is a test.\n'
            '\n'
            '• <b>At:</b> 2026-11-02 00:08 UTC\n'
            '\n'
            '<b>Details</b>\n'
            '• sent by: root@iZd7o3pitw8km72ti2wkrwZ\n'
            '• channels attempted: email, telegram\n'
            '\n'
            '<b>Remedy</b>\n'
            '<pre>python -m dev_lab.dev.hostalarm test</pre>'
        ),
        'markdown': (
            '**TEST** · Gitea · alert channels reached\n'
            '\n'
            '**Action:** No action needed. This is a test.\n'
            '\n'
            '- **At:** 2026-11-02 00:08 UTC\n'
            '\n'
            '**Details**\n'
            '- sent by: root@iZd7o3pitw8km72ti2wkrwZ\n'
            '- channels attempted: email, telegram\n'
            '\n'
            '**Remedy**\n'
            '```\n'
            'python -m dev_lab.dev.hostalarm test\n'
            '```'
        ),
        'email_html': (
            '<!DOCTYPE html>\n'
            '<html><body style="font-family:sans-serif;font-size:14px;color:#222">\n'
            '<h2 style="margin:0;padding:10px 14px;color:#fff;background:#6a1b9a"><b>TEST</b> · Gitea · alert channels reached</h2>\n'  # noqa: E501
            '<p><b>Action:</b> No action needed. This is a test.</p>\n'
            '<ul>\n'
            '<li><b>At:</b> 2026-11-02 00:08 UTC</li>\n'
            '</ul>\n'
            '<p><b>Details</b></p>\n'
            '<ul>\n'
            '<li>sent by: root@iZd7o3pitw8km72ti2wkrwZ</li>\n'
            '<li>channels attempted: email, telegram</li>\n'
            '</ul>\n'
            '<p><b>Remedy</b></p>\n'
            '<pre style="background:#f4f4f4;padding:8px">python -m dev_lab.dev.hostalarm test</pre>\n'
            '</body></html>'
        ),
        'headline': ('TEST · Gitea · alert channels reached'),
    },
}


@pytest.mark.parametrize('case', sorted(CASES))
@pytest.mark.parametrize('channel', sorted(RENDERERS))
def test_each_channel_renders_each_alert_to_its_golden(case: str, channel: str) -> None:
    assert RENDERERS[channel](CASES[case]) == GOLDEN[case][channel]


def _text(markup: str) -> str:
    """What a reader sees of *markup*: tags dropped, entities read."""
    return html.unescape(re.sub(r'<[^>]+>', '', markup))


def test_the_first_line_names_severity_in_words_host_metric_value_and_threshold() -> None:
    """No emoji; every channel opens with the headline, and the email subject is it."""
    assert headline(CASES['warning']) == 'WARNING \N{MIDDLE DOT} Gitea \N{MIDDLE DOT} disk / 91% (threshold 90%)'
    assert markdown(CASES['warning']).splitlines()[0] == (
        '**WARNING** \N{MIDDLE DOT} Gitea \N{MIDDLE DOT} disk / 91% (threshold 90%)'
    )
    for one in CASES.values():
        assert all(ch.isascii() or ch == '\N{MIDDLE DOT}' for ch in markdown(one) + headline(one))
        assert _text(telegram_html(one).splitlines()[0]) == headline(one)
        assert headline(one).split(' ', 1)[0] in {'CRITICAL', 'WARNING', 'INFO', 'TEST'}


def test_absent_context_is_omitted_and_since_equal_to_last_is_said_once() -> None:
    for render in RENDERERS.values():
        text = render(CASES['info'])
        assert 'None' not in text
        assert 'Since' not in text
        assert 'Repository' not in text
        assert text.count('nightly backup finished') == 1
    assert '- **At:** 2026-11-01 12:00 UTC' in markdown(CASES['info'])


def test_a_forge_alarm_carries_its_pr_branch_commit_and_run_as_links() -> None:
    page = telegram_html(CASES['forge'])
    assert f'<a href="{FORGE}/pulls/5443">#5443 feat(mesh): band rules own the MeshSpec</a>' in page
    assert f'<a href="{FORGE}/commit/3f2a9c81d7e4b5a6c7d8e9f00112233445566778"><code>3f2a9c81d7e4</code></a>' in page
    assert '<code>pr/meshspec-band-rules</code>' in page
    assert f'<a href="{FORGE}/actions/runs/812">' in page


HOSTILE = '*_[]()~>#+-=|{}.!\\ <script>alert(1)</script> & "x"'


def test_every_interpolated_value_is_escaped_for_markdown_and_html() -> None:
    """A hostile value in every field reads back as itself, and never as markup, in every HTML channel."""
    hostile = Notice(
        title=HOSTILE,
        host=HOSTILE,
        value=HOSTILE,
        threshold=HOSTILE,
        since=HOSTILE,
        context=Context(repo=HOSTILE, pr=1, pr_title=HOSTILE, pr_url='javascript:alert(1)', branch=HOSTILE),
        findings=(HOSTILE,),
        findings_title=HOSTILE,
        action=HOSTILE,
        commands=(HOSTILE,),
    )
    allowed = {'b', 'code', 'pre', 'p', 'ul', 'li', 'h2', 'html', 'body'}
    for page in (telegram_html(hostile), email_html(hostile)):
        assert '<script>' not in page
        assert 'javascript:' not in page  # a link that is not http(s) is its label alone
        assert set(re.findall(r'</?([a-z0-9]+)', page)) <= allowed
        assert _text(page).count(HOSTILE) >= 8  # each field reads exactly as it was typed
    assert markdown(hostile).count('\\*\\_\\[\\]()\\~\\>#+-=\\|{}.!\\\\ \\<script\\>') >= 8


def _balanced(text: str) -> bool:
    stack: list[str] = []
    for closing, name in re.findall(r'<(/?)([a-z]+)[^>]*>', text):
        if closing:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack and not re.search(r'&[a-z]*$|<[^>]*$', text)


def test_telegram_fits_its_limit_by_dropping_whole_items_never_a_tag() -> None:
    big = Notice(title='disk /', findings=tuple(f'<b>&{i}' * 40 for i in range(200)), commands=DOORS)
    text = telegram_html(big)
    assert len(text) <= TELEGRAM_LIMIT
    assert _balanced(text)
    assert re.search(r'\d+ more line\(s\) not shown', text)
    tiny = telegram_html(big, limit=120)
    assert len(tiny) <= 120
    assert _balanced(tiny)
    assert telegram_html(CASES['warning']) == GOLDEN['warning']['telegram_html']  # control: a short one is whole


def test_the_host_label_comes_from_notify_else_the_default_else_the_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('socket.gethostname', lambda: 'iZd7o3pitw8km72ti2wkrwZ')
    assert host_label({'host_label': 'Gitea'}) == 'Gitea'
    assert host_label({}, default='gitea-1') == 'gitea-1'
    assert host_label({}) == 'iZd7o3pitw8km72ti2wkrwZ'


@pytest.mark.parametrize('severity', [Severity.WARNING, Severity.CRITICAL])
def test_an_alarm_without_an_action_never_says_no_action(severity: Severity) -> None:
    """F-358f80905635: a WARNING or CRITICAL with no action points at the details; only TEST and INFO may say none."""
    alarm = Notice(title='web: health check failed', severity=severity, findings=('HTTP 503',))
    for render in RENDERERS.values():
        assert 'No action' not in render(alarm)
    assert f'**Action:** {INVESTIGATE}' in markdown(alarm)
    assert 'No action needed' in markdown(CASES['test'])  # control: a test still says it
    assert 'No action needed' in markdown(CASES['info'])  # and an INFO
