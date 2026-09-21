# pack/ is the ArrowMem ERP pack, vendored unchanged

The files in this directory are the ArrowMem ERP (survival and emergency basics) content
pack, `pack_id` `erp`, `generation` 1. They were copied byte-for-byte from the pack's own
repository, commit `d9cb26407a74eeca8ac829583b01ee40dd572957`:

- `citations.json`
- `content/basic_vehicle.json`
- `content/bush_lost.json`
- `safety/hard_lines.json`

`manifest.json` is deliberately NOT vendored: it carries the pack's legacy product name and
support address and internal plan-tree paths, none of which belong in a published repository.
The two fields this node ever read from it, the two content file paths above, are now a
one-line constant in `erp_node.py` (`CONTENT_FILES`).

**These files must never be edited in this repository.** The node reads them; it does not own
them. A fix, a new step, a French pass, a changed refusal: all of that happens in the pack's
repository and arrives here as a new byte-identical copy, with the commit hash above updated.

**Re-vendoring must read the git blob, never a working tree.** All four files are pure LF at
the source. Copy them with `git -C <pack repo checkout> show <commit>:<path>` and write the
bytes straight to disk; do not `cp` or drag-and-drop a working-tree copy, especially not from
a Windows checkout of the pack repository, which has no `.gitattributes` of its own and will
silently convert every LF to CRLF on checkout under `core.autocrlf=true`. That exact mistake
shipped once (`content/basic_vehicle.json`, fixed 2026-09-20) and is why this warning is here.
This repository's own `.gitattributes` sets `-text` on `pack/**` so a correct copy, once
committed, can never be re-normalised by a later checkout on any platform - but it cannot fix
a bad copy that was never byte-exact to begin with, which only re-vendoring from the blob can
do.

Every safety string the node emits is one of the strings in these files, verbatim.
`test_erp_node.py` asserts that for every command the node accepts.

Content licence: CC BY 4.0. See `NOTICE.md` for the source bodies this pack draws on and
`LICENSE-CONTENT` for the licence text. The code in this repository (everything outside
`pack/content/`, `pack/safety/`, `pack/citations.json`) is MIT; see the root `LICENSE`.
