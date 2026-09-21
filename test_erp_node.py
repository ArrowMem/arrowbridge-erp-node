"""python -m unittest -v

Every grammar branch, the content boundary (every safety line is a pack string, verbatim),
chunk reassembly identity, the stdin transport via subprocess, --sign via arrowenvelope when
it is importable, and an LXMF loopback (two processes on one shared Reticulum instance) when
rns and lxmf are installed.
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import erp_node

HERE = Path(__file__).resolve().parent
PACK = HERE / "pack"
PACK_FILES = ["content/basic_vehicle.json", "content/bush_lost.json", "safety/hard_lines.json", "citations.json"]
pack = erp_node.load_pack(PACK)
BASIC, BUSH = pack["basic"], pack["bush"]
NB, NS = len(BASIC["actions"]), len(BUSH["sections"])


def leaves(x, under_meta=False):
    """(string, is_metadata) for every string in a JSON tree; metadata = under a key starting with _."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, under_meta or k.startswith("_"))
    elif isinstance(x, list):
        for v in x:
            yield from leaves(v, under_meta)
    elif isinstance(x, str):
        yield x, under_meta


RAW = b"".join((PACK / f).read_bytes() for f in PACK_FILES)
ALL = [lf for f in PACK_FILES for lf in leaves(json.loads((PACK / f).read_text(encoding="utf-8")))]
CONTENT = {s for s, meta in ALL if not meta}
META = {s for s, meta in ALL if meta} - CONTENT
# manifest.json is not vendored here on purpose (pack/SOURCE.md): it carries the pack's legacy
# product name and support address, so there is no vendored copy left to leak from at all.

# Everything the node may say that is not a pack string. A new authored line must be added here.
NAV_EXACT = {
    erp_node.UNKNOWN,
    "ArrowMem ERP: survival steps from published sources, exact text, no model. Commands:",
    f"ERP BASIC 1-{NB} - one step. ERP BUSH 1-{NS} - one section. ERP BUSH 1.1 - one step",
    "ERP LINES - what this node will not answer",
    "ERP SRC <source id> - the citation for a step",
}
NAV_LINE = re.compile(r"SRC [a-z0-9_]+|Withheld: [a-z0-9_]+ \(see ERP LINES\)")
NAV_PREFIX = re.compile(r"(ERP (BASIC|BUSH) - |BASIC: |BUSH: |BUSH [0-9]+: |[0-9]+(\.[0-9]+)?\. |[a-z0-9_]+: )")

EVERY_COMMAND = (["ERP", "ERP BASIC", "ERP BUSH", "ERP LINES"]
                 + [f"ERP BASIC {i}" for i in range(1, NB + 1)]
                 + [f"ERP BUSH {i}" for i in range(1, NS + 1)]
                 + [f"ERP BUSH {i}.{j}" for i, s in enumerate(BUSH["sections"], 1) for j in range(1, len(s["actions"]) + 1)]
                 + [f"ERP SRC {k}" for k in pack["src"]])
UNKNOWN_REPLY = erp_node.UNKNOWN + "\n" + pack["floor"]


def strip_prefixes(parts):
    return [re.sub(r"^\[[0-9]+/[0-9]+\] ", "", p) for p in parts]


class Grammar(unittest.TestCase):
    def r(self, cmd):
        return erp_node.reply(pack, cmd)

    def test_menu_names_both_tiers(self):
        menu = self.r("ERP").splitlines()
        self.assertIn(f"ERP BASIC - {BASIC['title_en']}", menu)
        self.assertIn(f"ERP BUSH - {BUSH['title_en']}", menu)
        self.assertIn(f"ERP BASIC 1-{NB} - one step. ERP BUSH 1-{NS} - one section. ERP BUSH 1.1 - one step", menu)

    def test_basic_lists_every_step_in_order(self):
        lines = self.r("ERP BASIC").splitlines()
        self.assertEqual(lines[0], f"BASIC: {BASIC['title_en']}")
        self.assertEqual(lines[1], BASIC["who_this_is_for_en"])
        for i, a in enumerate(BASIC["actions"], 1):
            self.assertEqual(lines[1 + i], f"{i}. {a['text_en']}")
        self.assertIn(BASIC["withheld_from_this_scenario"][1]["text_en"], lines)  # named, not silently missing
        self.assertIn("Withheld: no_vehicle_headlight_instruction (see ERP LINES)", lines)

    def test_basic_step_is_text_plus_source_id(self):
        for i, a in enumerate(BASIC["actions"], 1):
            self.assertEqual(self.r(f"ERP BASIC {i}"), f"{i}. {a['text_en']}\nSRC {a['source_id']}")

    def test_bush_lists_section_titles(self):
        lines = self.r("ERP BUSH").splitlines()
        self.assertEqual(lines[:2], [f"BUSH: {BUSH['title_en']}", BUSH["who_this_is_for_en"]])
        self.assertEqual(lines[2:], [f"{i}. {s['title_en']}" for i, s in enumerate(BUSH["sections"], 1)])

    def test_bush_section_and_step(self):
        for i, s in enumerate(BUSH["sections"], 1):
            lines = self.r(f"ERP BUSH {i}").splitlines()
            self.assertEqual(lines[0], f"BUSH {i}: {s['title_en']}")
            for j, a in enumerate(s["actions"], 1):
                self.assertEqual(lines[j], f"{i}.{j}. {a['text_en']}")
                self.assertEqual(self.r(f"ERP BUSH {i}.{j}"), f"{i}.{j}. {a['text_en']}\nSRC {a['source_id']}")
            for w in s.get("withheld", []):
                self.assertIn(f"Withheld: {w['reason_id']} (see ERP LINES)", lines)

    def test_lines_is_every_refusal_verbatim(self):
        self.assertEqual(self.r("ERP LINES"), "\n".join(f"{x['id']}: {x['text_en']}" for x in pack["lines"]))
        self.assertEqual(len(pack["lines"]), 11)

    def test_src(self):
        self.assertEqual(self.r("ERP SRC bush_stay_put"), "bush_stay_put: " + pack["src"]["bush_stay_put"])
        for a in BASIC["actions"] + [a for s in BUSH["sections"] for a in s["actions"]]:
            self.assertIn(a["source_id"], pack["src"])  # every step's source id resolves

    def test_case_and_whitespace(self):
        self.assertEqual(self.r("  erp   basic  1 \r\n"), self.r("ERP BASIC 1"))
        self.assertEqual(self.r("\tErP\tBuSh\t2.3"), self.r("ERP BUSH 2.3"))
        self.assertEqual(self.r("erp src BUSH_STAY_PUT"), self.r("ERP SRC bush_stay_put"))
        self.assertEqual(self.r(" erp "), self.r("ERP"))

    def test_unknown_and_out_of_range(self):
        for cmd in ["", "hello", "help im lost", "ERP FOO", "ERPX", "BASIC", "ERP BASIC 0", f"ERP BASIC {NB + 1}",
                    "ERP BASIC -1", "ERP BASIC 1.1", "ERP BASIC 1 2", "ERP BASIC x", "ERP BASIC 1_0",
                    f"ERP BUSH {NS + 1}", "ERP BUSH 1.0", "ERP BUSH 1.9", "ERP BUSH 1.2.3", "ERP BUSH .", "ERP BUSH 1.",
                    "ERP LINES 1", "ERP SRC", "ERP SRC nope", "ERP SRC _default", "ERP SRC _note", "ERP SRC a b"]:
            self.assertEqual(self.r(cmd), UNKNOWN_REPLY, cmd)

    def test_floor_is_a_pack_hard_line(self):
        self.assertEqual(pack["floor"], next(x["text_en"] for x in pack["lines"] if x["id"] == "no_trauma_or_first_aid_content"))


class ContentBoundary(unittest.TestCase):
    def test_every_emitted_line_is_navigation_or_a_verbatim_pack_string(self):
        seen = set()
        for cmd in EVERY_COMMAND:
            for line in erp_node.reply(pack, cmd).splitlines():
                if line in NAV_EXACT or NAV_LINE.fullmatch(line):
                    continue
                m = NAV_PREFIX.match(line)
                body = line[m.end():] if m and line[m.end():] in CONTENT else line
                self.assertIn(body, CONTENT, f"{cmd!r} emitted a line that is not a pack string: {line!r}")
                self.assertIn(body.encode("utf-8"), RAW, f"not a byte-exact substring of a pack file: {line!r}")
                seen.add(body)
        for a in BASIC["actions"] + [a for s in BUSH["sections"] for a in s["actions"]]:
            self.assertIn(a["text_en"], seen)  # every step is reachable
        for x in pack["lines"]:
            self.assertIn(x["text_en"], seen)

    def test_never_emits_metadata_strings(self):
        for cmd in EVERY_COMMAND + ["nonsense"]:
            out = erp_node.reply(pack, cmd)
            for s in META:
                self.assertNotIn(s, out.splitlines(), cmd)
                if len(s) >= 20:  # a short metadata value could coincide with real content
                    self.assertNotIn(s, out, cmd)
            self.assertNotIn("note_en", out)
            for a in BASIC["actions"]:
                self.assertNotIn(a.get("note_en", "\0"), out)  # maintainer notes stay in the file

    def test_pack_strings_have_no_newline_and_order_matches_position(self):
        for s in CONTENT:  # the stdin blank-line terminator depends on this
            self.assertNotIn("\n", s)
        for cmd in EVERY_COMMAND:
            self.assertNotIn("\n\n", erp_node.reply(pack, cmd))
        for i, a in enumerate(BASIC["actions"], 1):
            self.assertEqual(a["order"], i)
        for s in BUSH["sections"]:
            for j, a in enumerate(s["actions"], 1):
                self.assertEqual(a["order"], j)


class Chunking(unittest.TestCase):
    def test_identity_and_budget(self):
        for cmd in EVERY_COMMAND + ["x"]:
            text = erp_node.reply(pack, cmd)
            self.assertEqual(erp_node.chunk(text, 0), [text])
            for n in (16, 40, 64, 127, 200, 500, 10000):
                parts = erp_node.chunk(text, n)
                self.assertEqual("".join(strip_prefixes(parts)), text, (cmd, n))
                for p in parts:
                    self.assertLessEqual(len(p), n, (cmd, n, p))
                if len(parts) > 1:
                    k = len(parts)
                    self.assertEqual([p.split(" ", 1)[0] for p in parts], [f"[{i}/{k}]" for i in range(1, k + 1)])
                else:
                    self.assertEqual(parts, [text])

    def test_prefers_line_boundaries(self):
        text = erp_node.reply(pack, "ERP BASIC")
        n = max(len(l) for l in text.splitlines()) + 8  # every line fits, so no line may be split
        for p in erp_node.chunk(text, n)[:-1]:
            self.assertTrue(p.endswith("\n"), repr(p[-40:]))

    def test_never_splits_a_word_when_a_space_exists(self):
        text = "aaa bbb ccc ddd eee fff ggg hhh iii jjj kkk lll mmm nnn ooo ppp qqq rrr sss ttt"
        for p in erp_node.chunk(text, 20)[:-1]:
            self.assertTrue(p.endswith(" "), repr(p))

    def test_rejects_absurd_budget(self):
        with self.assertRaises(ValueError):
            erp_node.chunk("x" * 100, 5)


def run_node(*args, stdin_text):
    return subprocess.run([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), *args],
                          input=stdin_text.encode("utf-8"), capture_output=True, timeout=60, cwd=HERE)


class StdinTransport(unittest.TestCase):
    def test_round_trip(self):
        out = run_node(stdin_text="ERP BASIC 1\n\n  erp  \nnonsense\r\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        expected = "".join(erp_node.reply(pack, c) + "\n\n" for c in ["ERP BASIC 1", "ERP", "nonsense"])
        self.assertEqual(out.stdout.decode("utf-8"), expected)

    def test_chunked_round_trip(self):
        out = run_node("--max-chars", "100", stdin_text="ERP BUSH 2\nERP\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        replies = out.stdout.decode("utf-8").split("\n\n")
        self.assertEqual(replies[-1], "")
        self.assertEqual(len(replies), 3)  # exactly one blank line per reply
        for got, cmd in zip(replies, ["ERP BUSH 2", "ERP"]):
            parts = re.split(r"(?:^|\n)(?=\[[0-9]+/[0-9]+\] )", got)
            parts = [p for p in parts if p]
            self.assertEqual(len(parts), len(erp_node.chunk(erp_node.reply(pack, cmd), 100)))
            for p in parts:
                self.assertLessEqual(len(p), 100)


try:
    sys.path.append(str(HERE.parent / "arrowmem-envelope"))
    import arrowenvelope as ae
except ImportError:  # pragma: no cover
    ae = None


@unittest.skipUnless(ae, "arrowenvelope not importable (sibling checkout or PYTHONPATH)")
class Signing(unittest.TestCase):
    def test_each_chunk_is_a_verifiable_envelope(self):
        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "node.key"
            sk = ae.generate()
            ae.save_key(sk, key)
            keys = {ae.key_id(ae.public_bytes(sk)): ae.public_bytes(sk)}
            out = run_node("--sign", str(key), "--max-chars", "127", stdin_text="ERP BASIC 2\n")
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.decode("ascii").split("\n")
            self.assertEqual(lines[-2:], ["", ""])
            opened = [ae.open(bytes.fromhex(l), keys).decode("utf-8") for l in lines[:-2]]
            self.assertEqual(opened, erp_node.chunk(erp_node.reply(pack, "ERP BASIC 2"), 127))
            self.assertEqual("".join(strip_prefixes(opened)), erp_node.reply(pack, "ERP BASIC 2"))
            with self.assertRaises(ae.EnvelopeError):
                ae.open(bytes.fromhex(lines[0]), {})


try:
    sys.path.append(str(HERE.parent / "arrowmem-envelope"))
    import arrowcontent as ac
except ImportError:  # pragma: no cover
    ac = None

import build_dict

GRAMMAR = erp_node.grammar_replies(pack)


class DictionaryBuild(unittest.TestCase):
    def test_dictionary_id_matches_spec(self):
        dictionary = build_dict.build_dictionary(PACK)
        self.assertEqual(len(dictionary), 29864)
        self.assertEqual(build_dict.dictionary_id(dictionary).hex(), "5ffbd490ada4f969")

    def test_committed_pack_dict_matches_a_fresh_build(self):
        committed = (HERE / "pack.dict").read_bytes()
        self.assertEqual(committed, build_dict.build_dictionary(PACK))

    def test_grammar_reply_count_matches_spec_measurement(self):
        self.assertEqual(len(GRAMMAR), 39)
        self.assertEqual(sum(len(t) for t in GRAMMAR.values()), 16059)


@unittest.skipUnless(ac, "arrowcontent not importable (sibling checkout or PYTHONPATH)")
class ContentFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = build_dict.build_dictionary(PACK)
        cls.index = erp_node.content_index(ac, pack)

    def test_red_wrong_dictionary_id_is_refused_not_silently_accepted(self):
        # RED FIRST (run before resolve_reference existed here): a decoder that trusts a
        # frame's claimed corpus id without checking it against the corpus it actually holds
        # must be caught, not accepted.
        frame = ac.build_reference(self.dictionary, GRAMMAR["ERP"].encode("utf-8"))
        with self.assertRaisesRegex(ac.ContentError, "reference not held"):
            ac.resolve_reference(frame, b"not the real dictionary", self.index)

    def test_ref_round_trip_every_reply(self):
        for cmd, text in GRAMMAR.items():
            frames = erp_node.content_frames(ac, self.dictionary, "ref", text, 0)
            self.assertEqual(len(frames), 1, cmd)
            self.assertEqual(len(frames[0]), 41, cmd)
            out = ac.resolve_reference(frames[0], self.dictionary, self.index)
            self.assertEqual(out, text.encode("utf-8"), cmd)

    def test_dict_round_trip_every_reply(self):
        dictionaries = {ac.content_id(self.dictionary): self.dictionary}
        for cmd, text in GRAMMAR.items():
            frames = erp_node.content_frames(ac, self.dictionary, "dict", text, 127)
            decoded_parts = [ac.decode_compressed(f, dictionaries).decode("utf-8") for f in frames]
            self.assertEqual("".join(strip_prefixes(decoded_parts)), text, cmd)

    def test_reference_not_held_unknown_object(self):
        bogus = ac.build_reference(self.dictionary, b"not a real reply")
        with self.assertRaisesRegex(ac.ContentError, "reference not held"):
            ac.resolve_reference(bogus, self.dictionary, self.index)

    def test_named_errors(self):
        did = ac.content_id(self.dictionary)
        with self.assertRaisesRegex(ac.ContentError, "not a compressed frame"):
            ac.decode_compressed(b"\x04\x00", {did: self.dictionary})
        with self.assertRaisesRegex(ac.ContentError, "unknown dictionary"):
            ac.decode_compressed(ac.build_compressed(self.dictionary, b"x"), {})
        with self.assertRaisesRegex(ac.ContentError, "bad inflate"):
            ac.decode_compressed(ac.COMPRESSED + did + b"\xff\xff\xff\xff", {did: self.dictionary})
        big = ac.build_compressed(self.dictionary, b"x" * 10000)
        with self.assertRaisesRegex(ac.ContentError, "too long"):
            ac.decode_compressed(big, {did: self.dictionary})

    def test_cli_ref_mode_through_decode(self):
        out = subprocess.run([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--content", "ref"],
                             input=b"ERP BASIC 3\n", capture_output=True, timeout=60, cwd=HERE)
        self.assertEqual(out.returncode, 0, out.stderr)
        frame_lines = [l for l in out.stdout.decode("ascii").splitlines() if l]
        self.assertEqual(len(frame_lines), 1)
        self.assertEqual(len(bytes.fromhex(frame_lines[0])), 41)
        back = subprocess.run([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--decode"],
                              input=out.stdout, capture_output=True, timeout=60, cwd=HERE)
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertEqual(back.stdout.decode("utf-8").strip("\n"), GRAMMAR["ERP BASIC 3"])

    def test_cli_dict_mode_through_decode(self):
        # ERP LINES: multi-frame at --max-chars 127, and its own text has internal newlines,
        # so reassembly is checked frame by frame against erp_node.chunk()'s own parts rather
        # than by re-splitting --decode's line-oriented stdout (which is not itself an
        # unambiguous frame separator once a decoded chunk contains a newline).
        out = subprocess.run([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK),
                              "--content", "dict", "--max-chars", "127"],
                             input=b"ERP LINES\n", capture_output=True, timeout=60, cwd=HERE)
        self.assertEqual(out.returncode, 0, out.stderr)
        frame_lines = [l for l in out.stdout.decode("ascii").splitlines() if l]
        expected_parts = erp_node.chunk(GRAMMAR["ERP LINES"], 127)
        self.assertEqual(len(frame_lines), len(expected_parts))
        dictionaries = {ac.content_id(self.dictionary): self.dictionary}
        decoded_parts = [ac.decode_compressed(bytes.fromhex(l), dictionaries).decode("utf-8") for l in frame_lines]
        self.assertEqual(decoded_parts, expected_parts)
        self.assertEqual("".join(strip_prefixes(decoded_parts)), GRAMMAR["ERP LINES"])

    def test_cli_decode_reports_named_error_and_exits_nonzero(self):
        garbage = (b"\x04" + ac.content_id(self.dictionary) + b"\xff\xff\xff\xff").hex() + "\n"
        out = subprocess.run([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--decode"],
                             input=garbage.encode("ascii"), capture_output=True, timeout=60, cwd=HERE)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.decode("ascii").strip(), "bad inflate")


class Padding(unittest.TestCase):
    def test_red_pad_smaller_than_frame_raises_not_truncates(self):
        # RED FIRST: a --pad that silently truncated an oversized frame would corrupt it;
        # it must instead fail loudly, and it must not be reachable via truncation at all.
        with self.assertRaises(ValueError):
            erp_node.apply_pad(b"abcdef", 3)
        with self.assertRaises(ValueError):
            erp_node.apply_pad_text("abcdef", 3)

    def test_apply_pad_fixed_size_round_trip(self):
        frame = b"\x04" + b"\x00" * 8 + b"x"
        padded = erp_node.apply_pad(frame, 20)
        self.assertEqual(len(padded), 20)
        self.assertTrue(padded.endswith(b"\x00" * (20 - len(frame))))
        self.assertEqual(padded[:len(frame)], frame)

    def test_apply_pad_zero_n_is_a_no_op(self):
        self.assertEqual(erp_node.apply_pad(b"abc", 0), b"abc")
        self.assertEqual(erp_node.apply_pad_text("abc", 0), "abc")

    def test_apply_pad_text_uses_spaces_not_newlines(self):
        padded = erp_node.apply_pad_text("hi", 5)
        self.assertEqual(padded, "hi   ")

    def test_pad_content_frames_round_trip_after_strip_ref_and_dict(self):
        ac, dictionary = erp_node.load_content(str(PACK))
        index = erp_node.content_index(ac, pack)
        dictionaries = {ac.content_id(dictionary): dictionary}
        for cmd, text in GRAMMAR.items():
            for frame in erp_node.content_frames(ac, dictionary, "ref", text, 127):
                padded = erp_node.apply_pad(frame, 200)
                self.assertEqual(len(padded), 200)
                self.assertEqual(ac.resolve_reference(padded, dictionary, index), text.encode("utf-8"))
            expected_parts = erp_node.chunk(text, 127)
            for frame, part in zip(erp_node.content_frames(ac, dictionary, "dict", text, 127), expected_parts):
                padded = erp_node.apply_pad(frame, 200)
                self.assertEqual(len(padded), 200)
                self.assertEqual(ac.decode_compressed(padded, dictionaries), part.encode("utf-8"))

    def test_pad_plain_chunk_strip_round_trip(self):
        for cmd, text in GRAMMAR.items():
            for part in erp_node.chunk(text, 127):
                padded = erp_node.apply_pad_text(part, 200)
                self.assertEqual(len(padded.encode("utf-8")), 200)
                self.assertEqual(padded.rstrip(" "), part.rstrip(" "))

    def test_argparse_refuses_pad_below_max_chars(self):
        out = run_node("--max-chars", "50", "--pad", "40", stdin_text="ERP\n")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(b"--pad", out.stderr)

    def test_argparse_refuses_pad_without_max_chars(self):
        out = run_node("--pad", "50", stdin_text="ERP\n")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(b"--pad", out.stderr)

    def test_cli_pad_produces_fixed_length_frames(self):
        out = run_node("--max-chars", "127", "--pad", "200", "--content", "ref", stdin_text="ERP BASIC 3\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = [l for l in out.stdout.decode("ascii").splitlines() if l]
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(bytes.fromhex(lines[0])), 200)


class Scheduling(unittest.TestCase):
    def test_output_appears_at_the_tick_not_before(self):
        # A single reply queued immediately must not appear until the first cadence tick;
        # wall time under 2s (every=0.4, expect the blank-line-terminated block by ~0.4-0.8s).
        p = subprocess.Popen(
            [sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--every", "0.4"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=HERE)
        p.stdin.write(b"ERP\n")
        p.stdin.flush()
        started = time.monotonic()
        result = {}

        def reader():
            got = b""
            while b"\n\n" not in got:
                b = p.stdout.read(1)
                if not b:
                    break
                got += b
            result["got"] = got
            result["elapsed"] = time.monotonic() - started

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=1.8)
        p.stdin.close()
        p.kill()
        p.wait()
        self.assertIn(b"\n\n", result.get("got", b""), result)
        self.assertGreaterEqual(result["elapsed"], 0.3, "reply appeared before the first tick")

    def test_no_reply_queued_a_tick_writes_nothing(self):
        out = run_node("--every", "0.2", stdin_text="")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, b"")

    def test_every_refused_with_decode_or_lxmf(self):
        out = run_node("--every", "0.2", "--decode", stdin_text="")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(b"--every", out.stderr)


class PlainModeRegression(unittest.TestCase):
    def test_content_flag_default_is_plain_and_unchanged(self):
        # Same expectation StdinTransport.test_round_trip already asserts; restated here next
        # to the new --content flag so a future reader sees plain mode was checked against it.
        out = run_node(stdin_text="ERP BASIC 1\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.decode("utf-8"), erp_node.reply(pack, "ERP BASIC 1") + "\n\n")


class LxmfPeerMode(unittest.TestCase):
    """record_holds and lxmf_mode are pure (no RNS/LXMF object), so this needs no rns/lxmf
    install and no subprocess: the RED case (an announced peer still answered plain) is
    exactly what a broken lxmf_mode would return here."""

    def test_recorded_peer_gets_dict_regardless_of_content_flag(self):
        held = {}
        our_id = b"\x11" * 8
        self.assertTrue(erp_node.record_holds(b"peerA", our_id, our_id, held))
        self.assertEqual(erp_node.lxmf_mode(b"peerA", held, "plain"), "dict")
        self.assertEqual(erp_node.lxmf_mode(b"peerA", held, "ref"), "dict")

    def test_unrecorded_peer_gets_the_content_flag_value(self):
        held = {}
        self.assertEqual(erp_node.lxmf_mode(b"peerB", held, "plain"), "plain")
        self.assertEqual(erp_node.lxmf_mode(b"peerB", held, "ref"), "ref")

    def test_wrong_id_is_never_recorded(self):
        held = {}
        our_id, other_id = b"\x11" * 8, b"\x22" * 8
        self.assertFalse(erp_node.record_holds(b"peerC", other_id, our_id, held))
        self.assertEqual(held, {})
        self.assertEqual(erp_node.lxmf_mode(b"peerC", held, "plain"), "plain")

    def test_load_content_optional_returns_none_on_missing_arrowcontent(self):
        # Regression: --lxmf must not hard-require arrowcontent (a plain-only node needs
        # only rns/lxmf). Patch the import to fail exactly as a clean checkout with no
        # sibling arrowmem-envelope would, and check the graceful (None, None), no traceback.
        with mock.patch.object(erp_node, "load_content", side_effect=ImportError("no module named arrowcontent")):
            self.assertEqual(erp_node.load_content_optional(str(PACK)), (None, None))

    def test_load_content_optional_passes_through_when_present(self):
        ac_mod, dictionary = object(), object()
        with mock.patch.object(erp_node, "load_content", return_value=(ac_mod, dictionary)):
            self.assertEqual(erp_node.load_content_optional(str(PACK)), (ac_mod, dictionary))

    def test_looks_like_holds_shape_check(self):
        self.assertTrue(erp_node.looks_like_holds(b"\x05" + b"\x11" * 8))
        self.assertTrue(erp_node.looks_like_holds(b"\x05" + b"\x11" * 8 + b"\x00\x00"))  # padded
        self.assertFalse(erp_node.looks_like_holds(b"\x05" + b"\x11" * 7))  # too short
        self.assertFalse(erp_node.looks_like_holds(b"ERP BASIC 1"))
        self.assertFalse(erp_node.looks_like_holds(b""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def lxmf_client(configdir, node_hash_hex, command):
    """Second process for the loopback test: announce, find the node, send, print the reply."""
    import LXMF
    import RNS
    RNS.Reticulum(configdir=configdir)
    ident = RNS.Identity()
    router = LXMF.LXMRouter(identity=ident, storagepath=configdir + "/client")
    me = router.register_delivery_identity(ident, display_name="loopback client")
    got = []
    router.register_delivery_callback(lambda m: got.append(m.content_as_string()))
    router.announce(me.hash)
    h = bytes.fromhex(node_hash_hex)
    RNS.Transport.request_path(h)
    deadline = time.time() + 60
    while not RNS.Transport.has_path(h) and time.time() < deadline:
        time.sleep(0.2)
    dest = RNS.Destination(RNS.Identity.recall(h), RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    router.handle_outbound(LXMF.LXMessage(dest, me, command))
    deadline = time.time() + 60
    while not got and time.time() < deadline:
        time.sleep(0.2)
    sys.stdout.buffer.write((got[0] if got else "").encode("utf-8"))  # bytes: no CRLF translation
    sys.stdout.flush()
    os._exit(0)


def lxmf_client_holds(configdir, node_hash_hex, holds_hex, command):
    """Third process: send a raw 0x05 HOLDS frame (hex on argv), then `command`, and print
    the reply's RAW bytes (not content_as_string, which would corrupt a binary 0x04 reply).
    Ordering the HOLDS frame before the command relies only on the client-side sleep below:
    each inbound message on the node runs in its own daemon thread, so nothing on the node
    side orders them."""
    import LXMF
    import RNS
    RNS.Reticulum(configdir=configdir)
    ident = RNS.Identity()
    router = LXMF.LXMRouter(identity=ident, storagepath=configdir + "/client")
    me = router.register_delivery_identity(ident, display_name="loopback client")
    got = []
    router.register_delivery_callback(lambda m: got.append(m.content))
    router.announce(me.hash)
    h = bytes.fromhex(node_hash_hex)
    RNS.Transport.request_path(h)
    deadline = time.time() + 60
    while not RNS.Transport.has_path(h) and time.time() < deadline:
        time.sleep(0.2)
    dest = RNS.Destination(RNS.Identity.recall(h), RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    router.handle_outbound(LXMF.LXMessage(dest, me, bytes.fromhex(holds_hex)))
    time.sleep(1.0)  # let the HOLDS frame be recorded before the real command goes out
    router.handle_outbound(LXMF.LXMessage(dest, me, command))
    deadline = time.time() + 60
    while not got and time.time() < deadline:
        time.sleep(0.2)
    sys.stdout.buffer.write(got[0] if got else b"")
    sys.stdout.flush()
    os._exit(0)


try:
    import LXMF  # noqa: F401
    import RNS  # noqa: F401
    HAVE_RNS = True
except ImportError:  # pragma: no cover
    HAVE_RNS = False


@unittest.skipUnless(HAVE_RNS, "rns and lxmf not installed")
class LxmfLoopback(unittest.TestCase):
    def _start_node(self, d, *extra_args):
        (Path(d) / "config").write_text(
            "[reticulum]\nenable_transport = No\nshare_instance = Yes\nshared_instance_type = tcp\n"
            f"shared_instance_port = {free_port()}\ninstance_control_port = {free_port()}\n"
            "[logging]\nloglevel = 3\n[interfaces]\n", encoding="utf-8")
        node = subprocess.Popen(
            [sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--lxmf", "--config", d, *extra_args],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=HERE, text=True)
        addr = []
        def read_addr():
            for line in node.stderr:
                if "LXMF address: " in line:
                    addr.append(line.split("LXMF address: ")[1].strip())
                    break
        threading.Thread(target=read_addr, daemon=True).start()
        for _ in range(300):
            if addr or node.poll() is not None:
                break
            time.sleep(0.2)
        self.assertTrue(addr, "node never printed its LXMF address")
        self.assertEqual(len(addr[0]), 32)
        return node, addr[0]

    def test_two_processes_one_shared_instance(self):
        with tempfile.TemporaryDirectory() as d:
            node, addr = self._start_node(d)
            try:
                client = subprocess.run([sys.executable, __file__, "client", d, addr, "ERP BASIC 1"],
                                        capture_output=True, timeout=150, cwd=HERE)
                self.assertEqual(client.stdout.decode("utf-8"), erp_node.reply(pack, "ERP BASIC 1"), client.stderr[-2000:])
            finally:
                node.kill()
                node.wait()

    @unittest.skipUnless(ac, "arrowcontent not importable (sibling checkout or PYTHONPATH)")
    def test_holds_frame_then_dict_reply(self):
        # RED case this proves fixed: on de8990c an announced peer was still answered plain
        # (serve_lxmf never read a 0x05 at all). Node started with no --content flag (default
        # plain), so a dict-mode reply here can only come from the peer's own 0x05 HOLDS.
        dictionary = build_dict.build_dictionary(PACK)
        did = ac.content_id(dictionary)
        holds_hex = (b"\x05" + did).hex()
        self.assertEqual(holds_hex, "055ffbd490ada4f969")
        with tempfile.TemporaryDirectory() as d:
            node, addr = self._start_node(d)
            try:
                client = subprocess.run(
                    [sys.executable, __file__, "clientholds", d, addr, holds_hex, "ERP BASIC 1"],
                    capture_output=True, timeout=150, cwd=HERE)
                reply_bytes = client.stdout
                self.assertEqual(reply_bytes[:1], b"\x04", client.stderr[-2000:])
                decoded = ac.decode_compressed(reply_bytes, {did: dictionary})
                self.assertEqual(decoded.decode("utf-8"), erp_node.reply(pack, "ERP BASIC 1"))
            finally:
                node.kill()
                node.wait()


if __name__ == "__main__":
    if sys.argv[1:2] == ["client"]:
        lxmf_client(*sys.argv[2:5])
    elif sys.argv[1:2] == ["clientholds"]:
        lxmf_client_holds(*sys.argv[2:6])
    unittest.main()
