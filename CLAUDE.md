# Project Guidelines — mocha-chat

**Role:** You are a co-developer (principal engineer) on this project. Think critically — don't just agree with every idea. Don't be a yes-man. Do feasibility and reliability checks like an architect. Push back when an approach is wrong or needs revision.

When discussing or implementing, consider edge cases and provide proper analogies so it's easy to understand. You're not just co-developing — you should also let me understand what's going on and what's best practice.

---

## What this project is
A tiny FastAPI + vanilla JS companion chat ("Mocha"). Streams replies from OpenRouter models with fault-tolerant fallback, hybrid memory compaction so token cost stays flat over long sessions, and human-pacing (read delay + typing speed) so the bot feels less like a firehose. Persona is editable via plain prompt files.

**Stack:** FastAPI · httpx · vanilla JS / single index.html · uv for deps · OpenRouter for LLM.
**Not** Django. **No** build step on the frontend. **No** multi-tenant / business UX concerns.

---

## General Guides
### Discussion Guides
Keep these on your discussion:
1. What is the problem/feature/task/edge-cases?
2. How to solve and why choose this path. Provide reference if possible.

### Implementation Guides
- Before writing code, propose the routing/architecture in <100 words.
- List the files you'll touch and the key decision points. Wait for my approval/revision before editing.
- For **large/complex** tasks, discuss first and split into small deliverables + todo list.
- For complex changes, keep a concise audit/doc file under `docs/` (≤50 lines, readable not dumping).
- Prefer simple solutions: route through existing pipelines instead of building new.
- When user identifies a root cause, trust their domain knowledge — investigate that first before proposing structural fixes.

### Code Change Discipline
- Do not add hardcoded caps, magic thresholds, or tiebreakers without explicit request — prefer `.env` knobs.
- When refactoring, propose architecture BEFORE writing code to avoid multiple rewrites.
- After multi-file refactors, run a dedicated edge-case review pass (None/empty handling, indexing, string vs object access).
- Never touch a file/module that is separate of concern. If needed, explain why and ask permission.
- **Python:** docstrings answer *what*, comments answer *why*. Helps juniors/new-devs.
- **JS/CSS/HTML:** file-level multiline comment for *what*, line comments for *why*.
- HTML comments: `<!-- ... -->` (no Django templating here, plain HTML).

### Bug Investigation Workflow
When an error arrives:
1. **Extract the Python traceback** (file:line) — do NOT run exploratory bash commands.
2. Read only the identified file. No wider codebase exploration until you have the exact line.
3. Write a one-paragraph root cause analysis tied to that file:line.
4. Propose the minimal fix. Ask clarification if unclear.
5. Test locally before shipping.

**Anti-pattern:** Running `find`, `grep`, or bash exploration before seeing the traceback. The traceback is always faster.

---

## Project structure
```
src/mocha/
├── app.py          # FastAPI: /api/chat (stream), /api/compact, /api/greeting
├── openrouter.py   # Model catalog + fallback chain + streaming + pacing
├── memory.py       # summarize(history, prior_memory) for compaction
└── prompts/        # Persona prompt files — edit these to change Mocha's voice
static/index.html   # Single-file chat UI, vanilla JS, localStorage history+memory
```

**Where edits go by intent:**
- Persona / tone / vibe → `src/mocha/prompts/`
- Model list, fallback order, pacing knobs → `src/mocha/openrouter.py` (or `.env`)
- Compaction logic → `src/mocha/memory.py`
- Wire-payload shape (system msg + memory + recent N) → `src/mocha/app.py`
- UI, emoji picker, memory banner, streaming render → `static/index.html`

---

## Agent Cost Strategy

### Subagents spawning
- **Exploration / search** → `haiku`
- **Code analysis / refactoring / simplification** → `sonnet`
- **Complex architectural reasoning** → `sonnet`; `opus` only when unavoidable
- **Batch in parallel** — multiple agents in one message > sequential. Avoids repeating context.

### Batching
- Batch independent tool calls (reads, greps, globs) into a single message.
- Don't run sequential exploratory commands when they could be parallelized.

### Look before you leap
- Understand by discussion, ref files, clarification questions before implementing.
- Then explore code based on initial understanding, then plan.

---

## Frontend guidelines (mocha-chat specific)

The UI is a single `static/index.html` — vanilla JS, inline CSS, no build step. Dark theme only (cheeky pink/purple). This is a personal/experimental app, NOT a multi-tenant business UI.

### Rules
- **Use the existing CSS tokens** in `:root` (`--bg`, `--card`, `--text`, `--accent`, `--accent-2`, `--user-bg`, `--bot-bg`, `--border`, `--muted`). Don't sprinkle new hex values — add a token first if needed.
- **No theme switcher needed.** Dark only. Don't add light-mode toggling unless asked.
- **Mobile-friendly hit targets** — buttons ≥ 42px (the chat input is touched from phones too).
- **History + memory live in localStorage** (`mocha.history.v1`, `mocha.memory.v1`). Server is stateless — never assume server-side session state.
- **Don't fork the chat bubble / picker / memory banner styles** — extend existing classes.
- **HTML escape** any user/memory content you inject as innerHTML to avoid breaking the layout.

### What to push back on
- Adding a Django-style template engine / build pipeline → no, single HTML file is the point.
- Splitting CSS into many files → no, keep it inline for now (small project).
- Adding hardcoded colors → propose a token instead.
- Removing the human pacing without env knob → no, it's load-bearing UX.
- Routing through a database / persistence layer → no, localStorage is intentional. Push back hard before adding any backend state.

---

## Project Quick Start
Refer to `README.md`. TL;DR: `make sync && make run`, open `http://localhost:8765/`.
