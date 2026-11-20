// Run a Python module or script with THIS checkout's interpreter, on every platform.
// Launcher shipped by dev-lab: dev_lab.dev.agent_guard (a repo's own launcher at this path is kept).
//
// A bare `python` in a hook resolves through PATH, and on Windows that is the Microsoft Store
// alias. The interpreter is the project's own current environment (venv_resolver.js), or the main checkout's when a linked
// worktree has none. No interpreter: one line on stderr and exit 0 -- a hook that cannot run
// must not block the session it was meant to inform.
//
// A STALE VENV NAMES ITS FIX (every-wall-teaches, 2026-11-13): a hook module the venv's dev-lab predates fails
// `No module named dev_lab...`. When the installed dev-lab commit is not the one this checkout's uv.lock pins,
// that is ONE line naming both shas and the bootstrap door, one walls-ledger line (the shape of
// dev_lab.dev.walls.record -- the venv may not hold that module either), and exit 0.
//
// A HOOK THAT CANNOT START NEVER BLOCKS (dev-lab #639): a child's argparse usage exit (2 with `usage:` or
// `error: argument` / `invalid choice` / `unrecognized arguments`) or a missing module is a wiring fault, not a
// decision -- passed through, exit 2 blocked every prompt and looped every Stop. It becomes one line naming the fix
// and exit 0, whether or not the venv is behind its lock. A deliberate refusal (exit 2 naming its rule) still blocks.
//
// ONE RESOLVER (dev-lab #641): the environment is venv_resolver.js's, installed beside this launcher. An upgrade
// publishes a new environment beside the live one, so a launch never waits for one and nothing is replayed here.
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { interpreter } = require('./venv_resolver.js');

// Facts are shared with Python and installed unchanged beside this launcher.
function nativeSession(env) {
  let catalog;
  try {
    catalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'native_session.json'), 'utf8'));
    if (!Number.isInteger(catalog.max_length) || catalog.max_length <= 0 ||
        typeof catalog.punctuation !== 'string' || !Array.isArray(catalog.harnesses) ||
        !catalog.harnesses.length || !catalog.harnesses.every((row) =>
          typeof row.primary === 'string' && Array.isArray(row.auxiliary) &&
          row.auxiliary.every((field) => typeof field === 'string'))) throw new Error('schema');
  } catch {
    throw new Error('native session catalog is missing or invalid. Door: restore the declared dev-lab installation.');
  }
  const declared = catalog.harnesses.filter((row) =>
    [row.primary, ...row.auxiliary].some((field) => Object.hasOwn(env, field)));
  if (!declared.length) return '';
  if (declared.length !== 1) {
    throw new Error('ambiguous native session harnesses. Door: run from exactly one native agent harness.');
  }
  const primary = declared[0].primary;
  const value = env[primary];
  const chars = typeof value === 'string' ? Array.from(value) : [];
  if (!chars.length || chars.length > catalog.max_length || !chars.every((char) =>
      /^[\p{L}\p{N}]$/u.test(char) || catalog.punctuation.includes(char))) {
    throw new Error(`native session ${primary} is not a session id or is missing. Door: restore the native harness identity.`);
  }
  return value;
}

let session;
try {
  session = nativeSession(process.env);
} catch (failed) {
  process.stderr.write(`[hook] ${failed.message}\n`);
  process.exit(1);
}

// The main checkout is asked of git only when it is needed -- this checkout has no interpreter, or a fault names the
// bootstrap door (HOOK-UNDER-FIVE-SECONDS, D24): a git start on every hook cost ~80 ms of the event's five seconds.
const roots = [process.env.CLAUDE_PROJECT_DIR || process.cwd()];
function withMain() {
  try {
    const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: roots[0],
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    roots.push(path.dirname(common));
  } catch {}
  return roots;
}

const python = interpreter(roots[0]) || withMain().slice(1).map(interpreter).find(Boolean);
if (!python) {
  process.stderr.write(`[hook] skipped ${process.argv.slice(2).join(' ')}: no .venv interpreter\n`);
  process.exit(0);
}

const args = process.argv.slice(2);
const run = spawnSync(python, args, { stdio: ['inherit', 'inherit', 'pipe'] });
const stderr = run.stderr ? run.stderr.toString('utf8') : '';
const fault = wiringFault(run.status, stderr);
if (!fault) {
  process.stderr.write(stderr);
  process.exit(run.status === null ? 1 : run.status);
}
const main = (roots.length > 1 ? roots : withMain())[roots.length - 1];
const behind = staleness(python);
const door = `${python} -m dev_lab.dev.dep --bootstrap ${main}`;
process.stderr.write(
  behind
    ? `[hook] ${fault} missing: installed dev-lab ${behind.installed.slice(0, 10)} is behind the lock's ` +
        `${behind.locked.slice(0, 10)} -- run: ${door} ` +
        `(it publishes a new environment beside this one; the next launch takes it)\n`
    :`[hook] ${args.join(' ')} could not start (${fault}); not a refusal, so it passed -- run: ${door} ` +
        `(if the installed dev-lab is current, the hook row names what dev-lab does not ship: re-render the wiring ` +
        `with ${python} -m dev_lab.dev.agent_guard --install)\n`,
);
if (behind) recordWall(main, args);
process.exit(0);

// What kept the child from starting -- a missing module, or argparse refusing its argv (exit 2 with its usage or an
// `error: argument` line) -- else null: a decision, passed through.
function wiringFault(status, text) {
  if (status === 0 || status === null) return null;
  const module = /No module named '?([\w.]+)/.exec(text);
  if (module) return module[1];
  const usage = status === 2 && /^usage: |error: (?:argument |unrecognized arguments|the following arguments)/m;
  if (!usage || !usage.test(text)) return null;
  const verb = /(?:invalid choice|unrecognized arguments): '?([\w-]+)/.exec(text);
  return verb ? verb[1] : 'its arguments';
}

// {installed, locked}: the venv's dev-lab commit and the one uv.lock pins, when both are known and differ; else null.
function staleness(python) {
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
  const probe = spawnSync(python, [
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
      session,
      ts: now.toISOString(),
    };
    fs.appendFileSync(path.join(dir, 'walls.jsonl'), `${JSON.stringify(line)}\n`);
  } catch {}
}
