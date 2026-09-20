# pack/ is the ArrowMem ERP pack, vendored unchanged

The files in this directory are the ArrowMem ERP (survival and emergency basics) content
pack, `pack_id` `erp`, `generation` 1, as recorded in `manifest.json` here. They were
copied byte-for-byte from the pack's own repository:

- `manifest.json`
- `citations.json`
- `content/basic_vehicle.json`
- `content/bush_lost.json`
- `safety/hard_lines.json`

**These files must never be edited in this repository.** The node reads them; it does not own
them. A fix, a new step, a French pass, a changed refusal: all of that happens in the pack's
repository and arrives here as a new byte-identical copy with a higher `generation`. Two of
the files carry CRLF line endings and three carry LF; `.gitattributes` tells git to leave both
alone so the copies stay identical to their source.

Every safety string the node emits is one of the strings in these files, verbatim.
`test_erp_node.py` asserts that for every command the node accepts.

Content licence: TO BE CONFIRMED BY ARROWMEM BEFORE PUBLICATION
