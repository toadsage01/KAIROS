# myforge

A file-driven blackboard + DAG state machine for AI coding agents.
**Agents never talk to each other.** Each agent reads `state/*.md`, writes
`state/*.md`, and the orchestrator is a pure DAG executor — not a manager
that thinks.

## Why this design

| Problem with chat-based agents | myforge's answer |
|---|---|
| Token cost is unpredictable | Each agent = exactly 1 LLM call with bounded input |
| Hard to debug | State lives in markdown files — `cat state/plan.md` |
| Can't resume | `state/tasks.json` is a checkpoint; re-run picks up where it stopped |
| HITL is awkward | HITL = a pause in the DAG waiting for a JSON signal file |
| Free tier rate limits kill you | Fallback chains + deterministic mock provider |
| Coder sees whole repo | Retrieval returns top-k chunks + a ranked repo sub-map |

## Phase status (all 5 phases complete)

| Phase | Hours | Status | What it does |
|---|---|---|---|
| 1 — Skeleton | 0–4 | ✅ done | FastAPI + LiteLLM router + FileState + Streamlit + dummy E2E |
| 2 — Core agents + worktrees | 4–10 | ✅ done | 5 agents wired; git worktree per task; merge-on-approval |
| 3 — Memory + codemap | 10–16 | ✅ done | ChromaDB embedded + ctags/regex repo map + retriever feeding coder |
| 4 — Tools + researcher | 16–20 | ✅ done | Tavily search + trafilatura extract wired into researcher; MCP client |
| 5 — Polish + cron | 20–24 | ✅ done | APScheduler re-index cron + model fallback logging + /cron + /router_log |

## Quick start

```bash
cd myforge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env to add your API keys
./run.sh
# -> FastAPI on http://localhost:8000
# -> Streamlit UI on http://localhost:8501
```

**Dependency notes:**
- If `pip install` fails on `httpx` version conflict with `litellm`,
  pin `httpx==0.27.2` (already done in `requirements.txt`).
- `chromadb`, `apscheduler`, `trafilatura` are listed as required now.
  Without them the system still runs but degrades:
  - No chromadb → vector store unavailable, retrieval uses codemap only
  - No apscheduler → cron jobs no-op, `/cron` reports `available=false`
  - No trafilatura → researcher can't extract full page text (still gets Tavily snippets)
- Without any API keys, the LLM router falls back to a deterministic mock
  provider so you can exercise the DAG end-to-end. The smoke test detects
  this and runs in MOCK mode; with keys + litellm installed, it runs in LIVE mode.

## End-to-end smoke test

```bash
python scripts/smoke_test.py
```

Mode-aware: detects whether real LLM providers + API keys are available.
- **MOCK mode** (no keys): exercises the full DAG with deterministic mock
  outputs. Asserts the mock thinker's fixed plan shape.
- **LIVE mode** (keys + litellm): exercises the full DAG with real LLMs.
  Asserts only structural properties (plan parses, files land on disk,
  branches merge, logs written) — does not impose specific plan content,
  since real LLMs produce varied output.

Verifies all 5 phases in either mode:
- Phase 1: thinker -> HITL -> coder -> reviewer -> done (multi-task loop)
- Phase 2: files actually written to disk; git worktrees branch + merge
- Phase 3: codemap finds symbols; vector store indexes chunks (if available);
           retrieval returns bounded context to coder
- Phase 4: researcher runs only for needs_research=true tasks;
           web search results (if TAVILY_API_KEY set) injected into prompt
- Phase 5: router fallback log written; cron job registered (if apscheduler)

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + litellm availability |
| POST | `/run` | Start a run (with `{goal}`) or advance one step (no body) |
| GET | `/state` | Full state snapshot (goal, plan, tasks, changes, reviews, log) |
| POST | `/approve` | Resolve a HITL gate: `{gate, decision: "approved"\|"rejected", note}` |
| GET | `/logs?tail=N` | Orchestrator log tail |
| GET | `/router_log?tail=N` | **Phase 5** — model fallback audit trail |
| GET | `/cron` | **Phase 5** — scheduled jobs status |
| POST | `/reset` | Wipe all state (dev only) |

## Project layout

```
myforge/
├── core/
│   ├── orchestrator.py    # DAG executor (NOT an LLM agent)
│   ├── state.py           # FileState blackboard
│   ├── dag.py             # Task graph from workflow.yaml
│   ├── hitl.py            # Gate pause/resume via JSON signal
│   ├── parser.py          # Extract path= fenced blocks from coder output
│   ├── workspace.py       # Per-task git worktree lifecycle
│   └── cron.py            # APScheduler wrapper (Phase 5)
├── agents/
│   ├── base.py            # run(ctx) -> state file path
│   ├── thinker.py         # goal.md -> plan.md
│   ├── coder.py           # plan.md -> changes/{task}.md + real files in worktree
│   ├── reviewer.py        # changes + worktree files -> review/{task}.md
│   ├── bugfixer.py        # review + changes -> new changes (in worktree)
│   └── researcher.py      # web search + LLM synthesis -> research/{task}.md
├── llm/
│   ├── router.py          # LiteLLM wrapper + fallback chain + mock + fallback logging
│   └── prompts/*.j2       # Jinja2 system prompts per agent
├── memory/
│   ├── vectorstore.py     # ChromaDB embedded
│   ├── codemap.py         # ctags (preferred) + regex fallback + networkx graph
│   └── retriever.py       # Combines vector + codemap into bounded context
├── tools/
│   ├── web.py             # Tavily search + trafilatura extract
│   ├── mcp.py             # MCP client (official SDK, one-shot sessions)
│   └── gitops.py          # Git operations (worktrees, commit, merge)
├── api/main.py            # FastAPI: /run /state /approve /logs /router_log /cron /reset
├── ui/app.py              # Streamlit
├── config/
│   ├── agents.yaml        # role, model chain, prompt file, temp, max_tokens
│   └── workflow.yaml      # DAG definition + target_repo path
└── state/                 # runtime (git-versioned if you choose)
    ├── goal.md            # immutable north star
    ├── plan.md            # thinker output
    ├── tasks.json         # DAG position + task list (checkpoint)
    ├── research/{task}.md
    ├── changes/{task}.md
    ├── review/{task}.md
    └── hitl/{gate}.json
```

## Configuration

### agents.yaml

Each agent has a model fallback chain. Example:

```yaml
agents:
  coder:
    role: "Implement a single task. Output unified diff or new file content."
    model:
      primary: "ollama/qwen2.5-coder:32b"
      fallback: "deepseek/deepseek-chat"
      fallback_2: "openrouter/qwen/qwen-2.5-coder-32b-instruct:free"
    system_prompt_file: "llm/prompts/coder.j2"
    temperature: 0.1
    max_tokens: 4096
    allow_mock: true
```

If all three providers fail and `allow_mock: true`, the router returns a
deterministic mock so the DAG still runs. Every fallback is logged to
`logs/router.log` (visible at `/router_log`).

### workflow.yaml

Defines the DAG. HITL nodes pause; branch nodes route on review status.

```yaml
target_repo: "${MYFORGE_TARGET_REPO:./target_repo}"

dag:
  - id: thinker
    agent: thinker
    next: hitl_plan
  - id: hitl_plan
    type: hitl
    gate: plan_approval
    next: coder
  - id: coder
    agent: coder
    next: reviewer
  # ... reviewer -> review_check (branch) -> done or bugfixer

max_review_iterations: 3
```

### .env

| Var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini 2.0 Flash (thinker/reviewer/researcher) |
| `DEEPSEEK_API_KEY` | DeepSeek V3 / R1 (thinker/bugfixer) |
| `GROQ_API_KEY` | Llama 3.3 70B (researcher alt) |
| `OPENROUTER_API_KEY` | Qwen 2.5 Coder free tier (coder fallback) |
| `TAVILY_API_KEY` | Researcher web search (Phase 4) |
| `MYFORGE_TARGET_REPO` | Where agents write code (default `./target_repo`) |
| `MYFORGE_MCP_COMMAND` / `MYFORGE_MCP_ARGS` | MCP server (Phase 4) |

## How the coder writes files

The coder outputs markdown with fenced code blocks tagged with `path=`:

```python path=src/hello.py
def hello():
    return 'hello from myforge'
```

`core/parser.py` extracts these blocks. The orchestrator's
`core/workspace.py` writes them into a per-task git worktree at
`<target_repo>/.worktrees/<task_id>/` on a branch `myforge/<task_id>`.
On reviewer approval, the branch merges back to the target repo's
current branch and the worktree is removed.

## Adding agent #6

10 lines of YAML, no code change. Add to `config/agents.yaml`:

```yaml
agents:
  archivist:
    role: "Summarize completed tasks into a changelog entry."
    model:
      primary: "gemini/gemini-2.0-flash"
      fallback: "deepseek/deepseek-chat"
    system_prompt_file: "llm/prompts/archivist.j2"
    temperature: 0.2
    max_tokens: 1024
    allow_mock: true
```

Then add a node in `config/workflow.yaml` and a thin `agents/archivist.py`
subclass of `BaseAgent`. Done.

## What is forbidden by design

- ❌ Agent-to-agent messages (chatter). Agents read files, write files.
- ❌ An orchestrator that "thinks". It executes nodes.
- ❌ Long-running server threads waiting on HITL. The server is stateless.
- ❌ Loading the whole repo into context. The coder reads a bounded repo map.
- ❌ Docker sandboxes. Git worktrees are real branches — mergeable, abortable.

## Cron jobs (Phase 5)

The FastAPI app registers one periodic job on startup:
`reindex_target_repo` runs every hour to keep the vector store + codemap
fresh as files change outside myforge. Status visible at `GET /cron`.

To add more cron jobs, call `get_cron_manager().add_job(...)` from
anywhere with access to the orchestrator.

## Verified end-to-end

The smoke test exercises all 5 phases in one run:
- Thinker writes plan.md (2 tasks, T1 needs research)
- HITL plan_approval gate pauses
- Approve -> researcher runs for T1 (web search attempted; falls back to
  model knowledge without TAVILY_API_KEY)
- Coder reads retrieval context, writes real files to a worktree branch
- Reviewer reads worktree files, approves
- Branch node merges worktree branch -> target_repo
- Loop advances to T2 (no research), repeats
- Router fallback log records every model attempt
- Cron job registered

Run it: `python scripts/smoke_test.py`
