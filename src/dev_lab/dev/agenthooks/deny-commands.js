#!/usr/bin/env node
// Engine shipped by lab-commons: dev_lab.dev.agenthooks (deny-commands). INSTALLED BY
// `python -m dev_lab.dev.agent_guard --install`, never hand-copied -- `agent_guard` reads the
// line above to tell an installed engine from a stale one from a hand-written file in the same
// slot. Editing this copy in a consumer repo makes it STALE, and the next verify says so.
/**
 * Generic PreToolUse command-deny engine. Knows NOTHING about git or pytest: every denied shape
 * is a rule in the JSON file passed as argv[2] (`.claude/hooks/deny-rules.json`), so adding or
 * retiring a rule is a data change, never an engine change.
 *
 * A rule is {name, pattern, matches?, allow?, scope?, severity?, asks?, reason}. `scope: 'subagent'` judges the rule only
 * when the payload carries a non-empty `agent_id`. `severity: 'hint'` never denies: the call runs and the
 * reason reaches the agent as `additionalContext` -- unless a refusing rule also fires, which wins. `pattern` (JS regex source) denies a
 * command it matches, unless `allow` (regex source) also matches -- the sanctioned spelling.
 * `reason` is the rewrite hint shown to the agent; `{root}` in it expands to the tool call's cwd, and `{python}`
 * (or a door's `<venv python>`) to the target checkout's interpreter by ABSOLUTE path. `asks` names the Python
 * module that judges a call the pattern only prefilters (A ROW WHOSE JUDGE IS A MODULE, below).
 *
 * ================================ WHAT IS MATCHED, AND WHY ================================
 *
 * Until 2026-09-01 every rule was a regex over the RAW PAYLOAD -- the whole Bash `command` string,
 * prose and all. That made each rule re-invent "is this token a command or is it text", and they
 * answered differently: `bare-pytest` and `pip-into-the-shared-venv` carried a hand-written
 * `(?:^|[;&|(\n])\s*` anchor; `uv-mutates-the-shared-venv` carried none. The unanchored one
 * therefore fired on the WORDS `uv sync` inside a heredoc that was WRITING DOCUMENTATION -- twice
 * in one session, both times while recording why that rule is right. A guard that refuses the
 * sentence describing it is not strict, it is imprecise, and the fix is precision, not laxity.
 *
 * So the engine now decides ONCE what the shell will actually EXECUTE, and rules are matched
 * against that. `executedTexts` yields two kinds of text and DROPS a third:
 *
 *   SHELL SEGMENT     the command line split on `; && || | & ( ) \n`, with leading `VAR=value`
 *                     assignments stripped. This is a command invocation.
 *   INTERPRETER CODE  the `-c` argument or heredoc body handed to python/node/sh/bash/...
 *                     That text IS executed, so it is scanned, anchored at LINE start -- the
 *                     discriminator the pytest rule already relied on: a line BEGINNING
 *                     `pytest.main(...)` runs pytest, a line reading `import pytest` does not.
 *   (dropped)         a heredoc body consumed by a SINK -- `cat`, `tee`, or any body whose
 *                     opening segment redirects to a file. That is DATA, and scanning it is the
 *                     defect this design removes.
 *
 * THE EVASION THIS MUST NOT REOPEN, measured 2026-08-22: an agent ran pytest through
 * `python - <<EOF ... pytest.main([...]) ... EOF` and disclosed it. A heredoc body is NOT
 * automatically inert -- it is inert only when its CONSUMER is a sink. That is why the
 * classification is by consumer rather than by syntax, and why "stop scanning heredocs" would have
 * been the wrong fix. Both directions are pinned by `tests/architecture/gate/test_agent_bash_guard.py`.
 *
 * =============================== WHAT A RULE STILL DECLARES ===============================
 *
 * `matches` says what the pattern NAMES, which is a property of the rule and not of the parser:
 *
 *   'command'  (default) the pattern names the command being run, so it must match at the START
 *              of a segment. `echo "uv sync"` runs echo; `grep -rn "git push"` runs grep.
 *   'line'     the shape spans segments (a value piped into a command): searched in the whole line.
 *   'argument' the pattern names an OPTION and must be found anywhere in the segment, because the
 *              command it qualifies varies: `--force` is forbidden on `git push`, on
 *              `sh with-retry.sh push`, and on anything else that ends up pushing.
 *
 * That split is the one thing a rule still has to say, and it replaces every hand-rolled anchor:
 * a rule that carried its own preceding-context class would be answering a question the engine has
 * already answered, and answering it differently is exactly how the two rules drifted apart.
 *
 * DENY, NOT REWRITE. The hook API's `updatedInput` has a reported regression for Bash
 * (anthropics/claude-code#79321) where the rewrite is silently dropped; a denied call with an
 * exact rewrite hint in the reason is the reliable shape.
 *
 * Fail-open by construction: unparseable stdin, a missing/invalid rules file, or a bad regex in
 * one rule never blocks a tool call -- an engine that can error closed would turn a typo in the
 * data file into a locked session.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');

/** The tools whose `tool_input.command` the shell executes. */
const SHELL_TOOLS = new Set(['Bash', 'PowerShell']);

/** Commands whose heredoc body / `-c` argument is EXECUTED and must therefore be scanned. */
const INTERPRETERS =
  /(?:^|[/\\])(?:python[\w.]*|node|sh|bash|zsh|dash|ksh|ruby|perl|Rscript)(?:\.exe)?$/i;

/** Leading `VAR=value` assignments: shell prefix, not the command word. */
const ENV_PREFIX = /^(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S*)\s+)+/;

/**
 * Commands that RUN ANOTHER COMMAND. `timeout 900 uv sync` invokes both `timeout` and `uv`, so a
 * segment has as many command positions as it has wrappers, and anchoring at the first one alone
 * would miss the second. MEASURED 2026-09-01 while writing this change's tests: with only the
 * env-prefix strip, `timeout 900 uv sync`, `nohup uv sync`, `env uv sync`, `time pytest`,
 * `xargs -n1 git push` and `sudo pip install x` ALL slipped through -- six shapes, found because
 * the row was written before the code and refused to pass.
 */
const WRAPPERS = /^(?:timeout|nohup|time|env|nice|ionice|stdbuf|command|exec|sudo|doas|xargs)$/i;

/**
 * `uv run <command>` is a wrapper too, but its verb is a SECOND token, so `WRAPPERS` cannot name
 * it: matching `uv` alone would also strip `uv sync`/`uv add`/`uv pip`, which are commands in their
 * own right and are exactly what the uv rule must keep seeing. Only the `run` form is a wrapper.
 *
 * MEASURED 2026-09-17: without this, `uv run python - <<PY ... PY` hid its interpreter behind `uv`
 * and the heredoc body was never scanned. A repo whose rules happen to name `uv run` refused that
 * line for an unrelated reason; one whose rules do not (consumer-c, consumer-b) ALLOWED it outright.
 */
const UV_RUN = /^(?:[^\s]*[/\\])?(uvx?)(?:\.exe)?$/i;

/** An argument that belongs to the WRAPPER rather than to the command it runs. */
const WRAPPER_ARG = /^(?:-|\d+(?:\.\d+)?[smhd]?$)/;

/** Shells: a `-c` script handed to one of these is SHELL text, so it has segments of its own. */
const SHELLS = /(?:^|[/\\])(?:sh|bash|zsh|dash|ksh)(?:\.exe)?$/i;

/**
 * Split a shell line at the operators that START a new command. `(` and `)` separate too, so a
 * subshell body is its own segment and `(pytest tests)` is still a pytest invocation.
 *
 * AN OPERATOR INSIDE QUOTES IS TEXT, and so is a backslash-escaped one. MEASURED 2026-10-03: a
 * naive split read `grep -rn "a\|uv run --no-sync" f` as a pipe into a `uv run` command and refused
 * a grep. `"..."` honours backslash escapes, `'...'` honours none -- the shell's own rules.
 */
function segments(line) {
  const out = [];
  let current = '';
  let quote = '';
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (quote) {
      current += ch;
      if (ch === '\\' && quote === '"' && i + 1 < line.length) current += line[++i];
      else if (ch === quote) quote = '';
      continue;
    }
    if (ch === '\\' && i + 1 < line.length) {
      current += ch + line[++i];
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    const two = line.slice(i, i + 2);
    if (two === '||' || two === '&&') {
      out.push(current);
      current = '';
      i += 1;
      continue;
    }
    if (';|&()\n'.includes(ch)) {
      out.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  out.push(current);
  return out;
}

/** The command word of a segment, with env assignments and surrounding quotes dropped. */
function commandWord(segment) {
  const bare = segment.replace(ENV_PREFIX, '').trim();
  const first = bare.split(/\s+/)[0] || '';
  return first.replace(/^["']|["']$/g, '');
}

/**
 * Remove every heredoc body from `cmd`, returning the remaining shell text plus the bodies that
 * are EXECUTED. A body is executed when the segment opening it runs an interpreter and does not
 * redirect to a file; otherwise it is data and is dropped.
 */
function splitHeredocs(cmd) {
  const executed = [];
  const shellBodies = [];
  let rest = '';
  let index = 0;
  const opener = /<<-?\s*(["']?)([A-Za-z_][A-Za-z0-9_]*)\1/g;
  let match;
  while ((match = opener.exec(cmd)) !== null) {
    if (match.index < index) continue;
    const delimiter = match[2];
    const bodyStart = cmd.indexOf('\n', opener.lastIndex);
    if (bodyStart === -1) break;
    const tail = cmd.slice(bodyStart + 1);
    const closer = new RegExp(`^[ \\t]*${delimiter}[ \\t]*$`, 'm');
    const end = tail.search(closer);
    const body = end === -1 ? tail : tail.slice(0, end);
    const bodyEnd = end === -1 ? cmd.length : bodyStart + 1 + end + delimiter.length;

    // The CONSUMER of the body decides what the body is, and nothing else does. A redirection
    // test was written here and then REMOVED as both redundant and wrong: `cat > f <<EOF` is
    // already excluded because `cat` is not an interpreter, while `python <<EOF > out.txt`
    // executes its body exactly as it would without the redirect -- so keying on `>` would have
    // exempted a real evasion route to buy a check that was doing nothing.
    const openingLine = cmd.slice(index, opener.lastIndex).split('\n').pop();
    const opening = segments(openingLine).pop() || openingLine;
    // EVERY command position, not just the first word: `timeout 900 python - <<PY` and
    // `uv run python - <<PY` both run an interpreter, and both read as `timeout`/`uv` at token
    // zero. Asking only `commandWord(opening)` reopened the 2026-08-22 evasion behind any wrapper.
    const consumers = commandPositions(opening).map(commandWord);
    if (consumers.some((word) => INTERPRETERS.test(word))) {
      executed.push(body);
      if (consumers.some((word) => SHELLS.test(word))) shellBodies.push(body);
    }

    rest += cmd.slice(index, opener.lastIndex);
    index = bodyEnd;
    opener.lastIndex = bodyEnd;
  }
  rest += cmd.slice(index);
  return { rest, executed, shellBodies };
}

/** `-c <script>` payloads: executed text, whatever the surrounding quoting. */
function inlineScripts(line) {
  const out = [];
  const re = /(?:^|\s)-c\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))/g;
  let m;
  while ((m = re.exec(line)) !== null) out.push(m[1] ?? m[2] ?? m[3] ?? '');
  return out;
}

/**
 * Interpreter source with the CONTENT of its string literals blanked (quotes and newlines kept), so text a
 * program only carries -- source it writes to a file, a message it prints -- is never read as a call it makes
 * (O48, 2026-11-18: a heredoc writing a file whose text held `rmtree(` was refused RECURSIVE-DELETE).
 * Triple quotes first, then ' " and `; a backslash escapes the next character. A call outside every literal
 * still reads exactly as written.
 */
function withoutStrings(code) {
  let out = '';
  let i = 0;
  while (i < code.length) {
    const triple = code.startsWith('"""', i) ? '"""' : code.startsWith("'''", i) ? "'''" : null;
    const quote = triple || (`'"\``.includes(code[i]) ? code[i] : null);
    if (!quote) {
      out += code[i];
      i += 1;
      continue;
    }
    out += quote;
    i += quote.length;
    while (i < code.length && !code.startsWith(quote, i)) {
      if (code[i] === '\\' && i + 1 < code.length) {
        out += code[i + 1] === '\n' ? '\n' : ' ';
        out += ' ';
        i += 2;
        continue;
      }
      // A one-line literal ends at its line: an unbalanced quote never swallows the code after it.
      if (code[i] === '\n' && !triple && quote !== '`') break;
      out += code[i] === '\n' ? '\n' : ' ';
      i += 1;
    }
    if (code.startsWith(quote, i)) {
      out += quote;
      i += quote.length;
    }
  }
  return out;
}

/**
 * Everything the shell will execute, as {text, kind}. `kind` is 'segment' for a shell command and
 * 'code' for interpreter source, which anchor differently.
 */
function executedTexts(cmd) {
  const { rest, executed, shellBodies } = splitHeredocs(cmd);
  const out = [];
  for (const segment of segments(rest)) {
    const positions = commandPositions(segment);
    for (const position of positions) out.push({ text: position, kind: 'segment' });
    // A shell's `-c` script is a command LINE: `bash -c "cd x && uv run python y"` runs `uv` at a
    // command position the quote-aware split no longer opens, so the script is split in its own right.
    const shell = positions.some((position) => SHELLS.test(commandWord(position)));
    for (const script of inlineScripts(segment)) {
      out.push({ text: script, kind: 'code' });
      if (shell) out.push(...executedTexts(script));
    }
  }
  for (const body of executed) out.push({ text: body, kind: 'code' });
  // A body a SHELL consumes is a command line in its own right: its segments are shell text ('shell' rows read it).
  for (const body of shellBodies) out.push(...executedTexts(body));
  return out;
}

/**
 * Every COMMAND POSITION in one segment: the text at the wrapper itself, then at the command each
 * wrapper runs. `timeout 900 uv sync` yields both `timeout 900 uv sync` and `uv sync`, so a rule
 * naming either one still fires.
 *
 * A segment opening with `VAR=value` assignments ALSO yields itself whole, first: the assignment is
 * what the shell executes before the command, so a rule naming one (`SKIP=` bypasses the commit
 * hooks) must be able to see it. Stripping it was right for the command word and blinded every rule
 * about the prefix itself.
 */
function commandPositions(segment) {
  const out = [];
  const raw = segment.trim();
  if (ENV_PREFIX.test(raw)) out.push(raw);
  let text = segment.replace(ENV_PREFIX, '').trim();
  const seen = new Set();
  while (text && !seen.has(text)) {
    seen.add(text);
    out.push(text);
    const tokens = text.split(/\s+/);
    const head = tokens[0].replace(/^["']|["']$/g, '');
    let i;
    const uv = UV_RUN.exec(head);
    if (WRAPPERS.test(head)) i = 1;
    else if (uv && uv[1].toLowerCase() === 'uvx') i = 1; // `uvx <command>`: no verb of its own
    else if (uv && tokens[1] === 'run') i = 2; // `uv run <command>`; `uv sync` is NOT a wrapper
    else break;
    while (i < tokens.length && WRAPPER_ARG.test(tokens[i])) i += 1;
    text = tokens.slice(i).join(' ').replace(ENV_PREFIX, '').trim();
  }
  return out;
}

/* ================================ WHOSE DOOR A REFUSAL NAMES ================================
 *
 * The rules come from the SESSION root -- the project the session started in -- but a command can
 * target ANOTHER repo: run from its directory, behind `cd X &&`, or as `git -C X`. MEASURED
 * 2026-10-04: an agent working inside one repo was refused and told to run the session repo's
 * verdict runner and dated-path script, neither of which exists where it was. So the PATTERN stays
 * the session's, and the EXIT is resolved from the repo the command targets: each repo declares its
 * doors once, keyed by rule ID, in `[tool.dev_lab.doors]` of its pyproject.
 */

/** A Git Bash `/c/x` path as the host spells it; quotes dropped. */
function hostPath(word) {
  const bare = word.replace(/^["']|["']$/g, '');
  const drive = /^\/([a-zA-Z])(?=\/|$)/.exec(bare);
  return drive ? `${drive[1]}:${bare.slice(2)}` : bare;
}

/** The directory one `git ...` / `uv ...` / dependency-door segment names for itself, or `null`: git's `-C X`
 * among its global options (`-c k=v` and the rest are skipped), uv's `--directory X` / `--project X` (or `=X`)
 * anywhere, the dependency door's `--bootstrap X` / `--lock-upgrade X`. */
function namedDir(words) {
  const program = (words[0] || '').replace(/\.exe$/i, '');
  const m = words.indexOf('-m');
  if (/python[\w.]*$/i.test(program) && m > 0 && /^(?:dev_lab|lab_commons)\.dev\.dep$/.test(words[m + 1] || '')) {
    for (let i = m + 2; i < words.length; i += 1) {
      const eq = /^--(?:bootstrap|lock-upgrade)=(.+)$/.exec(words[i]);
      if (eq) return eq[1];
      const next = words[i + 1];
      if ((words[i] === '--bootstrap' || words[i] === '--lock-upgrade') && next && !next.startsWith('-')) return next;
    }
  } else if (program === 'git') {
    for (let i = 1; i < words.length; i += 1) {
      if (words[i] === '-C') return words[i + 1] || null;
      if (words[i] === '-c') i += 1;
      else if (!words[i].startsWith('-')) return null; // the verb: global options end here
    }
  } else if (program === 'uv') {
    for (let i = 1; i < words.length; i += 1) {
      const eq = /^--(?:directory|project)=(.+)$/.exec(words[i]);
      if (eq) return eq[1];
      if (words[i] === '--directory' || words[i] === '--project') return words[i + 1] || null;
    }
  }
  return null;
}

/** The directory the command acts in -- the ONE answer to "which tree" every judge reads. A segment acts in the
 * call's cwd as moved by the `cd X` segments before it, or in the dir its git/uv/dep call names. The answer is
 * the dir of the first segment `acts` selects at any command position (the one a rule fired on, behind a
 * `timeout 50m` too), else of the first segment that is not a `cd`, else the cwd the `cd`s leave. A shell's
 * `-c` script is a command line of its own starting in its segment's dir, so its `cd`s move it (2026-11-17:
 * `timeout 50m bash -c 'cd B && ...'` from A, and a bounded `dep --bootstrap C`, were both judged against A). */
function targetDir(cmd, cwd, acts = () => true) {
  const found = targetIn(cmd, cwd, acts);
  return found.hit ?? found.first ?? found.dir;
}

/** `targetDir`'s walk: {hit} the dir of the first acting segment, else {first, dir}. */
function targetIn(cmd, cwd, acts) {
  let dir = cwd;
  let first = null;
  const word = String.raw`("[^"\n]*"|'[^'\n]*'|[^\s;&|()]+)`;
  for (const segment of segments(splitHeredocs(cmd).rest)) {
    const text = segment.replace(ENV_PREFIX, '').trim();
    const cd = new RegExp(String.raw`^(?:cd|pushd)\s+${word}\s*$`).exec(text);
    if (cd) {
      dir = path.resolve(dir, hostPath(cd[1]));
      continue;
    }
    const positions = commandPositions(text);
    const acting = positions.find((position) => acts(position));
    const named = namedDir((acting ?? positions[positions.length - 1] ?? text).match(new RegExp(word, 'g')) || []);
    const here = named ? path.resolve(dir, hostPath(named)) : dir;
    if (acting !== undefined) return { hit: here };
    if (positions.some((position) => SHELLS.test(commandWord(position)))) {
      for (const script of inlineScripts(text)) {
        const inner = targetIn(script, here, acts);
        if (inner.hit) return inner;
      }
    }
    if (first === null && text) first = here;
  }
  return { hit: null, first, dir };
}

/** The directory the segment `rule` fires on acts in (`targetDir`). */
function ruleTarget(rule, cmd, cwd) {
  let at;
  try {
    at = new RegExp(rule.matches === 'argument' ? rule.pattern : `^(?:${rule.pattern})`);
  } catch {
    return targetDir(cmd, cwd);
  }
  return targetDir(cmd, cwd, (text) => at.test(text));
}

/** `dir` spelled for comparison: case-folded where the filesystem is (Windows), as Python's `os.path.normcase`. */
const normcase = (dir) => (process.platform === 'win32' ? path.resolve(dir).toLowerCase() : path.resolve(dir));

/** Directories git's discovery never climbs into: GIT_CEILING_DIRECTORIES, git's own contract. */
const CEILINGS = new Set((process.env.GIT_CEILING_DIRECTORIES || '').split(path.delimiter).filter(Boolean).map(normcase));

/** The nearest directory at or above `dir` holding a `.git` (a worktree's `.git` is a file), stopping where git
 * does -- the walk dev_lab.dev.gitdirs.ancestors also takes. */
function repoRoot(dir) {
  let at = path.resolve(dir);
  for (;;) {
    if (fs.existsSync(path.join(at, '.git'))) return at;
    const up = path.dirname(at);
    if (up === at || CEILINGS.has(normcase(up))) return null;
    at = up;
  }
}

/** `[tool.dev_lab.doors]` of `root`'s pyproject: rule ID -> the command that repo offers. */
function doorsOf(root) {
  const doors = {};
  let text;
  try {
    text = fs.readFileSync(path.join(root, 'pyproject.toml'), 'utf8');
  } catch {
    return doors;
  }
  let inside = false;
  for (const line of text.split(/\r?\n/)) {
    const header = /^\s*\[([^\]]+)\]\s*(?:#.*)?$/.exec(line);
    if (header) {
      inside = header[1].trim() === 'tool.dev_lab.doors';
      continue;
    }
    const row = inside && /^\s*["']?([A-Za-z0-9_-]+)["']?\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')/.exec(line);
    if (row) doors[row[1]] = row[2] !== undefined ? row[2].replace(/\\(["\\])/g, '$1') : row[3];
  }
  return doors;
}

const samePath = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();

/* ================================ A REMEDY NAMES AN ABSOLUTE INTERPRETER ================================
 *
 * 2026-10-26: a remedy spelled `.venv/Scripts/python.exe` relative, the agent's cwd was another directory, the
 * command failed, and the agent handed the user the absolute rewrite instead of running it. So a reason carries
 * `{python}` (or a repo door's `<venv python>`) and the engine writes the TARGET checkout's interpreter by
 * absolute path -- the same answer as dev_lab.dev.venvpath.remedy_interpreter.
 */
/** The ONE resolver (dev-lab #641): installed beside this engine; in the package, one directory up. Loaded only
 * when a remedy names an interpreter, so a missing copy never stops a decision: the remedy names its door. */
const MISSING_RESOLVER = 'venv_resolver.js is missing beside deny-commands.js -- run: python -m dev_lab.dev.agent_guard --install';
let resolver;
function theResolver() {
  if (resolver === undefined) {
    const file = [__dirname, path.dirname(__dirname)].map((dir) => path.join(dir, 'venv_resolver.js')).find(fs.existsSync);
    resolver = file ? require(file) : null;
  }
  if (!resolver) throw new Error(MISSING_RESOLVER);
  return resolver;
}
/** The environment a LAUNCH from `root` runs: the pointer resolved, so a later swap leaves the launch running. */
const currentEnv = (root) => theResolver().currentEnv(root);
/** The environment a PRINTED door names: the pointer itself, `<root>/.venv` UNRESOLVED -- it survives the next
 * bootstrap, where a resolved `.venvs/<id>` goes stale (2026-11-22: the hook printed the resolved spelling while the
 * rendered rows held the pointer, and a consumer's guard read its own refusals as another rule's). The Python twin
 * is dev_lab.dev.venvpath.door_interpreter. */
const doorEnv = (root) => path.join(root, theResolver().POINTER);

const VENV_TAIL = process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'];
const posix = (p) => p.replace(/\\/g, '/');

/** `root`'s own venv interpreter; else its main checkout's (a linked worktree); else the SESSION checkout's, which
 * exists (2026-11-03: a target with no venv was named `<target>/.venv/...python`, a command that cannot run); its
 * own spelling only when no interpreter exists anywhere. */
function remedyPython(root) {
  const checkout = checkoutPython(root);
  if (checkout) return checkout;
  const own = path.join(doorEnv(path.resolve(root)), ...VENV_TAIL);
  const session = sessionRoot && path.join(doorEnv(sessionRoot), ...VENV_TAIL);
  if (session && fs.existsSync(session)) return posix(session);
  return posix(own);
}

/** `root`'s own venv interpreter, else its main checkout's (a linked worktree), else null: never another repo's. */
function checkoutPython(root) {
  const own = path.join(doorEnv(path.resolve(root)), ...VENV_TAIL);
  if (fs.existsSync(own)) return posix(own);
  try {
    const named = /^gitdir:\s*(.+?)\s*$/m.exec(fs.readFileSync(path.join(root, '.git'), 'utf8'));
    const gitdir = named ? path.resolve(root, named[1]) : '';
    if (gitdir && path.basename(path.dirname(gitdir)) === 'worktrees') {
      const main = path.join(doorEnv(path.dirname(path.dirname(path.dirname(gitdir)))), ...VENV_TAIL);
      if (fs.existsSync(main)) return posix(main);
    }
  } catch {
    // a `.git` directory, or none: no checkout interpreter
  }
  return null;
}

const listDir = (dir) => {
  try {
    return fs.readdirSync(dir);
  } catch {
    return [];
  }
};

/** Whether `python`'s venv has dev_lab installed: a `dev_lab-*.dist-info` in its site-packages. */
function carriesDevLab(python) {
  const lib = path.join(path.dirname(path.dirname(python)), process.platform === 'win32' ? 'Lib' : 'lib');
  const sites = process.platform === 'win32' ? [lib] : listDir(lib).map((version) => path.join(lib, version));
  return sites.some((site) => listDir(path.join(site, 'site-packages')).some((name) => /^dev_lab-.*\.dist-info$/.test(name)));
}

/** The exit of a per-repo-door rule when `target` declares none (2026-11-17: a pytest in one repo was sent to the
 * session repo's `scripts/gate/runner.py`, absent there): the family verify door when the target's OWN
 * interpreter carries dev_lab, else the declaration to add -- never another repo's path. A need whose family door
 * reads no file of the target (FAMILY_DOORS; 2026-11-22: a network verb in a repo declaring no doors was told to
 * declare one and named none) is sent to that door, printed with the session's interpreter. */
const FAMILY_DOORS = {
  'retry-wrapper': 'dev_lab.dev.netverb -- git <verb> (or uv <verb>)',
  'process-tree-killer': 'dev_lab.dev.stoprun --pid <pid>',
};
function undeclaredDoor(rule, target, shown) {
  if (FAMILY_DOORS[rule.needs]) {
    return `${shown} declares no door for it; the family door runs from any directory: ${doorPython(target)} -m ${FAMILY_DOORS[rule.needs]}`;
  }
  const python = rule.needs === 'verdict-entry-point' ? checkoutPython(target) : null;
  if (python && carriesDevLab(python)) {
    return `${shown} declares no door for it; its own interpreter carries dev_lab: ${python} -m dev_lab.dev.verify -- <paths>`;
  }
  return `${shown} declares no door for it: declare one in its pyproject.toml as [tool.dev_lab.doors] ${rule.name} = "<the command that runs it there>"`;
}

/** The interpreter a FAMILY door is printed with: the session checkout's, whose rendered rules named the door --
 * never the target's, whose older kit may lack the verb (2026-11-19, `worktrees --remove` in a sibling repo). */
function doorPython(checkout) {
  try {
    return remedyPython(sessionRoot || checkout || root);
  } catch (missing) {
    return `<${missing.message}>`;
  }
}

/** `text` with `{root}` as the cwd and the interpreter tokens as `checkout`'s absolute interpreter. */
function expand(text, checkout) {
  let out = String(text).replaceAll('{root}', root);
  if (out.includes('{door}')) out = out.replaceAll('{door}', doorPython(checkout));
  if (!checkout || !/\{python\}|<venv python>/.test(out)) return out;
  let python;
  try {
    python = remedyPython(checkout);
  } catch (missing) {
    python = `<${missing.message}>`; // the refusal still stands, and names the door that restores the resolver
  }
  return out.replaceAll('{python}', python).replaceAll('<venv python>', python);
}

/** The checkout a rule's remedy is about: the one the matching segment acts in, else the session's. */
function remedyCheckout(rule, cmd, cwd) {
  return (cwd && repoRoot(ruleTarget(rule, cmd, cwd))) || sessionRoot || (cwd && repoRoot(cwd)) || null;
}

/** The reason to show: the session's own, unless the command targets another repo. */
function reasonFor(rule, reason, cmd, cwd, sessionRoot) {
  const target = cwd ? repoRoot(ruleTarget(rule, cmd, cwd)) : null;
  if (!target || !sessionRoot || samePath(target, sessionRoot)) return reason;
  const shown = target.replace(/\\/g, '/');
  const door = doorsOf(target)[rule.name] && expand(doorsOf(target)[rule.name], target);
  // One header line; the full wording is docs-src/dev/refusals.md#cross-repo-refusals (dev-lab).
  const details = reason.split('\n').filter((line) => line.startsWith('details: '));
  if (door) {
    const said = rule.severity === 'hint' ? 'advised' : 'refused';
    return [`${rule.name}: ${said}; ${shown} declares its own door for it:`, door, ...details].join('\n');
  }
  if (rule.needs) return [reason.split('\n')[0], undeclaredDoor(rule, target, shown), ...details].join('\n');
  const session = sessionRoot.replace(/\\/g, '/');
  return `[targets ${shown}, which declares no door; repo files named below are ${session}'s]\n${reason}`;
}

/* ================================ A ROW THAT BINDS ONLY WHILE A RUN IS LIVE ================================
 *
 * `when: 'live-run'` (TREE-HAS-A-LIVE-RUN): the pattern names a command that mutates a checkout or its venv,
 * and it is refused only while a run executes from the checkout the command targets. Whether one does is
 * the process table's answer, which this engine cannot read: it asks `python -m dev_lab.dev.liverun
 * --tree <target>` through the session checkout's own interpreter, only AFTER the pattern matched, so an
 * unmatched command pays nothing. Exit 0 is no live run and exit 1 prints the refusal. No interpreter is no
 * refusal: a checkout without the kit has nobody to ask. A crash or a timeout REFUSES, unlike the rest of
 * this engine, because the harm this row guards (a run's tree changed under it) cannot be undone.
 */
/** The session checkout's own interpreter, or null: a checkout without a venv has nobody to ask. */
function venvPython(sessionRoot) {
  const tail = process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'];
  const python = sessionRoot ? path.join(currentEnv(sessionRoot), ...tail) : '';
  return python && fs.existsSync(python) ? python : null;
}

function liveRunRefusal(target, sessionRoot) {
  if (!target || !sessionRoot) return '';
  const python = venvPython(sessionRoot);
  if (!python) return '';
  const done = spawnSync(python, ['-m', 'dev_lab.dev.liverun', '--tree', target], {
    encoding: 'utf8',
    timeout: 15000,
    windowsHide: true,
  });
  if (done.status === 0) return '';
  const said = String(done.stdout || '').trim();
  if (done.status === 1 && said) return said;
  // A venv without the kit is the same case as no interpreter: nobody to ask, so no refusal. A checkout
  // mid-adoption (its lock not yet carrying dev-lab) must stay workable.
  if (/No module named '?dev_lab/.test(String(done.stderr || ''))) return '';
  // A Python that cannot start, or that imports the module and crashes, is not an answer.
  const why = done.error ? done.error.message : `exit ${done.status}${said ? '' : ', no answer'}`;
  return `TREE-HAS-A-LIVE-RUN: could not confirm that no run executes from ${target} (${why}); re-run when ` +
    `${remedyPython(sessionRoot)} -m dev_lab.dev.liverun --tree ${target} answers.`;
}

/* ================================ A ROW THAT BINDS ONLY ON A DECLARED REPO ================================
 *
 * `when: 'declared-repo'` (FAMILY-REPO-IS-CHECKED-OUT): the pattern names a clone, refused only when its url is a
 * family repo this machine already checks out. That is the machine file's answer (the family layer's remotes, the
 * local layer's paths), which this engine does not parse: it asks `python -m dev_lab.dev.familyrepos clone-check`
 * with the command on stdin, only AFTER the pattern matched. Exit 1 prints the refusal; anything else -- no
 * interpreter, no kit, a crash -- refuses NOTHING, because a duplicate clone is removable and a guard that cannot
 * read the declaration must not block every clone.
 */
function declaredRepoRefusal(command, sessionRoot) {
  const python = venvPython(sessionRoot);
  if (!python) return '';
  const done = spawnSync(python, ['-m', 'dev_lab.dev.familyrepos', 'clone-check'], {
    input: command,
    encoding: 'utf8',
    timeout: 15000,
    windowsHide: true,
  });
  const said = String(done.stdout || '').trim();
  return done.status === 1 && said ? said : '';
}

/* `when: 'background'`: `python -m dev_lab.dev.shelllife --admit` judges the line on stdin -- exit 0 admitted, exit 1
 * prints the refusal. '' admits; null is nobody to ask (no interpreter, no kit, a crash), and the row's pattern decides. */
function lifetimeRefusal(cmd, sessionRoot) {
  const python = venvPython(sessionRoot);
  if (!python) return null;
  const done = spawnSync(python, ['-m', 'dev_lab.dev.shelllife', '--admit'], {
    input: cmd,
    encoding: 'utf8',
    timeout: 15000,
    windowsHide: true,
  });
  if (done.status === 0) return '';
  const said = String(done.stdout || '').trim();
  return done.status === 1 && said ? said : null;
}

/* ================================ A ROW WHOSE JUDGE IS A MODULE ================================
 *
 * `asks: '<module>'`: the decision needs repo state no regex reads (TRACKED-CITES-NO-EPHEMERAL: is a path the
 * journal line cites ignored HERE?), so the pattern is only a cheap PREFILTER. After it matched -- never before, so
 * the common call starts no interpreter -- the session checkout's Python runs `-m <module> --admit` with the hook
 * payload on stdin. Exit 1 with text refuses with that text, verbatim; anything else admits: no interpreter, no kit,
 * a crash or a timeout is nobody's refusal, as the hook this replaced was (the commit-time check stands behind it).
 */
function askedRefusal(module, sessionRoot) {
  let python;
  try {
    python = venvPython(sessionRoot);
  } catch {
    return ''; // no resolver: nobody to ask
  }
  if (!python) return '';
  const done = spawnSync(python, ['-m', module, '--admit'], {
    input: JSON.stringify(input),
    encoding: 'utf8',
    timeout: 15000,
    windowsHide: true,
  });
  const said = String(done.stdout || '').trim();
  return done.status === 1 ? said : '';
}

/* ================================ A ROW THAT STILL ADMITS A FAMILY SIBLING CLONE ================================
 *
 * `admits: 'family-sibling-clone'` (WORKTREES-STAY-INSIDE): every family checkout lives BESIDE its siblings, so
 * cloning a family repo there is the one placement outside `.claude/worktrees` that is right -- and no regex can
 * tell it from a misplaced tree. Admitted only when the WHOLE line is `cd`s then ONE clone `<url> <dir>`, and
 * <dir> does not exist yet, is named for the repo, sits beside the main checkout of the tree the line runs in,
 * and the url comes from a forge (scheme+host+owner) some sibling checkout's `origin` already comes from. No
 * repo or owner is named here: the family is whatever already sits beside the checkout.
 */
/** `root`'s git dir, following a worktree's `.git` file and its `commondir` to the repository's own. */
function commonGitDir(root) {
  let dir = path.join(root, '.git');
  if (fs.statSync(dir).isFile()) {
    const said = /^gitdir:\s*(.+?)\s*$/m.exec(fs.readFileSync(dir, 'utf8'));
    if (!said) return null;
    dir = path.resolve(root, said[1]);
    const common = path.join(dir, 'commondir');
    if (fs.existsSync(common)) dir = path.resolve(dir, fs.readFileSync(common, 'utf8').trim());
  }
  return dir;
}

/** `{forge, name}` of a clone url: everything before the last path word, and that word without `.git`. */
function forgeOf(url) {
  const at = /^(.*[/:])([^/:]+?)(?:\.git)?\/?$/.exec(url || '');
  return at ? { forge: at[1].toLowerCase(), name: at[2] } : null;
}

/** The `origin` url in the repository whose git dir is `gitDir`, or null. */
function originOf(gitDir) {
  let inside = false;
  for (const line of fs.readFileSync(path.join(gitDir, 'config'), 'utf8').split(/\r?\n/)) {
    const header = /^\s*\[(.+)\]\s*$/.exec(line);
    if (header) inside = /^remote\s+"origin"$/.test(header[1].trim());
    const url = inside && /^\s*url\s*=\s*(.+?)\s*$/.exec(line);
    if (url) return url[1];
  }
  return null;
}

function familySiblingClone(cmd, cwd) {
  if (!cwd) return false;
  const word = String.raw`("[^"\n]*"|'[^'\n]*'|[^\s;&|()]+)`;
  const cdAt = new RegExp(String.raw`^(?:cd|pushd)\s+${word}\s*$`);
  const cloneAt = new RegExp(String.raw`^(?:git(?:\.exe)?|(?:sh|bash)\s+\S*retry\S*)\s+clone\s+${word}\s+${word}\s*$`);
  let dir = path.resolve(cwd);
  let clone = null;
  for (const segment of segments(splitHeredocs(cmd).rest)) {
    const text = segment.replace(ENV_PREFIX, '').trim();
    if (!text) continue;
    const cd = clone === null && cdAt.exec(text);
    if (cd) {
      dir = path.resolve(dir, hostPath(cd[1]));
      continue;
    }
    const at = clone === null && cloneAt.exec(text);
    if (!at) return false; // a second verb, of any kind, after or instead of the one clone
    clone = { url: hostPath(at[1]), target: path.resolve(dir, hostPath(at[2])) };
  }
  if (clone === null || fs.existsSync(clone.target)) return false;
  const repo = forgeOf(clone.url);
  if (!repo || path.basename(clone.target).toLowerCase() !== repo.name.toLowerCase()) return false;
  try {
    const own = repoRoot(cwd);
    const gitDir = own && commonGitDir(own);
    if (!gitDir || !samePath(path.dirname(clone.target), path.dirname(path.dirname(gitDir)))) return false;
    const family = path.dirname(clone.target);
    return fs.readdirSync(family).some((name) => {
      const sibling = path.join(family, name);
      if (!fs.existsSync(path.join(sibling, '.git'))) return false;
      const theirs = forgeOf(originOf(commonGitDir(sibling)));
      return theirs !== null && theirs.forge === repo.forge;
    });
  } catch {
    return false; // a tree the engine cannot read admits nothing
  }
}

/* ================================ A WORKTREE UNDER THE MACHINE'S BOUND HOME ================================
 *
 * `admits: 'bound-worktree-home'` (WORKTREES-STAY-INSIDE): a machine may bind the `worktrees` storage kind outside
 * the checkout ([storage.roots] worktrees), a path no committed pattern can name. The binding is ONE fact in the
 * machine file; `python -m dev_lab.dev.storage publish` renders it as JSON for this engine (no TOML here). A line is
 * admitted only when EVERY `worktree add|move` / `clone` target lies inside the repository's worktree home -- the
 * published root with `{repo}` filled by the main checkout's name, or its in-tree default. No file, no binding, a
 * target the engine cannot place: admits nothing.
 */
const STORAGE_ROOTS_ENV = 'LAB_COMMONS_STORAGE_ROOTS';

function publishedWorktrees() {
  const file =
    process.env[STORAGE_ROOTS_ENV] || path.join(require('os').homedir(), '.config', 'lab-commons', 'storage-roots.json');
  try {
    const kind = JSON.parse(fs.readFileSync(file, 'utf8')).worktrees;
    return kind && typeof kind.root === 'string' && typeof kind.default === 'string' ? kind : null;
  } catch {
    return null;
  }
}

function insideDir(target, base) {
  const folded = normcase(base);
  return normcase(target).startsWith(folded + path.sep);
}

/** The positional words after `options`: `-b`, `-B` and `--reason` consume the next word. */
function positionalWords(words) {
  const found = [];
  for (let i = 0; i < words.length; i += 1) {
    if (words[i] === '-b' || words[i] === '-B' || words[i] === '--reason') i += 1;
    else if (!words[i].startsWith('-')) found.push(words[i]);
  }
  return found;
}

function boundWorktreeHome(cmd, cwd) {
  const kind = cwd && publishedWorktrees();
  if (!kind) return false;
  let dir = path.resolve(cwd);
  let placed = 0;
  for (const segment of segments(splitHeredocs(cmd).rest)) {
    const text = segment.replace(ENV_PREFIX, '').trim();
    if (!text) continue;
    const words = (text.match(/"[^"\n]*"|'[^'\n]*'|\S+/g) || []).map((word) => word.replace(/^["']|["']$/g, ''));
    if (words[0] === 'cd' || words[0] === 'pushd') {
      dir = path.resolve(dir, hostPath(words[1] || '.'));
      continue;
    }
    let base = dir;
    let at;
    if (/^git(?:\.exe)?$/i.test(words[0])) {
      at = 1;
      while (at + 1 < words.length && (words[at] === '-C' || words[at] === '-c')) {
        if (words[at] === '-C') base = path.resolve(base, hostPath(words[at + 1]));
        at += 2;
      }
    } else if (/^(?:sh|bash)$/.test(words[0]) && /retry/i.test(words[1] || '')) {
      at = 2;
    } else {
      continue;
    }
    const rest = words.slice(at);
    let index;
    let positionals;
    if (rest[0] === 'worktree' && (rest[1] === 'add' || rest[1] === 'move')) {
      positionals = positionalWords(rest.slice(2));
      index = rest[1] === 'add' ? 0 : 1;
    } else if (rest[0] === 'clone') {
      positionals = positionalWords(rest.slice(1));
      index = 1;
    } else {
      continue;
    }
    if (positionals.length <= index) return false;
    const target = path.resolve(base, hostPath(positionals[index]));
    try {
      const own = repoRoot(base);
      const gitDir = own && commonGitDir(own);
      if (!gitDir) return false;
      const main = path.dirname(gitDir);
      const home = path.resolve(kind.root.split('{repo}').join(path.basename(main)));
      if (!insideDir(target, home) && !insideDir(target, path.join(main, ...kind.default.split('/')))) return false;
    } catch {
      return false;
    }
    placed += 1;
  }
  return placed > 0;
}

/** Whether `rule` carries the filesystem admission `name` (a row may carry one or several). */
function admitsBy(rule, name) {
  return Array.isArray(rule.admits) ? rule.admits.includes(name) : rule.admits === name;
}

/* ================================ A GREP WHOSE OPERANDS ARE FILES WALKS NOTHING ================================
 *
 * `admits: 'file-operands'` (RECURSIVE-GREP): `-r` names a WALK only when an operand is a directory, or when none is
 * given (grep then walks the cwd). Measured 2026-11-16: `grep -rn x src/a.py` was hinted though it reads one file.
 * The operands are read off the firing segment's argv, in the directory that segment acts in.
 */
const GREP = /^(?:.*[/\\])?[ef]?grep(?:\.exe)?$/i;
const GREP_VALUED_SHORT = 'efmABCdD';
const GREP_VALUED_LONG =
  /^--(?:regexp|file|max-count|after-context|before-context|context|include|exclude|exclude-dir|exclude-from|label|binary-files|devices|directories)$/;

/** The words the segment `rule` fires on would run, quotes dropped; null when it fires on none. */
function firingWords(rule, cmd) {
  let at;
  try {
    at = new RegExp(`^(?:${rule.pattern})`);
  } catch {
    return null;
  }
  const firing = segments(splitHeredocs(cmd).rest)
    .flatMap((segment) => commandPositions(segment))
    .find((text) => at.test(text));
  return firing ? (firing.match(/"[^"\n]*"|'[^'\n]*'|\S+/g) || []).map((w) => w.replace(/^["']|["']$/g, '')) : null;
}

function fileOperands(rule, cmd, cwd) {
  const words = cwd && firingWords(rule, cmd);
  if (!words) return false;
  let patternGiven = false;
  const positional = [];
  for (let i = words.findIndex((w) => GREP.test(w)) + 1; i > 0 && i < words.length; i += 1) {
    const w = words[i];
    if (w === '--') {
      positional.push(...words.slice(i + 1));
      break;
    }
    if (/^--(?:regexp|file)=/.test(w)) patternGiven = true;
    else if (GREP_VALUED_LONG.test(w)) {
      patternGiven = patternGiven || w === '--regexp' || w === '--file';
      i += 1;
    } else if (/^-[^-]/.test(w)) {
      const valued = [...w.slice(1)].findIndex((c) => GREP_VALUED_SHORT.includes(c));
      if (valued >= 0 && 'ef'.includes(w[valued + 1])) patternGiven = true;
      if (valued >= 0 && valued + 2 === w.length) i += 1; // the value is the next word
    } else if (!w.startsWith('--')) positional.push(w);
  }
  const operands = patternGiven ? positional : positional.slice(1);
  const dir = ruleTarget(rule, cmd, cwd);
  return (
    operands.length > 0 &&
    operands.every((operand) => {
      try {
        return fs.statSync(path.resolve(dir, hostPath(operand))).isFile();
      } catch {
        return false;
      }
    })
  );
}

/* A refusal is a WALL (WALLS-ARE-RECORDED, dev_lab.dev.walls): one metrics line and one ledger line, appended by the
 * ONE writer in a DETACHED interpreter, so the refusal the agent sees waits for nothing. No interpreter, no line. The
 * command never leaves this process: only a sha256 prefix of it does. A reason names a door when a line beyond its
 * cause is not only the `details:` pointer or the cross-repo header -- dev_lab.dev.walls.has_remedy, the same test. */
function hasRemedy(reason) {
  const lines = String(reason).split('\n').map((line) => line.trim()).filter(Boolean);
  return lines.filter((line) => !line.startsWith('details: ') && !/^\[targets .*\]$/.test(line)).length >= 2;
}

function logRefusal(name, where, reason) {
  const python = venvPython(sessionRoot);
  if (!python) return;
  try {
    const digest = crypto.createHash('sha256').update(cmd, 'utf8').digest('hex').slice(0, 16);
    const argv = ['-m', 'dev_lab.dev.walls', 'refused', '--rule', name, '--reason', 'agent-guard',
      '--command-sha256', digest, hasRemedy(reason) ? '--remedy' : '--no-remedy'];
    if (typeof input.session_id === 'string' && input.session_id) argv.push('--session', input.session_id);
    spawn(python, argv, { cwd: where, detached: true, stdio: 'ignore', windowsHide: true }).unref();
  } catch {
    // a ledger line never blocks the refusal it describes
  }
}

/** Does `rule` fire on any executed text? */
function fires(rule, texts, cmd) {
  // A 'line' rule names a shape that spans segments (a code piped into a command), so it reads the whole line.
  // Never a body a sink consumes (2026-11-16: prose naming a path was refused): the shell text and executed bodies.
  if (rule.matches === 'line') {
    const at = new RegExp(rule.pattern);
    const { rest, executed } = splitHeredocs(cmd);
    return at.test(rest) || executed.some((body) => at.test(body));
  }
  const argument = rule.matches === 'argument';
  // A 'command' rule anchors at the start of a segment, and at the start of a LINE inside
  // interpreter code. An 'argument' rule names an option, so it is searched within the text.
  const atSegment = new RegExp(argument ? rule.pattern : `^(?:${rule.pattern})`);
  const atLine = new RegExp(argument ? rule.pattern : `^[ \\t]*(?:${rule.pattern})`, 'm');
  // A 'shell' rule names a shell verb: interpreter code (python/node source) never spells it as a command.
  if (rule.matches === 'shell') return texts.some(({ text, kind }) => kind === 'segment' && atSegment.test(text));
  return texts.some(({ text, kind }) => (kind === 'segment' ? atSegment.test(text) : atLine.test(withoutStrings(text))));
}

let input;
let rules;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf8'));
  rules = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
} catch {
  process.exit(0);
}
// EVERY TOOL THAT RUNS A COMMAND LINE. Until 2026-10-08 this read `!== 'Bash'`, and the PowerShell
// tool -- the same `tool_input.command`, the same shell verbs -- ran every denied shape unjudged.
if (!SHELL_TOOLS.has(input.tool_name) || !Array.isArray(rules)) process.exit(0);
// `agent_id` is present only when the hook fires inside a subagent (fork included); a row scoped
// 'subagent' is judged only there. Keyed on agent_id, never agent_type: a main session launched
// with --agent carries agent_type too.
const subagent = typeof input.agent_id === 'string' && input.agent_id !== '';
const cmd = (input.tool_input && input.tool_input.command) || '';
const root = (input.cwd || '').replace(/\\/g, '/');
const sessionRoot = repoRoot(path.resolve(path.dirname(process.argv[2]), '..', '..'));
const texts = executedTexts(cmd);
const hints = [];

for (const rule of rules) {
  if (rule.scope === 'subagent' && !subagent) continue;
  let hit;
  try {
    hit = fires(rule, texts, cmd) && !(rule.allow && new RegExp(rule.allow).test(cmd));
  } catch {
    continue; // one malformed rule never blocks the session
  }
  if (hit && admitsBy(rule, 'family-sibling-clone') && familySiblingClone(cmd, input.cwd)) continue;
  if (hit && admitsBy(rule, 'bound-worktree-home') && boundWorktreeHome(cmd, input.cwd)) continue;
  if (hit && admitsBy(rule, 'file-operands') && fileOperands(rule, cmd, input.cwd)) continue;
  let liveReason = '';
  if (hit && rule.asks) {
    liveReason = askedRefusal(rule.asks, sessionRoot);
    hit = liveReason !== '';
  }
  // A 'background' row binds only on a Bash call the agent runs in the background (BACKGROUND-SHELL-IS-BOUNDED),
  // and there the session's interpreter judges it (a longer life needs the USER's grant); the pattern only without one.
  if (rule.when === 'background') {
    const background = input.tool_name === 'Bash' && input.tool_input.run_in_background === true;
    const asked = background ? lifetimeRefusal(cmd, sessionRoot) : null;
    if (asked !== null) {
      liveReason = asked;
      hit = asked !== '';
    } else {
      hit = hit && background;
    }
  }
  if (hit && rule.when === 'live-run') {
    // A PROBE judging which rule owns a shape sets this (run_engine(live_run=False)): its own suite is a
    // run in the checkout it probes. The tool never sends the key, so no agent command can set it.
    if (input.dev_lab_live_run_absent === true) continue;
    // The DIRECTORY, never its repoRoot: a worktree the line is about to create does not exist yet, and walking up
    // from it lands on the checkout holding it -- whose run is not this command's (2026-11-07). liverun resolves it.
    liveReason = liveRunRefusal(input.cwd ? ruleTarget(rule, cmd, input.cwd) : null, sessionRoot);
    hit = liveReason !== '';
  }
  if (hit && rule.when === 'declared-repo') {
    liveReason = declaredRepoRefusal(cmd, sessionRoot);
    hit = liveReason !== '';
  }
  if (hit && rule.severity === 'hint') {
    // A hint names the TARGET's door as a refusal does (2026-11-22: a network verb in a sibling repo was handed the
    // session repo's wrapper, a file the sibling does not have).
    hints.push(reasonFor(rule, expand(rule.reason || rule.name, remedyCheckout(rule, cmd, input.cwd)), cmd, input.cwd || '', sessionRoot));
  } else if (hit) {
    // A PROBE (run_engine) names where its refusal is logged, '' for nowhere; the tool never sends the key.
    const probed = typeof input.dev_lab_metrics_root === 'string';
    const where = probed ? input.dev_lab_metrics_root : input.cwd ? repoRoot(ruleTarget(rule, cmd, input.cwd)) || input.cwd : sessionRoot;
    const reason =
      liveReason ||
      reasonFor(rule, expand(rule.reason || rule.name, remedyCheckout(rule, cmd, input.cwd)), cmd, input.cwd || '', sessionRoot);
    if (where) logRefusal(rule.name, where, reason);
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason },
      })
    );
    process.exit(0);
  }
}
if (hints.length) {
  process.stdout.write(
    JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: hints.join('\n') } })
  );
}
process.exit(0);
