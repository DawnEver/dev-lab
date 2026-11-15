---
name: cargo-dependency-network-verbs-need-executed-controls
description: Tests-only scope for Cargo dependency operations through the existing network door
metadata:
  type: project
---

# Cargo dependency network verbs need executed controls

Stage: bounded Cargo network-door feature qualified at fixed 1ba39d51ea12620da559b2dcb0cf05a3816344cf. No actual Cargo dependency operation has run in this feature's qualification.

The public issue search for Cargo in existing titles and bodies returned no matching issue. The installed door currently recognises Git and uv but refuses Cargo update, fetch and generate-lockfile before execution. Those operations can resolve registry or Git dependencies; treating a native build or test as a network-door operation would instead bypass its own producer/admission contract.

The clean independent clone normally fast-forwarded from the completed layout-body receipt to fixed integration 1a2e1866806837f2bb6755cbeb1aa44868ec2934 and cut pr/cargo-network-verbs-1115. The lock did not change. Existing netverb retry, classification, authentication, bounded-process and tag-selection assertions remain untouched.

New controls use the actual is_network_verb and spelled APIs. They retain package selection, dry-run, manifest and target options, an explicit executable path, global configuration and colour options, and the real Rust toolchain-prefix choice. Negative controls distinguish build, test, check, run and metadata, and global help/version/list commands from dependency resolution. All argv must remain unchanged through the door. No real Rust dependency resolution is required to execute these pure classification controls. Production implementation waits for a real full-owner RED.

That prerequisite is now met: Actions 43748061198 measured the complete tests/test_dev_netverb.py at tests-only 4f64f0a399f4777de3c752b1ffd2eca201c7ddd2. The canonical receipt is FAIL, exit 1, environment af1049f8b8bd937b; raw results are seven failed and 64 passed in 12.81 seconds. Exactly the seven new dependency-positive cases failed on actual recognition, while all original controls and the nine new producer/local negatives passed. Original receipt and log are retained in ignored output.

The minimal source adds Cargo and its three dependency verbs to the existing single recognition owner, recognises its valued global options and explicit rustup toolchain prefix, and retains global help/version/list as local refusals. The original argv is never rewritten, a bare Cargo verb is not a new alias, and the existing bounded retry, authentication classification, stop/refusal and Git tag-selection machinery is untouched. This candidate still needs complete owner qualification before a consumer invokes the newly admitted dependency operation.

Actions 43749098362 supplied that complete qualification at fixed 1ba: canonical PASS, exit 0, 92 passed in 11.31 seconds, environment af1049f8b8bd937b. Its four exact complete owner selectors are tests/test_dev_netverb.py, tests/test_arch_every_network_verb_is_retried.py, tests/test_arch_public_surface.py and tests/test_arch_module_size_alarm.py. The original tests-only counterexamples and thresholds remain unchanged. Receipt and verify log are retained in ignored output. This proves the named SDK door population, not a Cargo dependency resolution, native build or consumer test verdict. A consumer can invoke the qualified SDK interpreter with its own working directory and the unchanged Cargo arguments; it must still use its actual native/dependency and measurement owners for subsequent work.
