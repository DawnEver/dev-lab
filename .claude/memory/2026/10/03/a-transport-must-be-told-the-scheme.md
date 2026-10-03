---
name: a-transport-must-be-told-the-scheme
description: A transport that receives a bare host cannot choose a connection class. One https-only default served both the credential-carrying channels and every health probe, so a probe against loopback spoke TLS at a plain socket and reported a healthy service unreachable.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# A transport must be told the scheme

`Transport` was `Callable[[str, float], HTTPConnection]` — a host and a timeout. The URL was parsed
before the call, and the scheme was thrown away in the parsing:

```python
host = url.removeprefix('https://').removeprefix('http://')
host, _, path = host.partition('/')
connection = transport(host, timeout)
```

A transport handed a bare host cannot tell `https://example.org` from `http://example.org`. The one
that shipped returned `HTTPSConnection` unconditionally, and its docstring was proud of it: *"a
connection that cannot be talked down to plain HTTP."* That is the right stance for an alert channel
carrying an API key. It is the wrong stance for a health probe against `http://127.0.0.1:7001/`.

## How it presented, and why the presentation was worse than the bug

Against the real target the probe failed with `SSLError: WRONG_VERSION_NUMBER`, and the component
reported `api_unreachable` — **critical** — for a service that was answering 200 to everything else
on the box, including the operator's own `curl` run a second earlier.

The second-order damage is the part to remember. `deploy.probe` reaches a **candidate** over
loopback plain HTTP through the same `fetch_json`, so the defect did not merely mislabel a healthy
service: it made the deployment gate refuse **every release**, and its refusal message named the
candidate not answering rather than a transport that could not connect.

## The fix moved a stance back to the party that owns it

Two transports, each with a stated reason, and the scheme carried from the one place that knows it:

* `https_only` — for channels that carry a credential. It **refuses** plain HTTP rather than
  upgrading it, because a silent upgrade and a silent downgrade look identical to the caller.
* `scheme_transport` — for probes, which carry nothing secret. Loopback is plain HTTP because the
  proxy terminates TLS at the edge.

The rule underneath: **the security stance belongs to the channel that carries the secret, not to a
transport shared by every caller.** One default cannot serve both, and sharing one is exactly how the
second case silently became the first.

URL parsing also collapsed into a single `split_url`, because two copies had already drifted — the
probe kept the scheme and the webhook sender dropped it.

## The test that would have caught it

Every existing test injected a double, and **a double agrees with whichever connection class it is
handed**. `test_supervise_transport.py` binds a real `http.server` on port 0 and completes a real
plain-HTTP round trip, because only a socket can tell TLS from plain text.
