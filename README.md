# arrowbridge-erp-node

A survival-content node for radio and mesh networks. It answers a closed set of commands with
the exact text of the ArrowMem ERP pack: what to do when stranded in a vehicle, and what to do
when lost on foot, every line traced to a published source. It runs on Reticulum (LXMF) or
behind any transport at all through stdin/stdout, with no model, no internet, and no signal.

Built for the community that bridged Reticulum over amateur HF
(github.com/buildwithparallel/crosstalk): their frames are plaintext and slow, so every reply
here is plaintext-safe and can be chunked to a frame budget.

## What it is not

- **Not first aid, not triage.** The pack has no injury, medical or mental-health content, on
  purpose; `ERP LINES` prints the eleven things it refuses to answer and why.
- **Not a model.** Nothing is generated, summarised, paraphrased or shortened. A command maps to
  a string in `pack/`, byte for byte, or to the one navigation reply below. Free text is never
  interpreted.
- **Not private on an open radio leg.** The crosstalk HF leg carries plaintext by their design,
  readable by anyone with a receiver. This content contains no personal information and takes
  no reader input, which is why it can go over that leg at all. Do not put anything else
  through the same pipe and call it private.
- **Not a route, a wait time, an alert feed or a shelter finder.** Those need a network. This
  is the zero-signal half only.

## Commands

Case-insensitive, whitespace tolerant, nothing else parsed.

| Send | Get |
| --- | --- |
| `ERP` | the menu: both tiers, each labelled with the pack's own title, and the command list |
| `ERP BASIC` | the BASIC tier (stranded in a vehicle): title, who it is for, every step numbered, and what the pack withholds |
| `ERP BASIC <n>` | step n, full text, then `SRC <source id>` |
| `ERP BUSH` | the BUSH tier (lost on foot): title, who it is for, its numbered section titles |
| `ERP BUSH <n>` | section n: title, every step in it numbered `n.m`, and what the pack withholds |
| `ERP BUSH <n>.<m>` | step m of section n, full text, then `SRC <source id>` |
| `ERP LINES` | the eleven hard-line refusals, `id: text`, so a reader knows what this node will not answer |
| `ERP SRC <source id>` | the citation line for that source id, as the pack records it |
| anything else | `Unknown command. Send ERP for the menu.` followed by the pack's own first-aid refusal line, which ends in call 911 |

Why the grammar has this shape: the pack's BASIC tier is a flat list of seven steps with no
step titles, so its index is the steps themselves. The BUSH tier has eight titled sections
(stay put first, on purpose), so `ERP BUSH` lists sections and `n.m` reaches a step. Out of
range numbers, `ERP BASIC 1.1`, extra words, and unknown source ids all get the unknown reply.
A step's `note_en` field (a maintainer note) is never emitted. Withheld items are named in the
tier and section replies as `Withheld: <id> (see ERP LINES)`, or in the pack's own words when
it wrote some, so a gap is a decision on record rather than a silent absence.

## Transports

**stdin/stdout, the universal adapter.** Any bridge, codec or radio can pipe into it.

    python erp_node.py --pack pack

One command per line in. Out: the reply's chunks, each on its own line (a chunk that spans
several lines keeps them), then one blank line. Replies never contain a blank line, so the
blank line is an unambiguous terminator. Empty input lines are ignored.

**LXMF.** Announces a delivery destination named `ArrowMem ERP` and answers every inbound
message by running its content through the same handler, one LXMF message per chunk, back to
the sender.

    pip install rns lxmf
    python erp_node.py --pack pack --lxmf [--config <reticulum config dir>]

The node's address is printed to stderr at start and is kept under Reticulum's storage
directory, so it survives restarts. It re-announces every 30 minutes. A sender the node has
never heard announce gets a path request and up to two minutes of patience before the reply is
dropped with a log line.

## Chunking and the radio budget

`--max-chars N` (default 0, no chunking) splits a reply into parts of at most N characters
each, prefixed `[k/K] `. A cut lands after the last line break that fits; if a single line is
longer than the budget, after the last space; only if a run has no space at all, mid-word. The
parts minus their prefixes concatenate back to the reply exactly; nothing is dropped or
reworded, ever. A reader who missed part 4 of `ERP BASIC` can ask for `ERP BASIC 4` alone.

Their numbers, not ours, retyped from the crosstalk codec document via arrowenvelope's
`SPEC.md`: inner-frame PAYLOAD up to 200 bytes, LDPC rate 1/2 at 100 baud, so 0.16 s per
payload byte, and about 7 seconds per short frame. We have measured none of this on air.
Measured here, on this pack, the reply sizes are:

| Reply | Characters | Frames at 200 | Frames at 127 (sealed) | Air time at 0.16 s per byte |
| --- | --- | --- | --- | --- |
| `ERP` | 378 | 3 | 5 | about 60 s |
| `ERP BASIC` | 1644 | 12 | 19 | about 4.4 min |
| `ERP BUSH` | 277 | 2 | 3 | about 44 s |
| `ERP BUSH 2` (the longest section) | 1117 | 8 | 13 | about 3 min |
| `ERP LINES` | 2926 | 19 | 30 | about 7.8 min |
| one step | 107 to 423 | 1 to 3 | 2 to 4 | 17 s to 68 s |
| unknown command | 167 | 1 | 3 | about 27 s |

Air time is characters times 0.16 s, before their LDPC block rounding and frame overhead.
`--max-chars 200` fits their unsealed PAYLOAD; `--max-chars 127` leaves room for the 73-byte
envelope header when signing.

## Signing (optional, off by default)

    python -m arrowenvelope keygen node.key
    python erp_node.py --pack pack --sign node.key --max-chars 127

Each outgoing chunk, prefix included, is sealed with arrowenvelope (Ed25519 over a content
hash, 73-byte header). A receiver holding the node's public key can reject anything not sent
by it, offline, with no clock. It authenticates; it does not encrypt. On stdin/stdout a sealed
chunk is written as one line of hex, because the raw envelope is binary and may contain a line
break; that hex is a local pipe format for a bridge to unpack, not air-ready text. Over LXMF the
raw envelope bytes are the message content. `arrowenvelope.py` is not on PyPI yet: the node
looks for a sibling checkout named `arrowmem-envelope`, or put it on `PYTHONPATH`, and
`pip install cryptography`.

## Where the content comes from

Everything under `pack/` is the ArrowMem ERP pack, copied byte for byte from its own
repository; `pack/SOURCE.md` names the files and the version. The node reads it and cannot
change it: `test_erp_node.py` walks every command the node accepts and asserts that every
non-navigation line it emits is a verbatim string from a pack file. Corrections, new steps,
translations and changed refusals happen in the pack repository, never here.

## Tests

    python -m unittest -v

Every grammar branch, case and whitespace tolerance, out-of-range and unknown input, the
content boundary above, chunk reassembly identity at several budgets, the stdin transport via
subprocess, signing when arrowenvelope is importable, and an LXMF loopback between two
processes on one shared Reticulum instance when `rns` and `lxmf` are installed.

## Licence

The code in this repository is MIT, ArrowMem Inc. 2026; see `LICENSE`.

### Content licence

The pack content under `pack/` is licensed separately. Its licence is stated in
`pack/SOURCE.md`.

## About

ArrowMem (arrowmem.ca) is a private assistant that runs on your own hardware. This node is its
free survival layer: the part that has to work when nothing else does.
