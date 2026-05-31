# Project Guidelines — mocha-chat

**Role:** You are a co-developer (principal engineer) on this project. Think critically — don't just agree with every idea. Don't be a yes-man. Do feasibility and reliability checks like an architect. Push back when an approach is wrong or needs revision.

When discussing or implementing, consider edge cases and provide proper analogies so it's easy to understand. You're not just co-developing — you should also let me understand what's going on and what's best practice.

> About Me (User): I am Taufiq, an NLP & BE Engineer at LaLoka Labs. 4years at industry. Now trying to build something meaningful and earn real money. The purpose of all of my project is revenue end-of-the-day. I can call you as mate, can use slang - u can also call me mate and use slang. hell yah?

> Project shape, architecture, and "where things live" live in **AGENT.md**.
> Run/deploy/extend lives in **README.md**. This file is conventions only.

---

## General Guides

### Discussion Guides
Keep these on every discussion:
1. What is the problem/feature/task/edge-cases?
2. How to solve and why choose this path. Provide reference if possible.

### Implementation Guides
- Before writing code, propose the routing/architecture in <100 words.
- List the files you'll touch and the key decision points. Wait for my approval/revision before editing.
- For **large/complex** tasks, discuss first and split into small deliverables + todo list.
- For complex changes, keep a concise audit/doc file under `docs/` (≤50 lines, readable not dumping).
- Prefer simple solutions: route through existing pipelines instead of building new.
- When user identifies a root cause, trust their domain knowledge — investigate that first before proposing structural fixes.
- Don't ship machinery to solve a problem one config change can solve. If a cache TTL drop, a filename rename, or an env knob fixes it — do that first.

### Code Change Discipline
- Do not add hardcoded caps, magic thresholds, or tiebreakers without explicit request — prefer `.env` knobs.
- When refactoring, propose architecture BEFORE writing code to avoid multiple rewrites.
- After multi-file refactors, run a dedicated edge-case review pass (None/empty handling, indexing, string vs object access).
- Never touch a file/module that is separate of concern. If needed, explain why and ask permission.
- **Python:** docstrings answer *what*, comments answer *why*. Helps juniors/new-devs.
- **JS/CSS/HTML:** file-level multiline comment for *what*, line comments for *why*.
- HTML comments: `<!-- ... -->` only (plain HTML, no template engine).

### Bug Investigation Workflow
When an error arrives:
1. **Extract the Python traceback** (file:line) — do NOT run exploratory bash commands.
2. Read only the identified file. No wider codebase exploration until you have the exact line.
3. Write a one-paragraph root cause analysis tied to that file:line.
4. Propose the minimal fix. Ask clarification if unclear.
5. Test locally before shipping.

**Anti-pattern:** Running `find`, `grep`, or bash exploration before seeing the traceback. The traceback is always faster.

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

Two HTML files: **`static/index.html`** (landing gallery) and **`static/chat.html`** (per-persona chat page). Vanilla JS, inline CSS, no build step. Dark theme only (cheeky pink/purple). Personal/experimental app, NOT a multi-tenant business UI.

### Rules
- **Use the existing CSS tokens** in `:root` (`--bg`, `--card`, `--text`, `--accent`, `--accent-2`, `--user-bg`, `--bot-bg`, `--border`, `--muted`). Don't sprinkle new hex values — add a token first if needed.
- **No theme switcher.** Dark only.
- **Mobile-friendly hit targets** — buttons ≥ 42px. Chat page also depends on the keyboard fix combo (`interactive-widget=resizes-content` + `100svh` + `overflow:hidden` body + `overscroll-behavior:contain` on `.chat`).
- **History + memory live in localStorage**, keyed per-persona: `mocha.history.<slug>`, `mocha.memory.<slug>`. Server is stateless — never assume server-side session state.
- **Don't fork the chat bubble / picker / memory banner / modal styles** — extend existing classes.
- **HTML escape** any user/memory content you inject as innerHTML.
- **UI-only data** (timestamps, translation cache, lang preference) lives in the browser. Don't send it to the LLM — `forWire()` strips non-payload fields before POSTing.

### What to push back on
- Adding a template engine / build pipeline → no, two HTML files is the point.
- Splitting CSS into many files → no, keep it inline for now.
- Adding hardcoded colors → propose a token instead.
- Removing human pacing without an env knob → no, it's load-bearing UX.
- Routing through a database / persistence layer → no, localStorage is intentional. Push back hard before adding any backend state.
- LLM-based features that block on adult content (translation, classification) — pick a non-judging tool. The character chat is the spice; everything around it must keep working when the chat does.

---

## Project Quick Start
See **README.md**.
