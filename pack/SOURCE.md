# pack/ is the ArrowMem ERP pack, vendored unchanged

The files in this directory are the ArrowMem ERP (survival and emergency basics) content
pack, `pack_id` `erp`, `generation` 1. They were copied byte-for-byte from the pack's own
repository, commit `90bee97070ed2be333e9afe496c0f363feb085cb`:

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
One of the files carries CRLF line endings and three carry LF; `.gitattributes` tells git to
leave both alone so the copies stay identical to their source.

Every safety string the node emits is one of the strings in these files, verbatim.
`test_erp_node.py` asserts that for every command the node accepts.

Content licence: CC BY 4.0. See `NOTICE.md` for the source bodies this pack draws on and
`LICENSE-CONTENT` for the licence text. The code in this repository (everything outside
`pack/content/`, `pack/safety/`, `pack/citations.json`) is MIT; see the root `LICENSE`.
