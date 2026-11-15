---
name: cargo-dependency-network-verbs-need-executed-controls
description: Tests-only scope for Cargo dependency operations through the existing network door
metadata:
  type: project
---

# Cargo dependency network verbs need executed controls

Stage: tests-only candidate, NOT_RUN. No Cargo dependency operation or production change has run.

The public issue search for Cargo in existing titles and bodies returned no matching issue. The installed door currently recognises Git and uv but refuses Cargo update, fetch and generate-lockfile before execution. Those operations can resolve registry or Git dependencies; treating a native build or test as a network-door operation would instead bypass its own producer/admission contract.

The clean independent clone normally fast-forwarded from the completed layout-body receipt to fixed integration 1a2e1866806837f2bb6755cbeb1aa44868ec2934 and cut pr/cargo-network-verbs-1115. The lock did not change. Existing netverb retry, classification, authentication, bounded-process and tag-selection assertions remain untouched.

New controls use the actual is_network_verb and spelled APIs. They retain package selection, dry-run, manifest and target options, an explicit executable path, global configuration and colour options, and the real Rust toolchain-prefix choice. Negative controls distinguish build, test, check, run and metadata, and global help/version/list commands from dependency resolution. All argv must remain unchanged through the door. No real Rust dependency resolution is required to execute these pure classification controls. Production implementation waits for a real full-owner RED.
