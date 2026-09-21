"""python build_dict.py [--pack pack]

Builds the arrowcontent dictionary for this node's own pack: the four pack content files,
concatenated in the exact order pinned by SPEC-CONTENT.md (measured there to compress this
pack's own closed grammar best), no separator bytes. Deterministic: the same pack/ directory
always produces the same bytes and the same dictionary id. Writes pack.dict beside this file
and prints its id. The committed pack.dict is this function's own output, re-run over the
committed pack/SOURCE.md commit; test_erp_node.py asserts the two match byte for byte.
"""
import argparse
import hashlib
from pathlib import Path

# Pinned by SPEC-CONTENT.md "The dictionary artifact": bush_lost.json last, measured to
# compress this pack's own 39-reply grammar best of the four single-file-last orderings.
ORDER = [
    "citations.json",
    "content/basic_vehicle.json",
    "safety/hard_lines.json",
    "content/bush_lost.json",
]


def build_dictionary(pack_dir):
    root = Path(pack_dir)
    return b"".join((root / f).read_bytes() for f in ORDER)


def dictionary_id(dictionary):
    """First 8 bytes of SHA-256, the id arrowcontent.content_id() also produces."""
    return hashlib.sha256(dictionary).digest()[:8]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pack", default=str(Path(__file__).parent / "pack"))
    p.add_argument("--out", default=str(Path(__file__).parent / "pack.dict"))
    a = p.parse_args(argv)
    dictionary = build_dictionary(a.pack)
    Path(a.out).write_bytes(dictionary)
    print(f"{a.out}: {len(dictionary)} bytes, id {dictionary_id(dictionary).hex()}")


if __name__ == "__main__":
    main()
