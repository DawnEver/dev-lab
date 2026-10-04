#!/usr/bin/env node
// Engine shipped by lab-commons: lab_commons.dev.agenthooks (deny-commands). INSTALLED BY
// `python -m lab_commons.dev.agent_guard --install`, never hand-copied -- `agent_guard` reads the
// line above to tell an installed engine from a stale one from a hand-written file in the same
// slot. Editing this copy in a consumer repo makes it STALE, and the next verify says so.
/**
 * Generic PreToolUse command-deny engine. Knows NOTHING about git or pytest: every denied shape
 * is a rule in the JSON file passed as argv[2] (`.claude/hooks/deny-rules.json`), so adding or
 * retiring a rule is a data change, never an engine change.
 *
 * A rule is {name, pattern, matches?, allow?, reason}. `pattern` (JS regex source) denies a
 * command it matches, unless `allow` (regex source) also matches -- the sanctioned spelling.
 * `reason` is the rewrite hint shown to the agent; `{root}` in it expands to the tool call's cwd.
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
    if (commandPositions(opening).some((position) => INTERPRETERS.test(commandWord(position)))) executed.push(body);

    rest += cmd.slice(index, opener.lastIndex);
    index = bodyEnd;
    opener.lastIndex = bodyEnd;
  }
  rest += cmd.slice(index);
  return { rest, executed };
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
 * Everything the shell will execute, as {text, kind}. `kind` is 'segment' for a shell command and
 * 'code' for interpreter source, which anchor differently.
 */
function executedTexts(cmd) {
  const { rest, executed } = splitHeredocs(cmd);
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
  return out;
}

/**
 * Every COMMAND POSITION in one segment: the text at the wrapper itself, then at the command each
 * wrapper runs. `timeout 900 uv sync` yields both `timeout 900 uv sync` and `uv sync`, so a rule
 * naming either one still fires.
 */
function commandPositions(segment) {
  const out = [];
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
 * doors once, keyed by rule ID, in `[tool.lab_commons.doors]` of its pyproject.
 */

/** A Git Bash `/c/x` path as the host spells it; quotes dropped. */
function hostPath(word) {
  const bare = word.replace(/^["']|["']$/g, '');
  const drive = /^\/([a-zA-Z])(?=\/|$)/.exec(bare);
  return drive ? `${drive[1]}:${bare.slice(2)}` : bare;
}

/** The directory the command acts in: the call's cwd, moved by `cd X` segments, or `git -C X`. */
function targetDir(cmd, cwd) {
  let dir = cwd;
  const word = String.raw`("[^"\n]*"|'[^'\n]*'|[^\s;&|()]+)`;
  for (const segment of segments(splitHeredocs(cmd).rest)) {
    const text = segment.replace(ENV_PREFIX, '').trim();
    const cd = new RegExp(String.raw`^(?:cd|pushd)\s+${word}\s*$`).exec(text);
    if (cd) {
      dir = path.resolve(dir, hostPath(cd[1]));
      continue;
    }
    const gitC = new RegExp(String.raw`^git(?:\.exe)?\s+-C\s+${word}`).exec(text);
    if (gitC) return path.resolve(dir, hostPath(gitC[1]));
  }
  return dir;
}

/** The nearest directory at or above `dir` holding a `.git` (a worktree's `.git` is a file). */
function repoRoot(dir) {
  let at = path.resolve(dir);
  for (;;) {
    if (fs.existsSync(path.join(at, '.git'))) return at;
    const up = path.dirname(at);
    if (up === at) return null;
    at = up;
  }
}

/** `[tool.lab_commons.doors]` of `root`'s pyproject: rule ID -> the command that repo offers. */
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
      inside = header[1].trim() === 'tool.lab_commons.doors';
      continue;
    }
    const row = inside && /^\s*["']?([A-Za-z0-9_-]+)["']?\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')/.exec(line);
    if (row) doors[row[1]] = row[2] !== undefined ? row[2].replace(/\\(["\\])/g, '$1') : row[3];
  }
  return doors;
}

const samePath = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();

/** The reason to show: the session's own, unless the command targets another repo. */
function reasonFor(rule, reason, cmd, cwd, sessionRoot) {
  const target = cwd ? repoRoot(targetDir(cmd, cwd)) : null;
  if (!target || !sessionRoot || samePath(target, sessionRoot)) return reason;
  const shown = target.replace(/\\/g, '/');
  const door = doorsOf(target)[rule.name];
  if (door) {
    return (
      `${rule.name}: refused. This command targets ${shown}, so its exit is that repo's own door ` +
      `(pyproject [tool.lab_commons.doors]): ${door}`
    );
  }
  return (
    `[${rule.name}: this command targets ${shown}, which declares no door for this rule in its ` +
    `pyproject [tool.lab_commons.doors]; any repo file named below belongs to ` +
    `${sessionRoot.replace(/\\/g, '/')} and may not exist there] ${reason}`
  );
}

/** Does `rule` fire on any executed text? */
function fires(rule, texts) {
  const argument = rule.matches === 'argument';
  // A 'command' rule anchors at the start of a segment, and at the start of a LINE inside
  // interpreter code. An 'argument' rule names an option, so it is searched within the text.
  const atSegment = new RegExp(argument ? rule.pattern : `^(?:${rule.pattern})`);
  const atLine = new RegExp(argument ? rule.pattern : `^[ \\t]*(?:${rule.pattern})`, 'm');
  return texts.some(({ text, kind }) => (kind === 'segment' ? atSegment : atLine).test(text));
}

let input;
let rules;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf8'));
  rules = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
} catch {
  process.exit(0);
}
if (input.tool_name !== 'Bash' || !Array.isArray(rules)) process.exit(0);
const cmd = (input.tool_input && input.tool_input.command) || '';
const root = (input.cwd || '').replace(/\\/g, '/');
const sessionRoot = repoRoot(path.resolve(path.dirname(process.argv[2]), '..', '..'));
const texts = executedTexts(cmd);

for (const rule of rules) {
  let hit;
  try {
    hit = fires(rule, texts) && !(rule.allow && new RegExp(rule.allow).test(cmd));
  } catch {
    continue; // one malformed rule never blocks the session
  }
  if (hit) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: reasonFor(
            rule,
            String(rule.reason || rule.name).replaceAll('{root}', root),
            cmd,
            input.cwd || '',
            sessionRoot
          ),
        },
      })
    );
    process.exit(0);
  }
}
process.exit(0);
