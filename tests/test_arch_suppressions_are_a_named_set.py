"""THE SUPPRESSION RATCHET: every silenced check is a NAMED waiver carrying its reason.

A suppression is a check that was asked a question and told not to answer. That is sometimes right --
three of the entries below are unavoidable -- but it is never free, and the failure mode is that the
list only ever grows: each new one looks like the last one, nobody can tell which, and the checks
this repo advertises quietly stop covering the code it ships to four other repos.

THE PIN IS A NAMED SET, NOT A COUNT, and that is the point of the whole module. An integer pin cannot
say WHICH row moved -- a suppression removed and a suppression added net to the same digit -- so the
honest-looking repair when it disagrees is to edit the number, which is how a pin ends up documenting
whatever the tree happens to contain. A named set forces the edit to say what changed.

THE RATCHET HAS TWO SIDES. An undeclared suppression reds, and a declared suppression that has
DISAPPEARED reds too. Without the second half nothing ever comes off the list, and a waiver nothing
uses is exactly as wrong as an undeclared one: it asserts a constraint on code that no longer exists.

THE ANCHOR IS THE SUPPRESSED SOURCE TEXT, NOT A LINE NUMBER. A line number churns on every unrelated
edit above it, and a pin that reds for an unrelated reason is a pin that gets deleted. The code on
the line -- comment stripped -- does not move when something above it does, it distinguishes two
suppressions of the SAME rule inside one function, and it
lets a reader of the pin see what is being waived without opening the file.

THE REASON LIVES IN THE DECLARATION, not on the source line. Two reasons for that call: a per-file
``ruff`` ignore in ``pyproject.toml`` has no source line to carry a comment, so only the declaration
can hold every waiver's reason in one shape; and a trailing comment is prose no tool consults, while
the dict value below is refused when it is empty. A source-line comment stays welcome -- it is just
not the thing under guard.

SCOPE is ``src/`` and ``tests/`` -- the two corpora every sibling guard uses, and this repo has no
``scripts/`` tree -- plus ``pyproject.toml``, where a suppression can hide without appearing in any
Python file at all.
"""

from __future__ import annotations

import io
import re
import tokenize
import tomllib
from pathlib import Path
from typing import Final

from _arch_corpus import ROOT, SOURCE_FLOOR, TEST_FLOOR, assert_floor, corpus_key, source_modules, suite_modules

from dev_lab.dev.failprint import subject_lines, subjects_of

#: A suppression site: ``(repo-relative path, rule code, anchor)``. The anchor is the suppressed
#: source text with the comment stripped, or -- for a whole-line comment and for a ``pyproject.toml``
#: per-file ignore -- the comment text and the file glob respectively.
Site = tuple[str, str, str]

#: EVERY suppression this repo allows, each with the reason it is allowed to exist.
#: RE-MEASURED 2026-09-17, when this repo adopted the family's 58-selector `select`: 62 sites, of
#: which 10 are the ``tests/**`` per-file ignores in ``pyproject.toml``. It was 14 the day before,
#: and the jump is the cost of the adoption rather than a loosening: 50 selector groups that had
#: never been asked anything here started asking, and every site below names which rule it silences,
#: on what source line, and why that one is allowed.
#:
#: THE PREVIOUS MEASUREMENT, KEPT: 2026-09-16 read 8 sites across 5 modules under ``src/``, 6 across
#: 4 modules under ``tests/`` (three source lines, two of which silence two rules each), and 0
#: per-file ignores in ``pyproject.toml``.
#:
#: THE ``src/`` COUNT ALREADY SAID 5 MODULES WHILE THE TABLE HELD 4, and that is worth a line here.
#: ``3cce383`` added a marker in ``docsite.py`` and one in ``test_dev_githooks.py`` and declared
#: neither, so this guard had been red since -- found on 2026-09-16 by a verify for an unrelated fix.
#: The COUNT was right and the TABLE was wrong, the direction this file's own docstring warns about,
#: so both rows are declared below rather than any number being edited down to meet the tree.
ALLOWED: Final[dict[Site, str]] = {
    (
        'tests/_forge_state.py',
        'PLR0911',
        'def _shape(self, route: str) -> tuple[str, str]:',
    ): "the fake forge's router: one return per Gitea route family, a table the forge's own URL shapes dictate",
    (
        'tests/test_dev_forgereview_bundle.py',
        'ANN401',
        'def call(self, method: str, path: str, body: dict[str, Any] | None = None, durable: object = None) -> Any:',
    ): "the fake overrides Client.call, whose answer is the endpoint's parsed JSON: its shape is the route",
    (
        'tests/test_dev_forgereview_bundle.py',
        'ANN401',
        'def _get(self, path: str) -> Any:',
    ): "the fake's GET router returns each endpoint's parsed JSON, whose shape is the route",
    (
        'tests/test_dev_failprint.py',
        'arg-type',
        'return lambda ref: fingerprints_at(_Forge(subjects), ref)',
    ): 'a _Forge stands in for the Client fingerprints_at takes: a test double, not a subclass the type checker sees',
    (
        'tests/test_dev_forgereview_bundle.py',
        'arg-type',
        'return fb.judge_pending(forge, runtimes=_RUNTIMES, fetch=prepared.fetch, run=run), seen',
    ): 'a FakeForge stands in for the Client the judge takes: a test double, not a subclass the type checker can see',
    (
        'tests/test_dev_forgereview_bundle.py',
        'arg-type',
        "assert review_tick(tmp_path, object(), review, base='main', host='h') == ()",
    ): 'PLANTED CONTROL: a bare object() as the client proves a judge base returns before any forge call',
    (
        'tests/test_dev_forgetick.py',
        'FBT001',
        'claimed: bool,',
    ): 'a parametrized case argument: pytest passes it by name, so the positional-bool hazard cannot occur',
    (
        'src/dev_lab/dev/forgerequest.py',
        'PLC0415',
        'from dev_lab.dev.forgeunit import unit_request',
    ): 'forgeunit publishes a Job THROUGH this module (forgepublish -> forgerequest), so a module-scope '
    'import here is a cycle that fails at import time. The built-in unit producer is resolved where '
    'it is called, once per request read',
    (
        'src/dev_lab/dev/reviewcode.py',
        'ANN401',
        'def call(method: str, url: str, body: dict[str, Any] | None) -> Any:',
    ): 'the forge door returns the parsed JSON answer, whose shape is the endpoint',
    (
        'src/dev_lab/dev/reviewcode.py',
        'BLE001',
        'except Exception as failed:',
    ): 'the pre-clone settle never fails the job: any fact it cannot read means the full review runs',
    (
        'src/dev_lab/dev/reviewcode.py',
        'S310',
        'request = urllib.request.Request(url, data=data, method=method)',
    ): 'the URL is the FORGE_URL the job declares API, an https endpoint the workflow declares, never user input',
    (
        'src/dev_lab/ops/giteaadmin.py',
        'S310',
        'request = urllib.request.Request(url, data=data, headers=headers, method=method)',
    ): "the host's own Gitea API, [ops.forge] api, a boundary key only an ops.config consent changes",
    (
        'src/dev_lab/ops/giteaadmin.py',
        'S310',
        'with urllib.request.urlopen(request, timeout=30) as answer:',
    ): 'opens only the request built above to [ops.forge] api',
    (
        'src/dev_lab/dev/forgememo.py',
        'ANN401',
        'def read(self, key: tuple[str, str], attempt: Callable[[], Any]) -> Any:',
    ): "the memo hands back the forge read's parsed JSON unchanged, whose shape is the route it remembers",
    (
        'src/dev_lab/dev/family/__init__.py',
        'ANN401',
        'def declared_table(data: Mapping[str, Any], name: str, default: Any = None) -> Any:',
    ): 'a TOML table is untyped: the value is whatever the manifest declares, handed back unchanged',
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        'def resend(self, write: Write) -> Any:',
    ): 'the outbox replay sends a journaled write through the same retry loop and returns its parsed JSON unchanged',
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        'def _attempts(self, write: Write, data: bytes | None) -> Any:',
    ): 'the retry loop under every verb returns the parsed JSON answer, whose shape is the endpoint',
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        'def landed(self, write: Write) -> Any:',
    ): "a create's read-back returns the listed object as the forge answered it -- the shape the create would have",
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        (
            'def upload(self, path: str, *, field: str, filename: str, content: bytes, '
            'durable: Durable | None = None) -> Any:'
        ),
    ): 'the attachment door returns the parsed JSON answer, normalized by its one caller (forgerecords.Attachment)',
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        ') -> Any:',
    ): 'call and the journaling door under it (the end of their wrapped signatures) return the parsed JSON '
    'answer, whose shape is the endpoint; each verb normalizes it into a typed Issue/Comment/PullRequest',
    (
        'src/dev_lab/dev/forgework.py',
        'ANN401',
        'def upload_raw(self, host: str, path: str, *, content: bytes, durable: Durable | None = None) -> Any:',
    ): "GitHub's release-asset upload returns the parsed JSON answer, normalized by its one caller "
    '(forgerecords.Attachment)',
    (
        'src/dev_lab/dev/docsite.py',
        'arg-type',
        'run(pdoc_argv(modules, out_dir, **options), cwd=root)',
    ): 'pdoc_argv takes `**options: object` so any caller option reaches it; run() is typed on str',
    (
        'src/dev_lab/dev/storage.py',
        'PLC0415',
        'from dev_lab.dev.artefactstores import ArtefactRefused, check_rclone_config',
    ): 'the forge journal and intent writers import storage.output_path, and artefactstores reaches them '
    'through the forge layer, so a module-scope import here is a cycle; render() is a rare door',
    (
        'src/dev_lab/dev/storage.py',
        'PLC0415',
        'from dev_lab.dev.toolrelease import ToolAbsent, resolve',
    ): 'every writer imports storage (the walls ledger on each Stop, inside the hook budget); only the rclone '
    'render needs the pinned-tool table, so it is read where render runs',
    (
        'src/dev_lab/dev/storage.py',
        'no-cover',
        'if found is None:',
    ): 'output always has an in-tree default (lab_commons.storage.root), so the refusal is a guard no '
    'declaration can reach; it keeps the return type a Path instead of Path | None',
    (
        'src/dev_lab/dev/forgerecords.py',
        'PLC0415',
        'from dev_lab.dev.retentionplan import load_policy as retention',
    ): 'retentionplan reaches this module through the forge layer; the [retention] budget has one reader',
    (
        'src/dev_lab/dev/hpcaccount/__init__.py',
        'PLC0415',
        'from dev_lab.dev.hpcaccount import (',
    ): 'the package imports no verb: each verb imports the package, so a top-level import would be a cycle',
    (
        'src/dev_lab/dev/hpcaccount/__init__.py',
        'PLC0415',
        'from dev_lab.dev.hpcaccount import tick, tickwall',
    ): 'the package imports no verb: tick and tickwall import the package, so a top-level import would be a cycle',
    (
        'src/dev_lab/dev/hpcaccount/__init__.py',
        'PLC0415',
        'from dev_lab.dev.hpcaccount.spec import DEFAULT_TICK_WALL_MINUTES',
    ): 'spec imports the package (division, grantslice) and the roles table; only the tick verb needs its default',
    (
        'src/dev_lab/dev/servelock.py',
        'PLC0415',
        'import msvcrt',
    ): 'the Windows lock primitive: msvcrt exists only on Windows, so a top-level import breaks POSIX',
    (
        'src/dev_lab/dev/servelock.py',
        'PLC0415',
        'import fcntl',
    ): 'the POSIX lock primitive: fcntl exists only on POSIX, so a top-level import breaks Windows',
    (
        'src/dev_lab/ops/totp.py',
        'PLC0415',
        'import segno',
    ): 'segno is the ops extra: only the enrolling host draws a QR; a consumer reading codes never installs it',
    (
        'tests/test_dev_githooks.py',
        'PLC0415',
        'import os',
    ): 'one helper needs the AMBIENT environment; a module-level import reads a monkeypatched one',
    (
        'tests/test_dev_doorcensus.py',
        'arg-type',
        'return DoorRow(why=_WHY, **kwargs)',
    ): 'one local builder supplies the shared reason and forwards its dict[str, object] fields verbatim',
    (
        'tests/test_famtests_injectedwidth.py',
        'arg-type',
        'assert_widths_are_the_named_set(scan, **(kwargs | over))',
    ): 'one local helper builds the keyword set as dict[str, object] so a case can override any one',
    (
        'tests/test_famtests_injectedwidth.py',
        'arg-type',
        'scan = real(paths, **kwargs)',
    ): 'a monkeypatch stand-in takes the shipped call untyped and forwards it verbatim to the real one',
    (
        'tests/test_famtests_trackedcjk.py',
        'ANN003',
        'def _forgetful(paths, **kwargs):',
    ): 'the same stand-in shape: annotating it would assert a signature the patch is not claiming',
    (
        'tests/test_famtests_trackedcjk.py',
        'ANN202',
        'def _forgetful(paths, **kwargs):',
    ): 'its return is whatever the shipped scanner returns, so a written return type would be a second claim',
    (
        'tests/test_famtests_upperbounds.py',
        'ARG005',
        "lambda spec, *, ecosystem: 'everything is a bound' if spec.strip() else None,",
    ): 'the planted control is CONVICT-EVERYTHING, so ignoring `ecosystem` is the doctoring under test',
    (
        'tests/test_famtests_upperbounds.py',
        'arg-type',
        'assert_no_undeclared_upper_bound(scan, **(kwargs | over))',
    ): 'the same overridable dict[str, object] keyword set as injectedwidth, for the same reason',
    (
        'pyproject.toml',
        'ANN001',
        'tests/**',
    ): "a test's parameters are fixtures; the type is declared once ON the fixture, and ANN2xx is not waived",
    (
        'pyproject.toml',
        'ARG002',
        'tests/**',
    ): 'a fixture requested for its SIDE EFFECT is used by being requested; dropping the parameter drops the setup',
    (
        'pyproject.toml',
        'D101',
        'tests/**',
    ): 'a test class is a named grouping; the name and the methods below it are the prose',
    (
        'pyproject.toml',
        'D102',
        'tests/**',
    ): 'a test method name in this suite is already a sentence, and a docstring would restate it',
    (
        'pyproject.toml',
        'D103',
        'tests/**',
    ): 'the same for a module-level test function',
    (
        'pyproject.toml',
        'INP001',
        'tests/**',
    ): 'tests/ is rootdir-relative by design; an __init__.py here would shadow the package under test',
    (
        'pyproject.toml',
        'N802',
        'tests/**',
    ): 'this suite SHOUTS the load-bearing word in 64 test names, and lower-casing them deletes the emphasis',
    (
        'pyproject.toml',
        'PLR2004',
        'tests/**',
    ): 'the literal in an assertion IS the expected value; hoisting it to a constant hides what is asserted',
    (
        'pyproject.toml',
        'S101',
        'tests/**',
    ): 'assert is the test vocabulary; src/ carries S101 unwaived',
    (
        'pyproject.toml',
        'SLF001',
        'tests/**',
    ): 'a test that cannot read a private member cannot pin a private invariant',
    (
        'src/dev_lab/dev/forgeheadgate.py',
        'BLE001',
        'except Exception as why:',
    ): 'the serve tick gates every open PR head in turn; one head whose gate raises (git, network, a corrupt '
    'tree) is one line for that head and must not end the tick for the others',
    (
        'src/dev_lab/dev/forgemergeready.py',
        'BLE001',
        'except Exception as error:',
    ): 'the merge tick judges every open PR in turn; one PR whose judgement raises (a git timeout, a forge '
    'call, a corrupt tree) is an error status on that PR and must not end the tick for the PRs after it',
    (
        'src/dev_lab/dev/forgemergeready.py',
        'BLE001',
        'except Exception as unposted:',
    ): 'posting the error status of a PR that could not be judged may itself fail for any reason; the cause '
    'is already said on stderr, so the tick moves on to the next PR',
    (
        'src/dev_lab/dev/famtests/testleaks.py',
        'S108',
        "WORDS: Final = ('mkdtemp', 'mkstemp', 'gettempdir', 'delete=False', '/tmp', ':\\\\', ':/')",
    ): "the reader's own pre-filter words: '/tmp' is the text it searches for, never a path it opens",
    (
        'src/dev_lab/dev/strayleaks.py',
        'PLC0415',
        'import psutil',
    ): 'psutil is transitive, not declared; its absence must keep every aged entry, not fail the sweep import',
    (
        'tests/test_dev_tmpsweep.py',
        'PLC0415',
        'import _winapi',
    ): '_winapi exists only on Windows; the junction helper imports it on the branch that runs there',
    (
        'src/dev_lab/supervise/components/resources.py',
        'PLC0415',
        'import psutil',
    ): 'psutil is optional on a supervised host; importing it inside the check turns its absence into a '
    'reported anomaly instead of a supervisor that cannot start',
    (
        'src/dev_lab/supervise/components/resources.py',
        'BLE001',
        'except Exception:',
    ): 'a process sampled by psutil can vanish or be denied mid-read (several unrelated types); such a '
    'process is skipped as gone, never a crashed resource check',
    (
        'src/dev_lab/supervise/deploy.py',
        'S108',
        "CANDIDATE: Final = '/var/tmp/lab-supervise-candidate'",
    ): 'the candidate build lives on a Linux server under /var/tmp ON PURPOSE: outside the live tree and not '
    'swept by a reboot; a predictable name the supervisor tears down before each use (its owner is not checked)',
    (
        'src/dev_lab/supervise/loop.py',
        'BLE001',
        'except Exception as exc:',
    ): 'the supervisor loop isolates each component check: whatever a check raises becomes a CRITICAL '
    'anomaly naming the type, so one faulty component cannot stop supervision of the rest',
    (
        'src/dev_lab/supervise/remedy.py',
        'BLE001',
        'except Exception as exc:',
    ): 'a component-supplied remedy handler may raise anything; the failure is reported as the step '
    'outcome so the remedy ladder can escalate rather than the supervisor dying',
    (
        'src/dev_lab/dev/quantity_values.py',
        'BLE001',
        'except Exception:',
    ): 'folding every pint failure into one answer IS the contract; one typo must not crash the scan',
    (
        'tests/test_dev_hpc_records.py',
        'C901',
        'def __call__(self, command: str, stdin: str | None = None) -> str:',
    ): 'the fake cluster answers one branch per verb; splitting it hides which verbs the flow sends',
    (
        'tests/test_dev_hpc_records.py',
        'PLR0911',
        'def __call__(self, command: str, stdin: str | None = None) -> str:',
    ): 'the same fake: one return per verb it answers',
    (
        'tests/test_dev_hpc_records.py',
        'PLR0912',
        'def __call__(self, command: str, stdin: str | None = None) -> str:',
    ): 'the same fake: one branch per verb it answers',
    (
        'tests/test_arch_hpc_leaves_the_workstation_untouched.py',
        'call-overload',
        'return real_popen(argv, *args, **kw)',
    ): 'the spy forwards whatever Popen was called with; a pass-through cannot restate its overloads',
    (
        'src/dev_lab/dev/units.py',
        'C901',
        'def _python_signatures(text: str) -> Iterator[_Signature]:',
    ): 'one branch per AST node kind read; splitting it hides that the set is exhaustive',
    (
        'src/dev_lab/dev/unit_slices.py',
        'C901',
        'def _read_python(path: str, text: str, tokens: Collection[str], out: _Collector) -> None:',
    ): 'one branch per AST node kind read, and that set IS the slice list; splitting it hides a missing slice',
    (
        'src/dev_lab/dev/unit_slices.py',
        'C901',
        'def _read_binding(',
    ): 'one branch per assignment-target kind, each feeding a different slice; the dispatch is the table',
    (
        'src/dev_lab/dev/unit_slices.py',
        'C901',
        'def _read_rust(path: str, text: str, tokens: Collection[str], out: _Collector) -> None:',
    ): "a lexer's state machine: comment, string and code states in one loop, which is what a lexer is",
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:',
    ): 'a stand-in for maturin: it must ACCEPT the real call and ignore it',
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_run(argv, *args: object, **kwargs: object) -> subprocess.CompletedProcess:',
    ): 'the same stand-in, in the arm that reads argv and ignores the rest',
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_time_once(probe, shadow, **kwargs: object) -> float:',
    ): 'the ORDER of the arms is the whole subject; the timing arguments are deliberately ignored',
    (
        'tests/test_dev_rules.py',
        'S607',
        "['git', '-C', str(tmp_path), 'init'],",
    ): 'git through PATH in a scratch checkout the test builds; an absolute path is wrong on every box',
    (
        'tests/test_dev_rules.py',
        'S607',
        "['git', '-C', str(tmp_path), 'add', '-A'],",
    ): 'the same scratch checkout, staging the files the guard is then asked to read',
    (
        'tests/test_dev_collectscope.py',
        'S607',
        "['git', '-C', str(root), *arguments],",
    ): 'git through PATH building the scratch checkouts the local-name reader is then asked to read',
    (
        'tests/test_dev_purge.py',
        'S607',
        "subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)",
    ): 'git through PATH building the scratch checkout the purge door is then asked to delete from',
    (
        'tests/test_dev_purge.py',
        'S607',
        "subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(keep.parent)], check=True, capture_output=True)",
    ): "Windows' own cmd through PATH planting the junction the purge door must refuse to follow",
    (
        'src/dev_lab/dev/accountsweep.py',
        'S607',
        "['crontab', '-l'],",
    ): "the account's own crontab through its PATH: this file is streamed, stdlib only, to a cluster account whose "
    'crontab lives at no path the workstation can know',
    (
        'src/dev_lab/dev/githooks/inprocess.py',
        'BLE001',
        'except Exception:',
    ): 'a hook row run in the runner`s interpreter must end as the subprocess would: an uncaught exception of any '
    'type is the interpreter`s exit 1 with its traceback, and the next row still runs',
    (
        'src/dev_lab/dev/branchnotices.py',
        'PLC0415',
        'from dev_lab.dev.forgepulls import pr_list',
    ): 'branchnotices runs inside git hooks on every commit and push; the forge client is read only on a '
    'cache miss, so the network leaf is imported there and a cache hit costs no import',
    (
        'src/dev_lab/dev/branchnotices.py',
        'PLC0415',
        'from dev_lab.dev.forgeclient import client_for',
    ): 'the same hook-latency reason: the client is built only on a cache miss, inside the bounded reader thread',
    (
        'src/dev_lab/dev/branchnotices.py',
        'BLE001',
        'except Exception:',
    ): 'the forge read runs in a daemon thread under a deadline beside a git verb; a notice must never fail '
    'the verb, and the forge client raises several unrelated types (network, JSON, auth)',
    (
        'src/dev_lab/dev/branchnotices.py',
        'S110',
        'except Exception:',
    ): 'the same thread: the failure is silent ON PURPOSE -- no notice is shown, and the next verb asks again',
    (
        'src/dev_lab/dev/branchnotices.py',
        'BLE001',
        'except (Exception, SystemExit):',
    ): 'the hook entry point: whatever the report raises, including argparse SystemExit on a bad flag, the '
    'hook exits 0, because a notice must never fail a git verb (test_main_exits_zero_whatever_happens)',
    (
        'src/dev_lab/dev/branchnotices.py',
        'S110',
        'except (Exception, SystemExit):',
    ): 'the same entry point: nothing is printed on failure because the hook line is informational only',
    (
        'src/dev_lab/dev/forgenotice.py',
        'PLC0415',
        'from dev_lab.dev.forgepulls import Marker, comment_list, marker',
    ): 'forgenotice is imported by the hook-path branchnotices and must stay a leaf at import; the forge '
    'modules load only when a notice is actually read from a PR comment',
    (
        'src/dev_lab/dev/forgenotice.py',
        'PLC0415',
        'from dev_lab.dev.forgepulls import pr_list',
    ): 'the same leaf-at-import reason: the PR list is read only by the CLI path that needs it',
    (
        'src/dev_lab/dev/forgenotice.py',
        'PLC0415',
        'from dev_lab.dev.forgeclient import client_for',
    ): 'the same leaf-at-import reason: the client is built only by the CLI entry point',
    (
        'src/dev_lab/dev/forgenotice.py',
        'PLC0415',
        'from dev_lab.dev.forgefailure import ForgeCallFailed',
    ): 'the same leaf-at-import reason: a forge failure is caught only by the CLI entry point',
    (
        'src/dev_lab/dev/forgenotice.py',
        'PLC0415',
        'from dev_lab.dev.lanepolicy import load_policy',
    ): 'the same leaf-at-import reason: the lane policy is read only by the CLI entry point',
    (
        'src/dev_lab/dev/hookdispatch.py',
        'BLE001',
        'except Exception:',
    ): "a crashed hook handler is one stderr line, never the dispatcher's crash: every other row still answers",
    (
        'src/dev_lab/dev/hookdispatch.py',
        'override',
        'def encoding(self) -> str:',
    ): "a routed stream's encoding is its calling thread's target's, so it is a property where typeshed has a field",
    (
        'src/dev_lab/dev/machineguard.py',
        'PLC0415',
        'from dev_lab.dev.venvpath import running_interpreter',
    ): 'deferred: the machine-file guard imports nothing heavy on the hook path; only the rendered door text needs it',
    (
        'src/dev_lab/dev/toolrelease.py',
        'S310',
        "return urllib.request.Request(url, headers={'User-Agent': USER_AGENT})",
    ): "the URL is a pinned release's https download URL from the module's own table, never input",
    (
        'src/dev_lab/dev/toolrelease.py',
        'arg-type',
        'shutil.copyfileobj(body, out)',
    ): "urlopen's answer is a binary file object; typeshed types it as the union it opens",
    (
        'src/dev_lab/dev/toolrelease.py',
        'attr-defined',
        "with answer as body, to.open('wb') as out:",
    ): "urlopen's answer is a context manager at runtime; typeshed's union lacks it",
    (
        'src/dev_lab/dev/agenthooks/__init__.py',
        'PLC0415',
        'from dev_lab.dev.hook_adoption import HookAdoption, render',
    ): 'hook_adoption sits ABOVE this hook-path leaf (it imports the deny table); only --family-rules reads it',
    (
        'src/dev_lab/dev/bringup.py',
        'PLC0415',
        'from dev_lab.dev import devhost',
    ): 'devhost imports bringup to wire its verb, so a module-scope import back is a cycle; walls() reads its door',
    (
        'src/dev_lab/dev/devhostadmit.py',
        'PLC0415',
        'from dev_lab.dev.planrunoffer import offered',
    ): 'planrunpreflight reads devhost, which wires this verb, and planrunoffer imports planrunpreflight names: a '
    'module-scope import is a cycle whenever planrunpreflight is imported first; only the live admit reads it',
    (
        'src/dev_lab/dev/testtemp.py',
        'PLC0415',
        'import pytest',
    ): 'script suites import this module where pytest is not installed; only the --basetemp refusal raises its error',
    (
        'src/dev_lab/dev/uvrelease.py',
        'PLR2004',
        'if not words or len(words[0]) != 64:',
    ): 'a sha256 is 64 hex digits: the length IS the format being checked',
    (
        'src/dev_lab/dev/uvrelease.py',
        'S310',
        'with urllib.request.urlopen(toolrelease.request(url), timeout=60) as body:',
    ): "the URL is the pinned uv release's https .sha256 URL from uv.toml's own table, never input",
    (
        'tests/test_dev_forgewaves.py',
        'E731',
        'send = lambda _t, r: calls.append(r) or (0, _STATUS)',
    ): 'a one-line recording fake handed to the code under test',
    (
        'tests/test_dev_toolrelease.py',
        'arg-type',
        'raise urllib.error.HTTPError(url, 403, reason, None, None)',
    ): 'the fake refusal needs no headers or body; the code under test reads only the status',
    (
        'tests/test_dev_toolrelease.py',
        'attr-defined',
        "seen.append(req.get_header('User-agent'))",
    ): 'the fake opener receives the Request the code built; typeshed types it as str | Request',
}

_NOQA = re.compile(r'\bnoqa\b\s*:?\s*([^#]*)')
_TYPE_IGNORE = re.compile(r'\btype\s*:\s*ignore\s*(?:\[([^\]]*)\])?')
_PRAGMA = re.compile(r'\bpragma\s*:\s*no\s+cover\b')
_RULE_CODE = re.compile(r'\b[A-Z]{1,6}[0-9]{3,4}\b')


def _codes(comment: str) -> tuple[str, ...]:
    """Every rule code a comment silences. A marker naming none silences EVERYTHING: ``...:ALL``."""
    out: list[str] = []
    noqa = _NOQA.search(comment)
    if noqa is not None:
        out.extend(_RULE_CODE.findall((noqa.group(1) or '').split('--')[0]) or ['noqa:ALL'])
    ignore = _TYPE_IGNORE.search(comment)
    if ignore is not None:
        out.extend(re.findall(r'[\w-]+', ignore.group(1) or '') or ['type-ignore:ALL'])
    if _PRAGMA.search(comment) is not None:
        out.append('no-cover')
    return tuple(out)


def python_sites(paths: tuple[Path, ...]) -> tuple[Site, ...]:
    """Every suppression in *paths*, read from real COMMENT tokens -- pure over its argument.

    Tokenized rather than grepped on purpose: a marker inside a string literal is data, not a
    suppression, and this module is itself inside the corpus it scans.
    """
    out: list[Site] = []
    for path in paths:
        text = path.read_text(encoding='utf-8')
        lines = text.splitlines()
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.COMMENT:
                continue
            codes = _codes(token.string)
            if not codes:
                continue
            anchor = lines[token.start[0] - 1][: token.start[1]].strip() or token.string.strip()
            out.extend((corpus_key(path), code, anchor) for code in codes)
    return tuple(out)


def pyproject_sites(pyproject: Path) -> tuple[Site, ...]:
    """Every per-file ``ruff`` ignore -- a suppression that appears in no Python file at all."""
    lint = tomllib.loads(pyproject.read_text(encoding='utf-8')).get('tool', {}).get('ruff', {}).get('lint', {})
    tables = (lint.get('per-file-ignores') or {}, lint.get('extend-per-file-ignores') or {})
    return tuple((corpus_key(pyproject), code, glob) for t in tables for glob, codes in t.items() for code in codes)


def undeclared_and_orphaned(sites: tuple[Site, ...], declared: dict[Site, str]) -> tuple[str, ...]:
    """BOTH SIDES OF THE RATCHET, plus the empty-reason refusal -- pure over its arguments."""
    live, pinned = set(sites), set(declared)
    problems = [
        f'UNDECLARED suppression {s} -- add it with the reason it is allowed to exist' for s in sorted(live - pinned)
    ]
    problems += [
        f'ORPHANED waiver {s} -- the suppression is gone; delete the entry in the same edit'
        for s in sorted(pinned - live)
    ]
    problems += [
        f'REASONLESS waiver {s} -- a bare entry says a suppression exists, not why it may'
        for s, why in sorted(declared.items())
        if not why.strip()
    ]
    return tuple(problems)


def subjects(sites: tuple[Site, ...], declared: dict[Site, str]) -> set[Site]:
    """The suppression tuples the ratchet's red names: undeclared, orphaned and reasonless."""
    return set(sites) ^ set(declared) | {site for site, why in declared.items() if not why.strip()}


def test_every_suppression_is_declared_and_every_declaration_is_used() -> None:
    """THE CHECK, over this repo's source, its suite and its ``pyproject.toml``."""
    source, suite = source_modules(), suite_modules()
    assert_floor(len(source), SOURCE_FLOOR, 'suppression (src)')
    assert_floor(len(suite), TEST_FLOOR, 'suppression (tests)')
    sites = python_sites(source + suite) + pyproject_sites(ROOT / 'pyproject.toml')
    problems = undeclared_and_orphaned(sites, ALLOWED)
    assert problems == (), (
        'the suppression ratchet moved:\n  ' + '\n  '.join(problems) + '\n' + subject_lines(subjects(sites, ALLOWED))
    )


def test_a_planted_suppression_and_a_planted_orphan_are_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, BOTH DIRECTIONS, through the REAL scanner, past a clean file."""
    marker = '# ' + 'noqa: F401'
    dirty = tmp_path / 'dirty.py'
    dirty.write_text(f'import os  {marker}\n', encoding='utf-8')
    quoted = tmp_path / 'quoted.py'
    quoted.write_text(f'MARKER = "{marker}"\n', encoding='utf-8')
    found = python_sites((dirty, quoted))
    assert found == (('dirty.py', 'F401', 'import os'),), f'the comment counts and the string literal does not: {found}'

    undeclared = undeclared_and_orphaned(found, {})
    assert any('UNDECLARED' in p for p in undeclared), undeclared

    orphaned = undeclared_and_orphaned((), {('gone.py', 'F401', 'import os'): 'stale'})
    assert any('ORPHANED' in p for p in orphaned), orphaned

    reasonless = undeclared_and_orphaned(found, {found[0]: '   '})
    assert any('REASONLESS' in p for p in reasonless), reasonless
    assert undeclared_and_orphaned(found, {found[0]: 'a real reason'}) == ()


def test_a_planted_per_file_ignore_and_a_planted_bare_marker_are_seen(tmp_path: Path) -> None:
    """The two hiding places a comment scan of ``src/`` alone would miss."""
    cfg = tmp_path / 'pyproject.toml'
    cfg.write_text('[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["F401", "E501"]\n', encoding='utf-8')
    assert pyproject_sites(cfg) == (('pyproject.toml', 'F401', 'tests/*'), ('pyproject.toml', 'E501', 'tests/*'))
    live = pyproject_sites(ROOT / 'pyproject.toml')
    assert {glob for _, _, glob in live} == {'tests/**'}, f'a second per-file glob appeared: {live}'
    assert len(live) == 10, f'measured 2026-09-17, when the 58-selector set was adopted: {live}'

    bare = tmp_path / 'bare.py'
    bare.write_text(
        'x: int = "s"  # ' + 'type: ignore\ndef f():  # ' + 'pragma: no cover\n    ...\n',
        encoding='utf-8',
    )
    codes = {code for _, code, _ in python_sites((bare,))}
    assert codes == {'type-ignore:ALL', 'no-cover'}, codes


def test_the_suppression_red_names_each_moved_tuple_as_a_subject() -> None:
    """THE PLANTED CONTROL for the fingerprint: undeclared, orphaned and reasonless tuples are each a subject."""
    new, gone, bare, kept = ('a.py', 'F401', 'x'), ('b.py', 'E501', 'y'), ('c.py', 'S101', 'z'), ('d.py', 'D1', 'w')
    assert subjects_of(subject_lines(subjects((new, bare, kept), {gone: 'r', bare: ' ', kept: 'r'}))) == {
        str(new),
        str(gone),
        str(bare),
    }
    assert subjects((kept,), {kept: 'r'}) == set()
