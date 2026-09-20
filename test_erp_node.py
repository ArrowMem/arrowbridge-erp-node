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
MANIFEST_ONLY = {s for s, _ in leaves(json.loads((PACK / "manifest.json").read_text(encoding="utf-8")))} - CONTENT

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

    def test_never_emits_metadata_or_manifest_strings(self):
        for cmd in EVERY_COMMAND + ["nonsense"]:
            out = erp_node.reply(pack, cmd)
            for s in META | MANIFEST_ONLY:  # "en" and "erp" are manifest values too, hence the length gate
                self.assertNotIn(s, out.splitlines(), cmd)
                if len(s) >= 20:  # covers the manifest's legacy product name and support address
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


try:
    import LXMF  # noqa: F401
    import RNS  # noqa: F401
    HAVE_RNS = True
except ImportError:  # pragma: no cover
    HAVE_RNS = False


@unittest.skipUnless(HAVE_RNS, "rns and lxmf not installed")
class LxmfLoopback(unittest.TestCase):
    def test_two_processes_one_shared_instance(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config").write_text(
                "[reticulum]\nenable_transport = No\nshare_instance = Yes\nshared_instance_type = tcp\n"
                f"shared_instance_port = {free_port()}\ninstance_control_port = {free_port()}\n"
                "[logging]\nloglevel = 3\n[interfaces]\n", encoding="utf-8")
            node = subprocess.Popen([sys.executable, str(HERE / "erp_node.py"), "--pack", str(PACK), "--lxmf", "--config", d],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=HERE, text=True)
            try:
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
                client = subprocess.run([sys.executable, __file__, "client", d, addr[0], "ERP BASIC 1"],
                                        capture_output=True, timeout=150, cwd=HERE)
                self.assertEqual(client.stdout.decode("utf-8"), erp_node.reply(pack, "ERP BASIC 1"), client.stderr[-2000:])
            finally:
                node.kill()
                node.wait()


if __name__ == "__main__":
    if sys.argv[1:2] == ["client"]:
        lxmf_client(*sys.argv[2:5])
    unittest.main()
