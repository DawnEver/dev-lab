// Run a Python module or script with THIS checkout's interpreter, on every platform.
// Launcher shipped by dev-lab: dev_lab.dev.agent_guard (a repo's own launcher at this path is kept).
//
// A bare `python` in a hook resolves through PATH, and on Windows that is the Microsoft Store
// alias. The interpreter is the project's own `.venv`, or the main checkout's when a linked
// worktree has none. No interpreter: one line on stderr and exit 0 -- a hook that cannot run
// must not block the session it was meant to inform.
//
// A STALE VENV NAMES ITS FIX (every-wall-teaches, 2026-11-13): a hook module the venv's dev-lab predates fails
// `No module named dev_lab...`. When the installed dev-lab commit is not the one this checkout's uv.lock pins,
// that is ONE line naming both shas and the bootstrap door, one walls-ledger line (the shape of
// dev_lab.dev.walls.record -- the venv may not hold that module either), and exit 0. A missing module from a
// venv that matches its lock is a real bug: its stderr and exit code pass through untouched.
//
// A QUEUED VENV UPDATE RUNS HERE (2026-11-14): `dep --bootstrap ROOT --when-free` that found the venv held left
// its argv in <venv>/dev-lab-pending-bootstrap.json (dev_lab.dev._dep_pending). This launcher runs from OUTSIDE
// the venv on every tool call, so it is the first door to see the venv free: it replays the request before its
// own hook, at most once a minute while the venv stays held. One launcher claims it (an exclusive lock file); its concurrent siblings wait for the claim to go
// before starting their interpreter, so none runs from a venv mid-update. Still held: dep re-queues and exits 0.
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const roots = [process.env.CLAUDE_PROJECT_DIR || process.cwd()];
try {
  const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
    cwd: roots[0],
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  roots.push(path.dirname(common));
} catch {}

const tail = process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'];
const python = roots.map((r) => path.join(r, '.venv', ...tail)).find((p) => fs.existsSync(p));
if (!python) {
  process.stderr.write(`[hook] skipped ${process.argv.slice(2).join(' ')}: no .venv interpreter\n`);
  process.exit(0);
}

performPendingUpdate(python);

const args = process.argv.slice(2);
const run = spawnSync(python, args, { stdio: ['inherit', 'inherit', 'pipe'] });
const stderr = run.stderr ? run.stderr.toString('utf8') : '';
const missing = run.status !== 0 && /No module named '?(dev_lab[\w.]*)/.exec(stderr);
const behind = missing && staleness(python);
if (!behind) {
  process.stderr.write(stderr);
  process.exit(run.status === null ? 1 : run.status);
}
const main = roots[roots.length - 1];
process.stderr.write(
  `[hook] ${missing[1]} missing: installed dev-lab ${behind.installed.slice(0, 10)} is behind the lock's ` +
    `${behind.locked.slice(0, 10)} -- run: ${python} -m dev_lab.dev.dep --bootstrap ${main}\n`,
);
recordWall(main, args);
process.exit(0);

// {installed, locked}: the venv's dev-lab commit and the one uv.lock pins, when both are known and differ; else null.
function staleness(interpreter) {
  let locked = '';
  for (const root of roots) {
    try {
      const lock = fs.readFileSync(path.join(root, 'uv.lock'), 'utf8');
      const pin = /\nname = "dev-lab"\r?\n(?:[^\n]+\n)*?source = \{ git = "[^"#]*#([0-9a-f]{7,40})"/.exec(`\n${lock}`);
      if (pin) {
        locked = pin[1];
        break;
      }
    } catch {}
  }
  if (!locked) return null;
  const probe = spawnSync(interpreter, [
    '-c',
    [
      'import json, importlib.metadata as m',
      'try: d = m.distribution("dev-lab").read_text("direct_url.json")',
      'except Exception: d = None',
      'print(json.loads(d).get("vcs_info", {}).get("commit_id", "") if d else "")',
    ].join('\n'),
  ]);
  const installed = probe.status === 0 ? probe.stdout.toString('utf8').trim() : '';
  return installed && installed !== locked ? { installed, locked } : null;
}

// One WALLS-ARE-RECORDED line in <main>/output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl (local date, as datedlog).
function recordWall(root, argv) {
  try {
    const now = new Date();
    const two = (n) => String(n).padStart(2, '0');
    const day = [two(now.getFullYear() % 100), two(now.getMonth() + 1), two(now.getDate())];
    const dir = path.join(root, 'output', 'logs', ...day, 'walls');
    fs.mkdirSync(dir, { recursive: true });
    const line = {
      command_sha256: crypto.createHash('sha256').update(argv.join(' ')).digest('hex').slice(0, 16),
      remedy_present: true,
      rule: 'VENV-FOLLOWS-THE-LOCK',
      session: process.env.CLAUDE_CODE_SESSION_ID || '',
      ts: now.toISOString(),
    };
    fs.appendFileSync(path.join(dir, 'walls.jsonl'), `${JSON.stringify(line)}\n`);
  } catch {}
}

// Whether *file* was written within REPLAY_EVERY_MS: a held venv is asked again at most once a minute, not per hook.
function recent(file) {
  try {
    return Date.now() - fs.statSync(file).mtimeMs < Number(process.env.DEV_LAB_REPLAY_EVERY_MS || 60 * 1000);
  } catch {
    return false;
  }
}

// Replay a queued `dep --when-free` request of the venv *interpreter* runs from; wait while a sibling replays it.
function performPendingUpdate(interpreter) {
  const venv = path.dirname(path.dirname(interpreter));
  const request = path.join(venv, 'dev-lab-pending-bootstrap.json');
  const claim = `${request}.claim`;
  const pause = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  const deadline = Date.now() + 15 * 60 * 1000; // a bootstrap's wall; a claim older than this is a dead claimer's
  while (fs.existsSync(request) || fs.existsSync(claim)) {
    if (!fs.existsSync(claim) && recent(request)) return; // asked or re-queued under a minute ago: still held
    let fd;
    try {
      fd = fs.openSync(claim, 'wx');
    } catch {
      try {
        if (Date.now() - fs.statSync(claim).mtimeMs > 15 * 60 * 1000) fs.unlinkSync(claim);
      } catch {}
      if (Date.now() > deadline) return;
      pause(500);
      continue;
    }
    try {
      fs.closeSync(fd);
      let argv;
      try {
        argv = JSON.parse(fs.readFileSync(request, 'utf8')).argv;
      } catch {
        return; // answered by the claimer before us, or unreadable: nothing to replay
      }
      if (!Array.isArray(argv)) return;
      process.stderr.write(`[hook] a queued venv update of ${venv} runs first: dep ${argv.join(' ')}
`);
      const done = spawnSync(interpreter, ['-m', 'dev_lab.dev.dep', ...argv.map(String), '--when-free'], {
        stdio: ['ignore', 2, 2], // a hook's stdout is its answer to Claude Code
      });
      if (done.status !== 0) fs.rmSync(request, { force: true }); // ran and failed: said once, not on every call
      return;
    } finally {
      fs.rmSync(claim, { force: true });
    }
  }
}
