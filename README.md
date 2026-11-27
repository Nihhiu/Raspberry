<h1 align="center">Raspberry</h1>

<p align="center"><strong>An AI composition agent for <a href="https://github.com/Ka1-S/LYNX-SHARE">LYNX SHARE</a>.</strong><br>
It observes your project, analyzes the music, and proposes MIDI edits — nothing is written until <em>you</em> approve it.<br>
Named for something in the FL Studio theme: something red, like the LYNX.</p>

<p align="center">
  <a href="#what-is-raspberry"><strong>About</strong></a> ·
  <a href="#how-it-works"><strong>How it works</strong></a> ·
  <a href="#getting-started"><strong>Getting started</strong></a> ·
  <a href="#usage">Usage</a> ·
  <a href="#safety">Safety</a> ·
  <a href="#project-structure">Structure</a> ·
  <a href="#status">Status</a> ·
  <a href="#license">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-90%20passing-5cb85c" alt="90 tests passing">
  <img src="https://img.shields.io/badge/Windows-10%20%C2%B7%2011-24292f" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/status-beta-f0ad4e" alt="Beta">
  <img src="https://img.shields.io/badge/license-GPLv3-5cb85c" alt="GPLv3 license">
</p>

---

## What is Raspberry?

Raspberry is an AI agent that composes MIDI inside [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE), a free and
open-source DAW with the FL Studio workflow. It runs beside the DAW, reads the open project over LYNX's Remote
Control API, and works in a strict rhythm: **observe → analyze → propose → ask → apply**.

It is for you if you…

- make music in LYNX SHARE and want an AI collaborator that works directly on the project, not on exported MIDI files;
- want every write gated by an explicit human approval, with native undo as the safety net;
- want the agent to respect your music: it reads the motif, harmony and groove before proposing anything, and preserves
  every note attribute it does not touch.

The agent layer is pure Python with no runtime dependencies. The transport is
[lynx-mcp](https://github.com/ITAgnesmeyer/lynx-mcp), reused unmodified, which speaks the `lynx-control/1` protocol to
the DAW over a local TCP loopback connection.

Raspberry is not tied to one AI client. It works with any MCP-capable client (OpenCode, Claude Desktop, Codex, …) —
each brings its own orchestration on top of the same tools — and the Python package can also be driven directly from
your own scripts, with no AI client at all. The approval dialog, the proposal contract and the verification pipeline
are the same in every case.

## How it works

```
You (approval dialog) ── approve / refuse
        │
AI client (OpenCode, Claude Desktop, …) ── orchestrates
        │
        ▼
agent/lynx_agent (pure Python: analyze · propose · apply · verify)
        │
        ▼
   lynx-mcp (MCP transport, 26 lynx_* tools)
        │  TCP loopback · lynx-control/1 · HMAC auth
        ▼
   LYNX SHARE (native model · triple fence · native undo)
```

Every proposed edit is a signed document: it binds the session, project, expected revision and a SHA-256 content hash,
and expires by session, project, revision and time. Applying it requires a single-use approval token that is born only
from your click on **Approve** — the agent can present the dialog, but can never create, edit or delete a token.

## Getting started

### Prerequisites

- Windows 10/11 with [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE/releases) 0.1.31.1 (alpha) installed
- [Python 3.12+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/)
- An MCP-capable AI client to orchestrate the tools — for example [OpenCode](https://opencode.ai), which picks up
  `opencode.json` in this folder automatically. Not required: you can also drive the agent layer directly from Python.

### Setup

```bash
# 1. Clone
git clone https://github.com/Nihhiu/Raspberry.git
cd Raspberry

# 2. Get the MCP transport
git clone https://github.com/ITAgnesmeyer/lynx-mcp.git
uv sync --project lynx-mcp

# 3. Start LYNX with remote control enabled
uv run --project lynx-mcp python -m lynx_mcp.testhost start
```

### Run the tests

```bash
$env:PYTHONPATH = "agent"
python -m unittest discover agent/tests    # 90 tests
```

## Usage

### With an AI client

Open your MCP client in this folder and say what you want musically. For example:

> *"Add a break with the piano between bars 97 and 113, following the motif and chord progression of the song."*

The agent will:

1. **Read** the project (channels, patterns, notes) — read-only, always first.
2. **Analyze** it — density, extension, repetition, accents, key hypothesis, off-grid notes.
3. **Propose** a concrete edit — explicit notes, never intentions, with a human-readable diff.
4. **Ask** — a local approval dialog shows the diff; only your click creates the approval token.
5. **Apply and verify** — writes atomically through the triple fence, then re-reads the project to confirm the result
   note by note before claiming success.

### Without an AI client

The agent layer is a plain Python package — proposals, approval and application work the same way from a script:

```python
from lynx_agent.proposals import ProposalCache
from lynx_agent.approval import ApprovalGate
from lynx_agent.apply import check_prereqs, compute_new_notes, verify_applied

cache = ProposalCache(session_id="my-script")          # load a saved proposal
proposal = cache.load("prop-0123456789ab")
ApprovalGate(session_id="my-script").consume(proposal)  # your click, single use
notes = compute_new_notes(proposal, current_notes)      # then write via lynx-mcp
```

Every accepted batch is one native undo step: rollback is always one `history.undo` away.

## Safety

| Guarantee | How |
|---|---|
| Nothing without your click | Single-use approval token, born only from the local approval dialog. 5-minute expiry, bound to the proposal hash. |
| No stale writes | Triple fence (`projectId` + `epoch` + `revision`) enforced server-side; a proposal against an old revision is refused (`changed`). |
| All or nothing | Each batch is validated by a full round-trip through the native format before commit; a failed validation writes nothing. |
| Recording is sacred | Writes are refused by the DAW during recording or playback. |
| Never claim unverified success | The agent re-reads the project after every write and compares the actual notes. |
| `uncertain` is final | A write that answers `uncertain` may or may not have been applied — it is never retried automatically. |

## Project structure

```
agent/
  lynx_agent/            Pure-Python agent layer (no transport logic)
    analysis.py          Musical analyzer (density, repetition, key hypothesis)
    proposals.py         Proposal contract + session cache (SHA-256, TTL)
    approval.py          Human approval gate (dialog + single-use token)
    apply.py             Note validation, state computation, post-write verification
    transforms.py        Transpose, velocity, quantize, humanize, displace
    generation.py        Drum/bass groove templates and fills (seeded, reproducible)
  tests/                 90 unit tests
  examples/              End-to-end demo of the observe→propose cycle
skills/
  lynx-agent/SKILL.md    Agent choreography and inviolable rules
auditoria/               Audit report on the LYNX SHARE native model
docs/                    Utility documentation
plan.md                  Master plan (phases 0–2C)
token_budget.py          Context-budget utility
```

## Status

- **Phase 0 — Audit** ✔︎ Native model and remote-edit path of LYNX SHARE reviewed at source level; decision: reuse lynx-mcp, no C++ extension.
- **Phase 1 — Observe** ✔︎ Analysis and signed proposals; the project is never touched.
- **Phase 2A — Minimal write** ✔︎ Approval dialog, atomic apply, post-write verification, native undo/redo verified live.
- **Phase 2B — Transforms** ✔︎ Transpose, velocity, quantize, humanize (seeded), verified live.
- **Phase 2C — Generation** ✔︎ Groove templates and fills, verified live.
- **Real-world use** ✔︎ A 16-bar piano break (38 notes) composed from a song's motif and progression, applied and verified.

## License

Raspberry is licensed under the [GNU General Public License v3.0](LICENSE) — a copyleft license. Anyone who uses,
modifies or redistributes it (including building something better on top of it) must release that work under the same
license, so improvements stay free and open for everyone.

- [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE) by Ka1-S — the DAW, and the inspiration for the name (AGPL-3.0; Raspberry only talks to it over TCP).
- [lynx-mcp](https://github.com/ITAgnesmeyer/lynx-mcp) by ITAgnesmeyer — the MCP transport, reused unmodified (MIT).
