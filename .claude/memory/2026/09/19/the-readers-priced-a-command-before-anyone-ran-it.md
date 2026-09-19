---
name: the-readers-priced-a-command-before-anyone-ran-it
description: The first end-to-end use of syncscope and collectscope against a real proposed command rather than a planted file. The consumers' venvs sit ~20 commits behind the published kit, so refreshing one is the last step between a published source of truth and a consumable one - and that refresh runs the same door that pruned an environment from 113 distributions to 30. Both readers were driven over the four-extra command with two negative controls each, and it scores COMPLETE at the runner and errors=[] at collection. The measurement, the controls, and what it still cannot see.
metadata:
  type: project
created: 2026-09-19
accessed: 2026-09-19
---

# The readers priced a command before anyone ran it

## The situation that needed an answer

`lab-commons` is published at `3e4330d`. Every consumer declares the kit as a BARE git URL with no
ref -- "the latest from that URL" -- so by the declaration the family already has one source of
truth. The consumers' environments do not: they run `0.2.2.dev112+g40d4a8e69`, about twenty commits
behind, so `pytestout`, `doorcensus`, `syncscope`, `collectscope` and the `placed_files`
absolute-path fix **do not exist for any consumer**.

Closing that gap is one install. That install runs the same door which, on 2026-09-18, took an
environment from **113 distributions to 30** and printed its warning afterwards. So the last step
between a published truth and a consumable one is the most dangerous command in the family.

## What was actually done: the readers were pointed at the command

Both readers landed this week for exactly this class, and until now both had only ever been driven
over planted files and recorded rows. Driven over the live motronics manifest:

    syncscope   uv sync --extra all --extra dev --extra img-to-cad --extra tooldrivers
                -> Scope.COMPLETE
                control: bare `uv sync`                       -> Scope.STRANDS

    collectscope, same selection
                -> errors=[]                     degrades=0   unresolved={tomlkit, yaml}
                control: --extra all --extra dev --extra img-to-cad
                -> errors=['pillow']             degrades=0   unresolved={tomlkit, yaml}
                control: --extra pareto --extra dev   (the row called "the sanctioned spelling")
                -> errors=[7 distributions]      degrades=3   unresolved={tomlkit, yaml}

**Both controls red, both layers green.** The greens are therefore a measurement rather than a
silence: a reader that scored everything COMPLETE would have scored the bare sync COMPLETE too, and
a collection reader blind to extras would not have singled out `pillow`.

## The two numbers that make this worth keeping

`--extra all --extra dev --extra img-to-cad` is the incantation recorded THE SAME DAY as "the one
that actually restored the box", and it strands `pillow` at collection. `--extra pareto --extra
dev` is the selection a census row called "the sanctioned spelling", and it strands seven. **Every
selection this family had written down leaves motronics unable to collect its own test tree.** The
four-extra form is the first that does not, and it was arrived at by measurement rather than by
another round of guessing.

`tomlkit` and `yaml` are identical across all three selections, so they are not a property of any
command -- they are the genuinely-undeclared transitive residue, and they stay UNRESOLVED by
construction.

## What this still does not establish

* Both answers come from COMMITTED TEXT. Neither reader knows what a command does on a box.
* `collectscope` cannot see `conftest.py` `collect_ignore`, `importlib`/string imports, or a
  distribution that installs and then fails to LOAD (ABI).
* A green here is about the RUNNER and the COLLECTION, not about whether any test passes.

So this prices the command; it does not promise the outcome. That distinction is the whole reason
the readers report `UNMEASURED` rather than guessing, and it is why the run itself is still a
decision with a person behind it rather than a step an agent takes because a number looked good.

## The shape worth carrying

A dangerous action does not stop being dangerous because it is measured -- but it stops being a
GUESS, and the argument for taking it stops resting on "the last person who did it said this
worked". Every previous incantation in this family had exactly that provenance, and each one was
wrong in a way nobody had instrumented. **The deliverable of a week spent building readers is that
the next hazardous command is priced before it runs, by something that convicts its own controls.**
