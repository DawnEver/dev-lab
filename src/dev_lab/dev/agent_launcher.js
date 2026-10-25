// Run a Python module or script with THIS checkout's interpreter, on every platform.
// Launcher shipped by dev-lab: dev_lab.dev.agent_guard (a repo's own launcher at this path is kept).
//
// A bare `python` in a hook resolves through PATH, and on Windows that is the Microsoft Store
// alias. The interpreter is the project's own `.venv`, or the main checkout's when a linked
// worktree has none. No interpreter: one line on stderr and exit 0 -- a hook that cannot run
// must not block the session it was meant to inform.
'use strict';
const { spawnSync, execFileSync } = require('child_process');
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
const run = spawnSync(python, process.argv.slice(2), { stdio: 'inherit' });
process.exit(run.status === null ? 1 : run.status);
