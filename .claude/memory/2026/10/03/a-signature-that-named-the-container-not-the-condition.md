---
name: a-signature-that-named-the-container-not-the-condition
description: The log scanner signed an anomaly with the set of file NAMES holding errors, so a new failure in a log that already had an old one inherited that old one's signature — and the policy writes a condition off by signature, so the new failure was absorbed into the old one's silence. Found on a live host where one two-line ENOENT convicted for 54 consecutive cycles.
created: 2026-10-03
accessed: 2026-10-03
---

# A signature that named the container, not the condition (2026-10-03)

Found by reading a live host's supervisor state rather than by any test:

```
anomalies: {"log_scanner.errors_in_log": {"consecutive": 54, "signature": "logs:['run.log']", "notified": 54}}
```

Fifty-four consecutive cycles, DEGRADED the whole time, over a **two-line ENOENT at line 2 of a
nine-line file**.

## The defect

`signature=f'logs:{sorted({hit["file"] for hit in hits})}'` — the set of file **names**.

A file name is stable while its contents are not. And `policy.decide` counts consecutive cycles
**per signature**, then writes the condition off:

> `if sightings > write_off: return Decision(notify=False, reason='silent: the same condition has held for N cycles')`

So the scanner had two outcomes for a fresh exception, and the wrong one for every case that
mattered. If no log held an error yet, it was reported. If one did, the new failure **wore the old
one's signature**, was counted as "the same condition", and went silent.

That is the exact failure this component exists to catch: an unhandled exception landing outside a
request, the shape that leaves `/health/` answering 200 while something is wrong. It was blind
precisely when something was already wrong.

## The fix, and why the digest folds digits

`signature = f'logs:{files}:{sha256(folded matched lines)[:16]}'`.

The numbers are **folded out** (`re.sub(r'\d+', '#', line)`) before hashing, and that is not
cosmetic: a log line is `10/03/2026 19:58:20 ERROR Failed to open file /x/y.toml! [Errno 2]`, so the
date, the clock and the errno change on every write. Hashing the raw text would make ONE condition a
**new signature every cycle** — an alert storm, the opposite failure. Folding keeps the message, the
path and the frames, which is what says *which* failure this is.

Two assertions in `test_a_new_error_in_a_log_that_already_had_one_is_a_new_condition`: the same error
re-dated keeps its signature; a different error in the same file does not.

**A signature is the identity of a condition. If it can be computed from where a thing sits rather
than from what it is, every "have I seen this before" in the system is answering the wrong question.**
