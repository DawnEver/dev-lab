---
name: box-claim-identity-and-measured-seats
description: the two ledger primitives <consumer> needed to delete its slot store -- a holding's identity (id/key/probe, offline release, exclusive external key) and seats measured by a supply probe
created: 2026-10-17
---
# Box: claim identity and measured seats (2026-10-17)

Asked by <consumer> (PLAN-<consumer>-onto-the-one-box-ledger, BLOCKED on external-claim lookup).

## What landed (lane/ledger-identity)

- `Holding` carries `id`, `key`, `probe` (`None` unless external); `holding.claim` rebuilds the `Claim`,
  so ANY process can `release(holding.claim)` on terminal evidence. The columns already existed in the
  ledger file, so no schema move was needed; older files still upgrade through `_ADDED`.
- `hold(..., key=K)` raises `DuplicateKey` (a `Refused`) while a live EXTERNAL claim (one `persist`ed with a
  probe) holds `K`. Only external claims make a key exclusive -- two in-process runs under one key are fine.
  The check runs after the reap, so a dead probe frees the key and its seats in the same admission.
- Seats are ledger resources with MEASURED supply: `[capabilities.<tool>] supply = [argv]` prints the TOTAL
  seats this box may lend (the licence count, not the free count -- the ledger subtracts its own holders;
  a free count would subtract them twice). `seat_supply()` runs it; a failed/timed-out/non-integer probe
  falls back to the declared `seats`. `Capacity.read()` uses it, so `hold` and the forge box supply see it.

## Decisions and limits

- A measured 0 makes a seat demand "larger than this box" and refused at once rather than queued -- a
  licence server reporting zero seats is treated as no supply, not a busy one.
- `forgeserve`'s host card still lists `declared_seats()` (its rows say "declared, no check").
- The probe runs on every `Capacity.read()` (once per `hold`), bounded by `SUPPLY_S` = 10 s.
