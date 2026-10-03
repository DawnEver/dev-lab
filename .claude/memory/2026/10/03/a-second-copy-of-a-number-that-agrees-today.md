---
name: a-second-copy-of-a-number-that-agrees-today
description: Sweeping the kit for one fact defined twice found two, and both were live defects — not mere tidiness. alert.py read a channel's reply to EOF because its private copy of the read cap never got the reason transport's copy got; and the HTTP success range existed as four constants in two modules.
created: 2026-10-03
accessed: 2026-10-03
---

# A second copy of a number that agrees today (2026-10-03)

The session's dominant defect is one value carrying two facts. This is its quieter twin: **one fact
carrying two values** — and both instances found by the sweep were live defects rather than tidiness.

## The one that was a live defect

`alert.py` read a channel's reply with `response.read()` — no argument, so **to EOF** — into the
supervisor's own 300M cgroup. `transport.fetch_json` had been fixed for exactly this (`3c6b11e`, "a
reply is read to a cap, not to EOF").

**Why it survived the fix next door:** each call site held its own copy of the number.
`transport.REPLY_KEPT` and a local `alert._REPLY_KEPT`, both 200. They agreed, so nothing looked
wrong — and the day one copy was given a REASON (*"READ to a cap, not written to one"*) was the day
they stopped being the same thing, with nothing to say so. The fix is not just the cap: the local
copy is gone and `BODY_CAP`/`REPLY_KEPT` are imported.

## The one that was four constants for one fact

`OK_FLOOR`/`OK_CEILING` (200/300) in `components/health` judged an endpoint healthy;
`_HTTP_OK_FLOOR`/`_HTTP_OK_CEILING` (200/300) in `alert` judged a channel to have taken a notice. Same
fact, two definitions, and the private pair carried no reason at all. They live in `transport` now —
the module that already owns the HTTP caps — and both callers import them. `health` does **not**
re-export: a name re-exported through the module that merely uses it is precisely how the family gets
two of them.

## The method, which is the transferable part

`grep -rn '^[A-Z_]*: Final'` over the package, sorted **by value**, then read down the collisions. A
sort by value is what makes this a sweep rather than a guess: two constants with the same number are
candidates, and the judgement is whether they share a REASON. Audited the collisions that are fine
and they are recorded as fine — `alert._TIMEOUT` (15) and `systemd._GRACE` (15) are unrelated;
`policy.DEFAULT_WRITE_OFF` (3), `release.DEFAULT_KEEP` (3) and `release.DEFAULT_TOLERANCE` (3) are
three separate judgements; `systemd.OUTPUT_CAP` and `transport.BODY_CAP` are both `64 * 1024` and cap
different sources.

The same sweep over a consumer's package found **no duplicate constant name at all** — every
all-caps constant in it is defined once — so the result there is a clean null, which is worth as
much as the two findings here.

**AND I FIRST WROTE THE CONSUMER'S PATH INTO THIS FILE, WHICH IS A PUBLISHED TREE.** The private
marker guard caught it within the hour, which is the whole argument for having one: the sentence
read better with the path in it, and reading better is exactly the pressure that puts a consumer's
name into a kit that ships to all of them.

**Two copies that agree are not one fact. They are one fact until the day one copy is given a reason.**
