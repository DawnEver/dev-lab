"""CONSENT CREDENTIALS: the user's per-action consent, signed by one issuer and verified anywhere.

User-approved design 2026-11-07. The ISSUER on the forge host alone holds the TOTP seed and an Ed25519 private key
(:mod:`.issuer`); verifiers hold only the public key; clients hold no secret (:mod:`.client`). A credential is JSON
signed over every field (:mod:`.credential`) for one action of the ONE registry (:mod:`.actions`). The user grants
one in their own terminal (``python -m dev_lab.ops.consent grant <request.json>``); an irreversible action registers
its use online (:func:`.client.admit`). Break-glass waves open on ``breakglass.wave`` credentials
(:mod:`dev_lab.ops.breakglass`).
"""

__all__: list[str] = []
