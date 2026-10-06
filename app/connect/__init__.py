"""Surasura Connect (3.0's Pipeline track; core code since 🧭 Q4-2): Surasura's words made into cards by Anki Miner.

P1.3 builds the mine path, which nothing runs by itself yet (Connect's runner is P2.4):

- `pick`       — which words of one subtitle become cards, and the line each is cut from (`surasura-cli pick`)
- `runfile`    — the run file Anki Miner's `--api mine` reads, written strict UTF-8 (K61)
- `anki_miner` — the caller: finding Anki Miner, its `--api` verbs, a `mine` call and its results
- `fields`     — the deck, note type and fields Anki Miner fills, from its own settings export

Nothing here is imported unless a command-line verb needs it: with the preview off, every output is 2.5's.
"""
