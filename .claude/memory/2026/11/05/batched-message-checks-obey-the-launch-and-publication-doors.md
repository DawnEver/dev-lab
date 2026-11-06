---
name: batched-message-checks-obey-the-launch-and-publication-doors
description: The real PR218 Linux part identifies three architecture failures, repaired without exemptions or changed message semantics.
metadata:
  type: project
---
# Actual forge failure and correction

PR218 head 9516a0d2d069 ran 6380 Linux base tests. The part failed on three
architecture contracts: czbatch spawned Git through subprocess.run instead of
lab_commons.launch.run, and the new public module lacked its inventory bullet
and provenance declaration. Security passed; review and Windows were still
running when this failure was read. No part or review is presumed green.

Route the identical Git argument list and raw-byte capture through the shared
launch door, which owns hidden process creation on Windows. Declare the module
in the actual inventory and original-module registry: this is an extraction of
the kit's existing shell hook, not a superseded consumer fork. No test exemption,
message validator, range, SHA exemption or acceptance policy changes.
