# arrowbridge-erp-node

A survival-content node for radio and mesh networks. It answers a closed set of commands with
the exact text of the ArrowMem emergency response pack: what to do when stranded in a vehicle,
and what to do when lost on foot, every line traced to a published source. It runs on Reticulum
(LXMF) or behind any transport at all through stdin/stdout, with no model, no internet, and no
signal.

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

`ERP` is the command word, short for emergency response. `BASIC` is the stranded-in-a-vehicle
tier and `BUSH` is the lost-on-foot tier. Type all three exactly as they appear below: they are
literal commands sent over a radio link, not words the node interprets, so they are never
translated and never spelled any other way.

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

    python3 erp_node.py --pack pack

One command per line in. Out: the reply's chunks, each on its own line (a chunk that spans
several lines keeps them), then one blank line. Replies never contain a blank line, so the
blank line is an unambiguous terminator. Empty input lines are ignored.

**LXMF.** Announces a delivery destination named `ArrowMem ERP` and answers every inbound
message by running its content through the same handler, one LXMF message per chunk, back to
the sender.

    pip install rns lxmf
    python3 erp_node.py --pack pack --lxmf [--config <reticulum config dir>]

The node's address is printed to stderr at start and is kept under Reticulum's storage
directory, so it survives restarts. It re-announces every 30 minutes. A sender the node has
never heard announce gets a path request and up to two minutes of patience before the reply is
dropped with a log line.

The sibling `arrowmem-envelope` checkout (see "Faster frames" below) is needed only for
compressed replies, same as before: a plain-only `--lxmf` node still needs only `pip install
rns lxmf`. If that checkout is missing, `--lxmf` logs one line at start (`arrowcontent not
found: 0x05 announces will be recorded but answered in plain text`) and runs plain-only for
the whole session; a 0x05 HOLDS frame that arrives after that is logged as ignored, never a
traceback.

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
| `ERP BASIC` | 1600 | 12 | 18 | about 4.3 min |
| `ERP BUSH` | 277 | 2 | 3 | about 44 s |
| `ERP BUSH 2` (the longest section) | 1117 | 8 | 13 | about 3 min |
| `ERP LINES` | 2913 | 19 | 30 | about 7.8 min |
| one step | 107 to 423 | 1 to 3 | 2 to 4 | 17 s to 68 s |
| unknown command | 167 | 1 | 3 | about 27 s |

Air time is characters times 0.16 s, before their LDPC block rounding and frame overhead.
`--max-chars 200` fits their unsealed PAYLOAD; `--max-chars 127` leaves room for the 73-byte
envelope header when signing.

## Faster frames (optional, off by default)

`--content {plain,ref,dict}` (default `plain`) rides arrowcontent's wire format
(`arrowmem-envelope/SPEC-CONTENT.md`) as the frame's payload: `ref` sends one 41-byte 0x03
content reference per reply, `dict` sends one 0x04 dictionary-compressed frame per chunk. The
dictionary (`pack.dict`, id `5ffbd490ada4f969`) is built from this node's own pack in the
pinned order SPEC-CONTENT.md names, and ships committed in this repository (`build_dict.py`
rebuilds it; `python3 -m unittest -v` checks the committed file matches a fresh build). Both
modes need `pip install cryptography` for nothing extra; they only need the sibling
`arrowmem-envelope` checkout (or `PYTHONPATH`), same as `--sign`.

**Fallback rule: plain is the default and stays the default for any peer that has not said it
holds the pack.** For stdin/stdout, `--content ref`/`--content dict` are explicit opt-in flags a
node operator sets only when the peer is known to run the identical pack (this node's own case
today, per SPEC-CONTENT.md's own reading: "the request already is the reference case"). A peer
that does not speak these frames simply never gets one, because plain stays the default.

**`--lxmf` wires the 0x05 HOLDS advertise-before-compress frame.** Send the node this 9-byte
frame, hex `055ffbd490ada4f969` (our pinned dictionary id, `0x05` prefix), from any LXMF
message and the node records your source hash in memory; every later reply to you is then
`dict` mode (one or more 0x04 frames), regardless of the `--content` flag the node was
started with. A HOLDS frame gets no reply of its own, ack or otherwise. Anyone who has not
sent one keeps getting whatever `--content` says (plain by default), exactly as before. This
is unauthenticated: `--sign` seals only this node's outbound chunks, it never opens an
inbound envelope, so a bare 0x05 is accepted on its face whether or not `--sign` is on. A
forged announce changes only the encoding a peer is answered in, never the content: at worst
it makes a peer receive 0x04 frames it cannot decode (its own decoder reports `unknown
dictionary`, or the bytes are simply unparseable if it runs no arrowcontent decoder at all).
There is no un-announce frame; a mis-recorded peer clears only on node restart (in-memory
table, not persisted). The node never sends its own 0x05: it is the content server, never a
content requester, so it never needs to announce.

**Who has to hold what.** `ref` mode: both ends need byte-identical `pack/` content (same
`pack/SOURCE.md` commit) and each builds its own index from it; a reply this node can emit but
the receiver's pack predates is `reference not held`, never a guess. `dict` mode: both ends
need the identical `pack.dict` bytes (checked by id); a receiver on an older or newer pack
gets `unknown dictionary`.

    python3 erp_node.py --pack pack --content ref
    python3 erp_node.py --pack pack --content dict --max-chars 127
    python3 erp_node.py --pack pack --decode

`ref`/`dict` here (the explicit `--content` flag) are stdin/stdout only; see above for how
`--lxmf` uses the 0x05 HOLDS frame instead of this flag to decide dict mode per peer. Each
line of stdin/stdout output is one content frame,
hex-encoded (always, signed or not, since a frame is binary); `--sign` seals the frame itself,
so the content frame becomes the envelope payload. `--decode` reads hex frames back and prints
either the decoded text or one of SPEC-CONTENT.md's named errors (`not a compressed frame`,
`unknown dictionary`, `bad inflate`, `too long`, `reference not held`), non-zero exit on error.

### Measurement

    python3 measure.py

Reproducible over the full closed grammar (39 replies, 16,059 raw bytes). Both of
SPEC-CONTENT.md's honest cases are printed, never a single ratio: (a) the dictionary excludes
the reply's own source content file, the novel-reply case; (b) the full shipping dictionary,
reply's own source included, the reference case (this node answering from its own pack, to a
second node running the same pack).

    reply                  raw  f@200  f@127  ref  dict(a)  dict(b)
    ---------------------------------------------------------------
    ERP                    378      3      5    1      155      155
    ERP BASIC             1600     12     18    1      652      109
    ERP BUSH               277      2      3    1      155       74
    ERP LINES             2913     19     30    1      122      122
    ...
    ---------------------------------------------------------------
    TOTAL                16059    116    178   39     5513     1397

    case (a), dictionary excludes the reply's own source file: 16059 raw -> 5513 bytes, 2.913x
    case (b), reference case, full shipping dictionary: 16059 raw -> 1397 bytes, 11.495x
    ref mode (0x03): 39 frames total, 41 bytes each, regardless of reply length (this node
    already holds every reply it can emit)

Case (a) here excludes a reply's own tier content file (`basic_vehicle.json` or
`bush_lost.json`) where one applies, and is otherwise the full dictionary; it is an
approximation of SPEC-CONTENT.md's own per-reply exclusion, and the two numbers are not
expected to match exactly. Case (b) matches SPEC-CONTENT.md's own pinned-order measurement
exactly (1,397 bytes, 11.495x). Never quote either as a single figure without its label.

### Legal reading

A published algorithm (RFC 1951) against a published, content-addressed dictionary obscures
nothing; see `arrowmem-envelope/SPEC-CONTENT.md` "Legal reading" for the full statutory text
this reasoning rests on.

## Privacy on an open leg (optional, off by default)

`--pad N` fixes every emitted frame or plain chunk to exactly N bytes with a trailing pad
(zero bytes for a binary frame, spaces for the unsealed plain-text fallback), so a listener
sees the same size every time regardless of what a reply actually contains. This removes the
message-length signal, the cheapest traffic-analysis input there is, and it obscures no
meaning: the content is exactly what it was, just measured out to a fixed size. What it
costs is the air time compression saves: at `--pad 200` every frame is 200 bytes, about 32
seconds at 0.16 s per byte, against the measured sizes in the table above, where the whole
point of `--content dict` was to make most replies far smaller than that. Padding and
dictionary compression pull in opposite directions on the same byte; how much of the
compression saving to spend back on flattening the length signal is a per-link operator
choice, not one this code makes for you. N must be at least `--max-chars`, checked at
startup, and a frame that would exceed N is a hard error, never a silent truncation.

`--every S` queues each reply as it finishes and writes it only at the next tick of a fixed
cadence that starts when the process starts, instead of the moment it is ready. This breaks
the timing correlation between when a question went out and when an answer came back: a
listener sees transmissions on a schedule, not on demand. A tick with nothing queued writes
nothing: this node never fills a silent tick with a contentless frame just to keep the
cadence looking busy, because that is its own question under FCC 97.113(b) (station
identification on an emission with no content) that this change does not open.

Neither of these hides who is transmitting or what a decoded frame says once someone has the
right dictionary or corpus. What a listener still learns, even with both on: that a station
identified by its call sign, which the law requires and no setting here can hide, transmitted
a fixed-size frame at a scheduled time. The one thing that stays hidden for free is who the
frame is for: a destination is a hash (Reticulum's own property, not this code's), so nothing
on the air names a recipient. See `SIGNED_BEACON_PRIVACY_LAYERS_2026-09-20.md` for the full
layer stack and the legal reasoning behind treating this as a beacon rather than a channel to
secure.

    python3 erp_node.py --pack pack --content ref --max-chars 127 --pad 200
    python3 erp_node.py --pack pack --every 5

## Signing (optional, off by default)

    PYTHONPATH=../arrowmem-envelope python3 -m arrowenvelope keygen node.key
    python3 erp_node.py --pack pack --sign node.key --max-chars 127

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

    python3 -m unittest -v

Every grammar branch, case and whitespace tolerance, out-of-range and unknown input, the
content boundary above, chunk reassembly identity at several budgets, the stdin transport via
subprocess, signing when arrowenvelope is importable, an LXMF loopback between two processes
on one shared Reticulum instance when `rns` and `lxmf` are installed (plus a second loopback,
also gated on arrowcontent being importable, that sends a 0x05 HOLDS frame first and asserts
the next reply is a 0x04 dictionary-compressed frame decoding back to the exact text), the
per-peer mode choice (`record_holds`/`lxmf_mode`) unit-tested with no Reticulum instance at
all, the `pack.dict` id and that it matches a fresh build, and (when arrowcontent is
importable) `ref`/`dict` round trips over every grammar reply plus every named decoder error.

## Licence

The code in this repository is MIT, ArrowMem Inc. 2026; see `LICENSE`.

### Content licence

The pack content (`pack/content/`, `pack/safety/`, `pack/citations.json`) is licensed
separately from the code, under CC BY 4.0; see `pack/LICENSE-CONTENT`. `pack/NOTICE.md` names
every source body this content draws on and states that none of them endorses or is
affiliated with this pack or with ArrowMem.

## About

ArrowMem (arrowmem.ca) is a private assistant that runs on your own hardware. This node is its
survival layer: the part that has to work when nothing else does.

If you run this on a box that is always on and want to know what else that box is exposing,
ArrowMem Guard (arrowmem.ca/guard.html) is the same team's machine sweep. It is separate from
this node and optional.

This node is standalone software and it is the only place this content is answered today. The
ArrowMem assistant does not yet provide guided emergency support, and nothing here should be
read as saying it does.

## Credits

Built by ArrowMem Inc. with Claude (Anthropic) as the coding collaborator. Reviewed adversarially by a
separate model session that did not write it, and verified on a second machine, a different operating
system, that did not build it: the full suite, the closed command grammar driven by hand, and the radio
transport exercised for real. The content is restated in our own words from the sources named in
pack/NOTICE.md. Issues and pull requests welcome.
