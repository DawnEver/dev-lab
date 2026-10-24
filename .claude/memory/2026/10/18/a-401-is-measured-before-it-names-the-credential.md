---
name: a-401-is-measured-before-it-names-the-credential
description: A single gitea 401 was printed as "permanent, re-store the credential" while the same credential authenticated minutes later; the forge client now checks GET /user first. Also: this fix was twice dropped from integrate/main by pushes built on an older tip
created: 2026-10-18
---

# A 401 is measured before it names the credential

- Incident (a consumer repo, 2026-10-18): `forge status list` printed `forge-refused -- retrying cannot
  change this answer ... re-store it: auth login` on a 401; minutes later the same `git credential` token
  authenticated and `git push` had used it throughout. Later that evening `GET /user` itself refused 3/3
  for ~30 min and then cleared untouched -- even a reproduced refusal can be the server's for a while.
- Fix (47d309a): on 401/403 `Client._diagnosis` asks `GET /user` with the same credential; only a refusal
  there names the credential (`AUTH_REMEDY`); otherwise transient, retried, and reported as `AUTH_TRANSIENT`.
  `ForgeCallFailed.credential_refused` is the one predicate.
- Delivery: merged into integrate/main twice (10133cc, 390a6f4); both were dropped by pushes from another
  session built on an older tip (6d69a96, 96a90c8). User ruling: this lane goes only through PR #3
  (https://github.com/DawnEver/lab-commons/pull/3); b354f48 declares the branch in `sessions` so the
  branch-set hook admits it -- the integrator drops that row on merge.
- SUPERSEDED IN PART 2026-10-21: the `GET /user` check used the same stale token, so an EXPIRED OAuth
  access token was still reported as "re-store it". The cause and the refresh fix:
  `2026/10/21/a-gitea-auth-refusal-is-an-expired-oauth-token-and-the-client-refreshes-it.md`.
