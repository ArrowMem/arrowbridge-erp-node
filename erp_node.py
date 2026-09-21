"""ArrowMem ERP survival node. A closed set of commands in, the pack's exact strings out.

No model, no internet, no free text. Every safety string this file emits is a byte-exact
string from pack/ (see pack/SOURCE.md). The only authored strings are navigation.
"""
import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

NUM = re.compile(r"[0-9]+")  # not int(): int() accepts "-1", "1_0" and non-ASCII digits
UNKNOWN = "Unknown command. Send ERP for the menu."
# The floor under every unknown command is the pack's own first-aid refusal, verbatim (it ends
# in "call 911"). A prior holding-text draft was rejected here: it said guided support "is
# not available in this tool yet" and pointed at "resources below", both false on this node.
FLOOR_ID = "no_trauma_or_first_aid_content"


# pack/manifest.json is not vendored here (it carries brand and internal-path bytes that never
# ship publicly); these two paths are its only fields this node ever read. See pack/SOURCE.md.
CONTENT_FILES = {"basic": "content/basic_vehicle.json", "bush": "content/bush_lost.json"}


def load_pack(pack_dir):
    root = Path(pack_dir)
    read = lambda rel: json.loads((root / rel).read_text(encoding="utf-8"))
    lines = read("safety/hard_lines.json")["refusals"]
    return {
        "basic": read(CONTENT_FILES["basic"]),
        "bush": read(CONTENT_FILES["bush"]),
        "lines": lines,
        "floor": next(r["text_en"] for r in lines if r["id"] == FLOOR_ID),
        "src": {k: v for k, v in read("citations.json").items() if not k.startswith("_")},
    }


def _nth(items, tok):
    """items[n-1] for a decimal token in range, else None."""
    return items[int(tok) - 1] if NUM.fullmatch(tok) and 0 < int(tok) <= len(items) else None


def _withheld(items):
    return [w.get("text_en") or f"Withheld: {w['reason_id']} (see ERP LINES)" for w in items]


def _steps(label, actions):
    return [f"{label}{i}. {a['text_en']}" for i, a in enumerate(actions, 1)]


def reply(pack, command):
    """The whole node. Case-insensitive, whitespace tolerant, nothing else parsed."""
    t = command.split()
    basic, bush = pack["basic"], pack["bush"]
    head, rest = (t[1].upper() if len(t) > 1 else ""), t[2:]
    if not t or t[0].upper() != "ERP" or len(rest) > 1:
        pass
    elif not head:
        return "\n".join([
            "ArrowMem ERP: survival steps from published sources, exact text, no model. Commands:",
            f"ERP BASIC - {basic['title_en']}",
            f"ERP BUSH - {bush['title_en']}",
            f"ERP BASIC 1-{len(basic['actions'])} - one step. ERP BUSH 1-{len(bush['sections'])}"
            " - one section. ERP BUSH 1.1 - one step",
            "ERP LINES - what this node will not answer",
            "ERP SRC <source id> - the citation for a step"])
    elif head == "LINES" and not rest:
        return "\n".join(f"{r['id']}: {r['text_en']}" for r in pack["lines"])
    elif head == "SRC" and rest and rest[0].lower() in pack["src"]:
        return f"{rest[0].lower()}: {pack['src'][rest[0].lower()]}"
    elif head == "BASIC" and not rest:
        return "\n".join([f"BASIC: {basic['title_en']}", basic["who_this_is_for_en"]]
                         + _steps("", basic["actions"]) + _withheld(basic["withheld_from_this_scenario"]))
    elif head == "BASIC" and (a := _nth(basic["actions"], rest[0])):
        return f"{int(rest[0])}. {a['text_en']}\nSRC {a['source_id']}"
    elif head == "BUSH" and not rest:
        return "\n".join([f"BUSH: {bush['title_en']}", bush["who_this_is_for_en"]]
                         + [f"{i}. {s['title_en']}" for i, s in enumerate(bush["sections"], 1)])
    elif head == "BUSH" and len(dot := rest[0].split(".")) <= 2 and (s := _nth(bush["sections"], dot[0])):
        n = int(dot[0])
        if len(dot) == 1:
            return "\n".join([f"BUSH {n}: {s['title_en']}"] + _steps(f"{n}.", s["actions"])
                             + _withheld(s.get("withheld", [])))
        if a := _nth(s["actions"], dot[1]):
            return f"{n}.{int(dot[1])}. {a['text_en']}\nSRC {a['source_id']}"
    return UNKNOWN + "\n" + pack["floor"]


def chunk(text, max_chars):
    """Parts of text, each at most max_chars including its "[k/K] " prefix, so that the parts
    minus prefixes concatenate back to text exactly. A cut lands after the last newline that
    fits, else after the last space, else hard. Nothing is dropped, nothing is reworded."""
    if not max_chars or len(text) <= max_chars:
        return [text]
    if max_chars < 16:
        raise ValueError("--max-chars must be 0 or at least 16")
    k = 1
    while True:  # the prefix width depends on the part count, so iterate until the width holds
        budget = max_chars - len(f"[{k}/{k}] ")
        parts, rest = [], text
        while len(rest) > budget:
            cut = rest.rfind("\n", 0, budget)
            if cut < 0: cut = rest.rfind(" ", 0, budget)
            if cut < 0: cut = budget - 1
            parts.append(rest[:cut + 1])
            rest = rest[cut + 1:]
        if rest: parts.append(rest)
        if len(str(len(parts))) <= len(str(k)): break
        k = len(parts)
    return [f"[{i}/{len(parts)}] {p}" for i, p in enumerate(parts, 1)]


def sealer(keyfile):
    """--sign: each outgoing chunk becomes an arrowenvelope (Ed25519 over the chunk)."""
    # ponytail: sibling checkout lookup until arrowenvelope is on PyPI; PYTHONPATH also works.
    sys.path.append(str(Path(__file__).resolve().parent.parent / "arrowmem-envelope"))
    import arrowenvelope as ae
    key = ae.load_key(keyfile)
    return lambda part: ae.seal(key, part.encode("utf-8"))


def serve_stdin(pack, max_chars, seal):
    """One command per line in; the reply's chunks, one blank line after each reply, out.
    With --sign each chunk is one line of hex (a sealed chunk is binary and may contain 0x0A)."""
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        for part in chunk(reply(pack, line), max_chars):
            sys.stdout.write(seal(part).hex() + "\n" if seal else part + ("" if part.endswith("\n") else "\n"))
        sys.stdout.write("\n")
        sys.stdout.flush()


def serve_lxmf(pack, max_chars, seal, configdir):
    """Announce an LXMF destination "ArrowMem ERP"; answer every inbound message's content
    through reply(), one LXMF message per chunk, back to the sender."""
    import LXMF
    import RNS
    RNS.Reticulum(configdir=configdir)
    store = Path(RNS.Reticulum.storagepath) / "erp_node"
    store.mkdir(parents=True, exist_ok=True)
    idfile = store / "identity"  # the node's address survives restarts
    identity = RNS.Identity.from_file(str(idfile)) if idfile.exists() else RNS.Identity()
    if not idfile.exists():
        identity.to_file(str(idfile))
    router = LXMF.LXMRouter(identity=identity, storagepath=str(store))
    me = router.register_delivery_identity(identity, display_name="ArrowMem ERP")

    def answer(msg):
        dest = msg.source  # set by LXMF when the sender has announced; else ask the network
        if dest is None:
            RNS.Transport.request_path(msg.source_hash)
            for _ in range(60):
                time.sleep(2)
                if ident := RNS.Identity.recall(msg.source_hash):
                    dest = RNS.Destination(ident, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
                    break
            else:
                return RNS.log("ERP: no path back to " + RNS.prettyhexrep(msg.source_hash), RNS.LOG_WARNING)
        for part in chunk(reply(pack, msg.content_as_string() or ""), max_chars):
            router.handle_outbound(LXMF.LXMessage(dest, me, seal(part) if seal else part))

    router.register_delivery_callback(lambda m: threading.Thread(target=answer, args=(m,), daemon=True).start())
    print("ArrowMem ERP LXMF address: " + RNS.hexrep(me.hash, delimit=False), file=sys.stderr, flush=True)
    while True:
        router.announce(me.hash)
        time.sleep(1800)  # ponytail: fixed re-announce; make it a flag if an HF operator needs it slower


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pack", default=str(Path(__file__).parent / "pack"), help="pack directory (default: ./pack)")
    p.add_argument("--max-chars", type=int, default=0, help="chunk replies to at most N chars each (0 = off)")
    p.add_argument("--sign", metavar="KEYFILE", help="seal each chunk with an arrowenvelope key (off by default)")
    p.add_argument("--lxmf", action="store_true", help="serve over LXMF instead of stdin/stdout")
    p.add_argument("--config", help="Reticulum config directory for --lxmf (default: Reticulum's own)")
    a = p.parse_args(argv)
    pack, seal = load_pack(a.pack), sealer(a.sign) if a.sign else None
    if a.lxmf:
        serve_lxmf(pack, a.max_chars, seal, a.config)
    else:
        serve_stdin(pack, a.max_chars, seal)


if __name__ == "__main__":
    main()
