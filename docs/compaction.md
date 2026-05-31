# Compaction

How `history` gets folded into `memory` so prompts don't grow unbounded.

## Mental model

1. **LLM always sees** `system prompt` + `memory` summary + last `KEEP_RECENT` history entries verbatim.
2. **`memory` grows** via `/api/compact`: client sends a chunk of older entries + the prior memory string → server's utility LLM folds them into an updated summary.
3. **`foldedUpTo`** (localStorage `mocha.foldedUpTo.<slug>`) tracks the `history` index already captured in `memory`. Compaction fires when enough unfolded entries pile up.

## Knobs (`src/mocha/settings.py`)

| name | default | meaning |
|---|---|---|
| `KEEP_RECENT` | 16 | recent entries the LLM sees verbatim per chat call |
| `COMPACT_INTERVAL` | 10 | entries folded into `memory` per `/api/compact` call |

**Invariant:** `COMPACT_INTERVAL ≤ KEEP_RECENT`. Otherwise unfolded entries can fall out of the live window before being summarized → LLM context gap.

Server inlines these as `window.MOCHA_CONFIG` into `/chat` HTML (mirrors landing's `window.MOCHA_PERSONAS`). Client reads, decides locally — zero extra round-trips.

## Trace (KEEP_RECENT=16, COMPACT_INTERVAL=10)

Columns:
- **`history.length`** — total entries in client history (1 user msg or 1 bot reply = 1 entry).
- **`foldedUpTo` (before/after)** — index in `history` already summarized into `memory`, read from / written to localStorage.
- **`unfolded`** = `length - foldedUpTo` — entries not yet in `memory`. The trigger.
- **fires?** — yes when `unfolded ≥ KEEP_RECENT`; the live window can no longer cover everything unfolded.
- **folds** — exactly `COMPACT_INTERVAL` entries, starting from `foldedUpTo`.
- **LLM sees** — what `/api/chat` actually sends to the model: `memory` summary + last `KEEP_RECENT` history entries.

| `history.length` | `foldedUpTo` (before) | `unfolded` | compact fires? | folds | `foldedUpTo` (after) | LLM sees |
|---|---|---|---|---|---|---|
| 10 | 0 | 10 | no (< 16) | — | 0 | memory="" + history[0..10) |
| 16 | 0 | 16 | **YES** | history[0..10) | 10 | memory(0-9) + history[0..16) |
| 24 | 10 | 14 | no (< 16) | — | 10 | memory(0-9) + history[8..24) |
| 26 | 10 | 16 | **YES** | history[10..20) | 20 | memory(0-19) + history[10..26) |
| 36 | 20 | 16 | **YES** | history[20..30) | 30 | memory(0-29) + history[20..36) |

60-turn chat: ~6 compact calls vs ~40 before. Each call folds a constant 10 entries.

## Why the memory ↔ live history overlap is intentional

Look at row 4: `memory` covers entries 0-19, but the LLM also sees entries `[10..26)` verbatim. Entries 10-19 are in **both**. That's by design — the freshly-folded chunk stays nearby in the live window so the model has a smooth "handover" from verbatim to summarized form (it sees the detail and the summary side by side until the verbatim copy naturally rolls out a few turns later). Without overlap (e.g. `COMPACT_INTERVAL == KEEP_RECENT`), an entry would jump straight from "verbatim" to "only in summary" in one turn, risking a noticeable context shift mid-conversation. Overlap size = `KEEP_RECENT - COMPACT_INTERVAL` (here: 6 entries).

## Files

- `src/mocha/settings.py` — env knobs
- `src/mocha/app.py` — `/chat` route inlines `MOCHA_CONFIG`
- `static/chat.html` — `maybeCompact()` and the "Compaction model" comment block
