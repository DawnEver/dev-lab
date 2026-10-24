---
name: a-gitea-auth-refusal-is-an-expired-oauth-token-and-the-client-refreshes-it
description: The recurring "forge API token invalid / attempt-1 auth transient" is Git Credential Manager's expiring OAuth access token; git refreshes it on its retry, and the forge API client now does too (reject + fill), so auth login is named only when the store is left empty
created: 2026-10-21
---

# A gitea auth refusal is an expired OAuth token, and the client refreshes it

- Measured 2026-10-21 10:50 (a motronics-studio box): `git credential fill` for the gitea host answered
  username `OAUTH_USER` -- GCM's OAuth store. Its access token expires. `forge auth status` said
  `forge-refused ... re-store it: auth login`; one `git ls-remote origin` (attempt 1 refused, attempt 2 OK)
  and the same `auth status` said "authenticated as MingyangBao". Git had rejected the expired token on the
  401 and its next fill refreshed it. That is also the long-known "attempt-1 transient" on every git verb.
- The 2026-10-18 fix (`a-401-is-measured-before-it-names-the-credential`) asked `GET /user` with the SAME
  stale token, so it confirmed the expiry and still told the user to re-login -- the cause was one layer down.
- Fix: `lab_commons.credentials.refresh_credential` (git credential reject, then fill); `forgework.Client`
  spends it once on a 401 that `GET /user` confirms and retries with the refreshed token
  (`forgework.stored_client` wires it for `client_for` and `forge auth status|check`). A refusal after the
  refresh is `AUTH_REMEDY` (no re-login); a store left empty is `AUTH_GONE` (the one case naming `auth login`).
- The one explanation lives in `docs-src/dev/forge.md` ("A gitea auth refusal is an expired OAuth token");
  the GIT-NETWORK-VERB refusal, the netverb transient row and the `auth` alarm point there.
