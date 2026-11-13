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
