"""THE ORIGINAL `dev_lab.dev.forge*` MODULES -- DATA, one name per module.

The forge half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at
the module-size band, 2026-11-14). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'forgeserve',
    'forgeproduce',
    'forgecarry',
    # See the module docstring above: declared original against a measured 2-name overlap.
    'forge',
    # No consumer had issue/PR verbs or a token installer to fork: each box ran ``gh``/``tea`` or a
    # browser. Checked 2026-10-01 against every consumer's tracked files.
    'forgeauth',
    'forgecli',
    'forgecred',
    'forgefailure',
    'forgework',
    'forgestatus',
    'forgeoutbox',
    'forgelabels',
    'forgepublish',
    'forgeintent',
    'forgenotice',
    'forgetry',
    'forgewait',
    'forgerecords',
    'forgetick',
    'forgeautosync',
    'forgeintegration',
    'forgelanes',
    'forgemerge',
    'forgemessages',  # the message condition split out of forgemerge (2026-11-07)
    # ORIGINAL: split out of forgemerge inside the kit by responsibility (2026-11-13); no consumer held them.
    'forgemergecall',
    'forgemergeready',
    'forgemergewaits',
    'forgereview',
    'forgereview_declared',
    'forgereview_findings',
    # ORIGINAL: the review read the whole diff or nothing; the slice budget and lenses are new here.
    'forgereview_command',
    'forgereview_scope',
    'forgereview_runtimes',
    'forgesecrets',
    'forgepulls',
    'forgesync',
    'forgerun',
    'forgesupersede',
    'forgescope',
    'forgerunpost',
    'forgerunstate',
    'forgeclaim',
    'forgeschedule',
    'forgequeue',
    'forgehosts',
    'forgepoller',
    'forgesettled',
    'forgeprovides',
    'forgetidy',
    'forgereview_claim',
    'forgeoom',
    'forgeslurm',
    # ORIGINAL: a submit detached from the tick under its own lock was never done; split from forgeserve (2026-11-08).
    'forgesubmit',
    'forgeship',
    'forgealarm',
    'forgefleet',
    # ORIGINAL: split out of forgetick/forgeserve inside the kit; no consumer held them.
    'forgetake',
    'forgerounds',
    'forgecoalesce',
    'forgeservesteps',
    'forgeunit',
    'forgeorigin',
    'forgerequest',
    'forgerequesthost',
    'forgerequestpaths',
    # ORIGINAL: shared demand derived from the forge's run records; no consumer read them (D4).
    'forgedemand',
    'forgeissue',
    'forgeroute',
    # ORIGINAL: both are forge mechanisms of 2026-10-22 with no consumer file before them.
    'forgescarce',
    # ORIGINAL: a standing verdict and 'review again' were read inline in forgereview; split out 2026-11-07.
    'forgereview_stands',
    'forgefacts',
    # ORIGINAL: lock freshness and branch set as forge statuses on a PR head (2026-10-24).
    'forgeheadgate',
    'forgestuck',
    'forgewatch',
    # ORIGINAL: the forge's review/security gate, new here; and the in-kit splits of `metrics` and
    # `forge` (a split of a kit module supersedes no CONSUMER file, so it inherits the parent's kind).
    'forgecontexts',
    'forgereview_advice',
    'forgereview_summary',
    'forgesecurity',
    'forgetakeover',
    'forgeaffinity',  # HPC account affinity of verify parts, new here
    'forgeapp',  # a GitHub App as a forge identity (the judge's), new here
    'forgereview_gate',  # the one review gate every merge door reads, split from forgereview_declared
    'forgereview_identity',  # who reviews: the forge's status, never a head's author, new here
    'forgerunshow',  # a cluster run's findings published on the forge, new here
    'forgedraft',  # a PR opens as a draft until its author marks it ready (D53), new here
    'forgebacklog',  # a ready head unreviewed past the bound pages once, new here
    'forgebreakglass',
    'forgeauthnotice',  # the session-start token check: a refused forge token heard before an agent complains
    'forgereview_bundle',
    'forgereview_pointer',
    'forgereview_job',  # an in-kit split of forgetakeover: the forge's review job
    'forgereview_batch',  # the Batch API resume of a pending review, new here
    'forgeprotect',  # branch protection declared, planned and applied on both forges, new here
    # ORIGINAL: split out of `forgework` inside the kit by concept; no consumer held it.
    'forgestamp',
    # ORIGINAL: the poller pass's read memo (2026-11-04); no consumer polled the forge.
    'forgememo',
    # ORIGINAL: the door's label verb (2026-11-10, a repo's needs-consent label); no consumer wrote a label.
    'forgelabel',
    # ORIGINAL: the refusal feedback of `forge auth` (2026-11-10); no consumer recorded a verdict.
    'forgeverdict',
    # ORIGINAL: split out of `forgeauth` inside the kit (2026-11-10); no consumer held it.
    'forgekeyfile',
    # ORIGINAL: the serve step that carries out a data PR's consumer runs (2026-11-11); no consumer held it.
    'forgedataruns',
    # ORIGINAL: branch protection vs a declaration, split out of `forge` by concept (2026-11-14); no consumer held it.
    'forgerule',
    # ORIGINAL: a forge read's busy seconds per phase (2026-11-13, the 170 s queue); no consumer measured it.
    'forgephases',
)
