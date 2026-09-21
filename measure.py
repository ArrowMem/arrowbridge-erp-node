"""python measure.py [--pack pack]

Prints the frame-count / compression table over the full closed grammar (39 replies,
16,059 raw bytes, SPEC-CONTENT.md's own count): per reply, raw bytes, frames at the 200-byte
and 127-byte PAYLOAD budgets (plain chunking, erp_node.chunk()), 1 frame for ref mode, and
dict-compressed bytes under both of SPEC-CONTENT.md's honest cases:
  (a) dictionary excluding the reply's own source content file (the novel-reply case)
  (b) the full shipping dictionary, reply's own source included (the reference case: this
      node's own pack, matching its own reply, over the air to a second node running the
      same pack)
Never a single best-case ratio; both totals are printed and labelled.
"""
import argparse
import zlib
from pathlib import Path

import build_dict
import erp_node

# Which pack content file a reply's own text is drawn from, for case (a)'s exclusion. ERP,
# ERP LINES and the tier menus are not drawn from one single content file (they are built
# from titles/labels across files plus authored navigation), so case (a) excludes nothing
# extra for them; the full dictionary is used, same as case (b). This is an approximation,
# not the per-string source map the spec's own reply-level number would need -- noted as an
# assumption in the build report.
OWN_FILE = {"ERP BASIC": "content/basic_vehicle.json", "ERP BUSH": "content/bush_lost.json"}


def dict_excluding(pack_dir, exclude_rel):
    root = Path(pack_dir)
    return b"".join((root / f).read_bytes() for f in build_dict.ORDER if f != exclude_rel)


def compressed_len(dictionary, text):
    co = zlib.compressobj(9, zlib.DEFLATED, -15, zdict=dictionary)
    return len(co.compress(text.encode("utf-8")) + co.flush())


def own_file_for(cmd):
    if cmd.startswith("ERP BASIC"):
        return OWN_FILE["ERP BASIC"]
    if cmd.startswith("ERP BUSH"):
        return OWN_FILE["ERP BUSH"]
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pack", default=str(Path(__file__).parent / "pack"))
    a = p.parse_args(argv)
    pack = erp_node.load_pack(a.pack)
    replies = erp_node.grammar_replies(pack)

    full_dict = build_dict.build_dictionary(a.pack)
    excl_cache = {f: dict_excluding(a.pack, f) for f in build_dict.ORDER}

    rows = []
    totals = dict(raw=0, f200=0, f127=0, ref=0, a=0, b=0)
    for cmd, text in replies.items():
        raw = len(text.encode("utf-8"))
        f200 = len(erp_node.chunk(text, 200))
        f127 = len(erp_node.chunk(text, 127))
        excl = excl_cache.get(own_file_for(cmd), full_dict)
        da = compressed_len(excl, text)
        db = compressed_len(full_dict, text)
        rows.append((cmd, raw, f200, f127, da, db))
        totals["raw"] += raw
        totals["f200"] += f200
        totals["f127"] += f127
        totals["ref"] += 1
        totals["a"] += da
        totals["b"] += db

    header = f"{'reply':<20}{'raw':>6}{'f@200':>7}{'f@127':>7}{'ref':>5}{'dict(a)':>9}{'dict(b)':>9}"
    print(header)
    print("-" * len(header))
    for cmd, raw, f200, f127, da, db in rows:
        print(f"{cmd:<20}{raw:>6}{f200:>7}{f127:>7}{1:>5}{da:>9}{db:>9}")
    print("-" * len(header))
    print(f"{'TOTAL':<20}{totals['raw']:>6}{totals['f200']:>7}{totals['f127']:>7}"
          f"{totals['ref']:>5}{totals['a']:>9}{totals['b']:>9}")
    print()
    print(f"case (a), dictionary excludes the reply's own source file: "
          f"{totals['raw']} raw -> {totals['a']} bytes, {totals['raw'] / totals['a']:.3f}x")
    print(f"case (b), reference case, full shipping dictionary: "
          f"{totals['raw']} raw -> {totals['b']} bytes, {totals['raw'] / totals['b']:.3f}x")
    print(f"ref mode (0x03): {totals['ref']} frames total, 41 bytes each, "
          f"regardless of reply length (this node already holds every reply it can emit)")


if __name__ == "__main__":
    main()
