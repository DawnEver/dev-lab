// WHICH ENVIRONMENT A NEW LAUNCH TAKES (dev-lab #641): the ONE rule, shipped once and required by every JS door.
// Installed beside the hook launcher and the deny engine (dev_lab.dev.agent_guard); `node venv_resolver.js --shell`
// renders the POSIX twin that githooks/with-venv.sh carries between its markers, and that the git hook shims and the
// remote deploy lines embed (dev_lab.dev.venvpointer.shell_function reads it there). The Python twin is
// dev_lab.dev.venvpointer.current; tests/test_dev_venv_resolver.py holds all three to one answer on 20 layouts.
//
// THE RULE: the first line of <root>/.venv-current, surrounding whitespace removed, names a directory under
// <root>/.venvs/ -- a name with no `/`, `\` or `:` that is not `.` or `..`; when it names none, <root>/.venv.
// The pointer is replaced atomically, so a reader sees the old name or the new one; Windows refuses the open in
// the instant of the swap, and that is retried, never read as absent.
'use strict';
const fs = require('fs');
const path = require('path');

const POINTER = '.venv-current';
const HOME = '.venvs';
const ALIAS = '.venv';
const READ_TRIES = 50;
//: Both interpreter layouts, probed in this order (dev_lab.dev.venvpath.CANDIDATE_RELATIVE_PATHS).
const TAILS = [['Scripts', 'python.exe'], ['bin', 'python']];

function valid(name) {
  return Boolean(name) && name !== '.' && name !== '..' && !/[/\\:]/.test(name);
}

function readPointer(file) {
  for (let i = 0; i < READ_TRIES; i += 1) {
    try {
      return fs.readFileSync(file, 'utf8').split('\n')[0].trim();
    } catch (failed) {
      if (failed.code !== 'EPERM' && failed.code !== 'EBUSY' && failed.code !== 'EACCES') return '';
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
    }
  }
  return '';
}

/** The environment a NEW launch in checkout `root` runs from. */
function currentEnv(root) {
  const name = readPointer(path.join(root, POINTER));
  if (valid(name)) {
    const env = path.join(root, HOME, name);
    try {
      if (fs.statSync(env).isDirectory()) return env;
    } catch {}
  }
  return path.join(root, ALIAS);
}

/** The first existing interpreter of `root`'s current environment, else null. */
function interpreter(root) {
  const env = currentEnv(root);
  for (const tail of TAILS) {
    const found = path.join(env, ...tail);
    if (fs.existsSync(found)) return found;
  }
  return null;
}

/** The POSIX twin: one line defining `_current_env ROOT`, which prints the same answer as currentEnv. It holds no
 * `%`: a crontab line embeds it, and cron reads an unescaped `%` as a newline. */
function shellFunction() {
  const strip = "sed 's/^[[:space:]]*//;s/[[:space:]]*$//'";
  return (
    '_current_env() { _n=""; ' +
    `if [ -f "$1/${POINTER}" ]; then _n="$(head -n 1 "$1/${POINTER}" | ${strip})"; fi; ` +
    `case "$_n" in (""|.|..|*/*|*\\\\*|*:*) echo "$1/${ALIAS}" ;; ` +
    `(*) if [ -d "$1/${HOME}/$_n" ]; then echo "$1/${HOME}/$_n"; else echo "$1/${ALIAS}"; fi ;; ` +
    'esac; }'
  );
}

module.exports = { ALIAS, HOME, POINTER, TAILS, currentEnv, interpreter, shellFunction };

if (require.main === module) {
  const [verb, root] = process.argv.slice(2);
  if (verb === '--shell') process.stdout.write(`${shellFunction()}\n`);
  else if (verb === '--current' && root) process.stdout.write(`${currentEnv(root)}\n`);
  else {
    process.stderr.write('usage: venv_resolver.js --shell | --current ROOT\n');
    process.exit(2);
  }
}
