"""Surasura Connect (3.0's Pipeline track; core code since 🧭 Q4-2): Surasura's words made into cards by Anki Miner.

P1.3 builds the mine path, which nothing runs by itself yet (Connect's runner is P2.4):

- `pick`       — which words of one subtitle become cards, and the line each is cut from (`surasura-cli pick`)
- `runfile`    — the run file Anki Miner's `--api mine` reads, written strict UTF-8 (K61)
- `anki_miner` — the caller: finding Anki Miner, its `--api` verbs, a `mine` call and its results
- `fields`     — the deck, note type and fields Anki Miner fills, from its own settings export

P2.1 puts Connect on the library store (the verbs `register`, `place`, `finish`, `connect --consume-only`:
`app/cli/connect_verbs.py`):

- `library`    — the thin adapter on `app/library_store.py`: Connect's reader and watermark, the top 20, placements by
                 a named source
- `inbox`      — the placement log read after the watermark into jobs (queued, dropped); a gap reconciles, never mines
- `ledger`     — `<local data>/connect/ledger.sqlite`: the jobs (work in flight, nothing lasting)
- `kick`       — Connect started on demand, one at a time, never while an update is staged
- `rules`      — New arrivals' placing rules (`placing_rules`, 3.0 only)
- `notice`     — the window's start-up line: what another program added while Surasura was closed

P2.4 builds the loop (`surasura-cli connect`):

- `runner`     — sync → known-sync → generate → pick → fit check → mine → backfill → junban → sync, every job in
                 top-20 order, each step saved; waits and resumes; exits when no job is left
- `fit_check`  — hato's `timed`, else tsubasa's `CONFIDENT` with one segment, else not mined
- `power`      — mains power only, below-normal priority

Nothing here is imported unless a command-line verb needs it, or the window with Connect's preview on: with the
preview off, every output is 2.5's.
"""
