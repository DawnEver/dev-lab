// WHICH ENVIRONMENT A NEW LAUNCH TAKES (dev-lab #641): the ONE rule, shipped once and required by every JS door.
// Installed beside the hook launcher and the deny engine (dev_lab.dev.agent_guard); `node venv_resolver.js --shell`
// renders the POSIX twin that githooks/with-venv.sh carries between its markers, and that the git hook shims and the
// remote deploy lines embed (dev_lab.dev.venvpointer.shell_function reads it there). The Python twin is
// dev_lab.dev.venvpointer.current; tests/test_dev_venv_resolver.py holds all three to one answer.
//
// THE RULE (user ruling 2026-11-20): <root>/.venv is the pointer -- a link (junction/symlink) to the published
// <root>/.venvs/<name>, or a plain environment directory never published. The answer is .venv RESOLVED, so a launch
// holds the environment itself and a later swap of the link leaves it running; a missing .venv answers <root>/.venv,
// so every miss names it (the door: dev_lab.dev.dep --bootstrap).
'use strict';
const fs = require('fs');
const path = require('path');

const POINTER = '.venv';
const HOME = '.venvs';
//: Both interpreter layouts, probed in this order (dev_lab.dev.venvpath.CANDIDATE_RELATIVE_PATHS).
const TAILS = [['Scripts', 'python.exe'], ['bin', 'python']];

/** The environment a NEW launch in checkout `root` runs from. */
function currentEnv(root) {
  const link = path.join(root, POINTER);
  try {
    return fs.realpathSync.native(link);
  } catch {
    return link;
  }
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
  return (
    `_current_env() { if [ -d "$1/${POINTER}" ]; then (cd -P "$1/${POINTER}" && pwd -P); ` +
    `else echo "$1/${POINTER}"; fi; }`
  );
}

module.exports = { HOME, POINTER, TAILS, currentEnv, interpreter, shellFunction };

if (require.main === module) {
  const [verb, root] = process.argv.slice(2);
  if (verb === '--shell') process.stdout.write(`${shellFunction()}\n`);
  else if (verb === '--current' && root) process.stdout.write(`${currentEnv(root)}\n`);
  else {
    process.stderr.write('usage: venv_resolver.js --shell | --current ROOT\n');
    process.exit(2);
  }
}
