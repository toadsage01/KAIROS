Implementation goal & status list - My recent inability to keep up with the process done so far and efficient and clean writing of prompts was inevitable but this is nothing that should be called a failure, because we're gonna deal with this problem too. In this prompt you'll see the list of all goals (except few that I'll implement after achieveing these) & their status (not entirely accurate or sometimes even if accurate and & yet respectively thus marked with a note following them written in single or multiple lines) all starting with ---. Some points at later half of this prompt is already discussed or is related to points or paragraphs mentioned earlier. With these re arrange all the phases strongly coherently and modularly. 

I want you now to complete each phase in one single compilation by you, take however long time you'd need, but I want accurate working output. Do smoke test, dummy test. You already have the knowledge of both the kairos and the webai2api. So you can get it done. I'll only be checking end phase results. And will be continuing in a loop like this untill all phases are implemented with complete accuracy. Remember we should not getting stuck in error looping by writing efficient code and reseraching the right pathway to a goal, we learn from our mistakes, before implementing anything we think about it. 

Below I'll list the implementation status with some fixes where I feel need be. But at each iteration you only need work on one phase so you can have full focus on it. 

✅ File-driven blackboard (state/*.md, tasks.json) --- this is already great but is not efficient enough for complex works, is it relaying efficienty with the memory pool and wisdom pool for wisdom os (the os with a focus only but infinite background which overlays all my work, all related work are compiled together dynamically, reduancy is reomved, smart bloom taxonomy with spaced repetition reminder etc. and much more).

✅ DAG executor (not an LLM agent — pure topology) --- Dag executor sounds great and it still needs to be much more complex plus it must need a ai partner together to work out on any complex task. AI as a smart real life manager replacement. 
✅ 5 agents wired (thinker, coder, reviewer, bugfixer, researcher) --- we need to implement more agents, as I've told you before that I'll including tools like open-design, so a agent with specialised tools other than basic to work extensively on any design I've in my mind or can prompt/idea or brainstorm with me with actual web access and research.

✅ HITL gates with JSON signal files. --- telegram bot is up and it doesn notifies me of status mostly errors and task done message for every implementation. but it no where close to being a agent which has smartness so it understand ok this task is simple, we need not approval from me and just sending a summarized stylised response to me is enough and when a task is critical it asks me, the brainstomer or prompt refiner agent that I've told also should work in here, as sometimes I'll be away from my laptop and I would like to use my phone to continue development. Another important thing that when a prompt refiner or brainstormer or as below mentioned blueprint feature. A agent works with me, perhaps the best would be  a mix claude with deep reseach input, which we may use from google deep-research or perplexity research by upgrading our adapter to be able to handle these. with those. usually an  entire llm chat will be about the project but if a chat has been made with the brainstormer, the brainstorming for that particular project should always be in that and the project started in another chat should continue in that, so we need smart logging and retrieval in any cases of chat across all.  

✅ Git worktrees per task + merge-on-approval --- we can avoid git right now, after the whole project is done, we can implement git worktree, sign up with my auth aswell, to keep a cloud back up for me aswell.

✅ Async API (job queue + background worker, no blocking) --- I don't have much knowledge of async, but what you've already implemented is doing a fab job. If you need implement it fruther in case need be. feel free to do so.

✅ Per-run workspace selection (like Claude Code) --- very important, we had it on streamlit ui and right now not on the tui.

✅ APScheduler cron (hourly re-index) --- it is active but I haven't been able to use, if telegram bot is considered, then yeah one cron is up.

✅ YAML-configured agents (adding agent = 10 lines of YAML) --- agent management and metric tracking is also important, right now what is there is good. 

✅ Prompt logging (logs/prompts/{timestamp}_{agent}_{model}.txt) --- these prompt loggings and all sort of logs are important. And specially for the models to run aswell, the current date agent frameworks uses harness and system which allows models to learn from its mistake and also the capbility to save a work style done if that has succeeded efficiently like hermes ai. 

✅ Router fallback logging (logs/router.log) 
✅ Tool call logging (logs/tool_calls.log)
✅ Hard task cap in orchestrator (max_tasks_per_goal: 3) --- this definitely is not working the right way, but we also need to understand the different requirement of different projects, not all can be implemented with a fix no. of tasks!
```

### LLM Router & Web Bridge
```
✅ LiteLLM router with fallback chains (primary → fallback → fallback_2 → mock) --- we will eventually remove mock with a local run model my choice. 
✅ WebAI2API bridge integration (Claude, GPT-4o, DeepSeek, Gemini, GLM) this has been the one of the most important feats that we achieved. we need to give a model access to the webai2api aswell via whatever ways that would allow kairos to easily track bug, open up things as requirements be. We'll also set up a lightweight instance viewer for all the active config.yaml mentioned files, so I can abort unnecessary manual labor there.

✅ conversationId pass-through (session continuity) --- very important I've discussed a few bit above, the management of these conversationIDs should be managed efficiently.

✅ json_mode pass-through (strict JSON output directive) --- very important, we will learn from the renowned llm's and compeletely use the webGUI interfaces just as a api would for these models.

✅ litellm.drop_params = True (drops unsupported temperature/top_p) 
✅ stream: True always (WebAI2API rejects non-streaming when busy)

✅ Response validation (min length, HTML detection with fence check, max length) --- this is important. we will learn from the renowned llm's and compeletely use the webGUI interfaces just as a api would for these models.

✅ openai/ prefix for ALL web bridge models (correct auth header)

✅ Normalizer fallback (Groq + instructor for parsing SOTA output) --- we will learn from the renowned llm's and compeletely use the webGUI interfaces just as a api would for these models.
✅ <think> tag stripping (DeepSeek reasoning mode) will work on these below.
✅ Prose-around-code stripping (normalizer preprocessor) 

✅ Garbled output detection (CSS in HTML, truncated fences) --- Yes obviuosly, since when kairos will be done. I'll be undertaking myself on very complex projects, will need my kairos to work just as claude code would with model 4.8. we are coping our way. and we sure are gonna win over those.
```

### WebAI2API Patches (Applied to Docker Container)
```
✅ Session continuity in chatgpt_text.js (sessionCache Map)
✅ Session continuity in deepseek_text.js
✅ Session continuity in gemini_text.js

✅ claude_text.js rewritten (SSE interception, not DOM polling) --- claude is a genius and the market leader. we must use it effectively, research need be.

✅ zai_text.js new adapter (targets chat.z.ai, not zai.is) --- chat.z.ai webGUI features a agent mode which is a very strong powerhouse! We'll work over the adapter to utilise this feature aswell. also chat.z.ai in any mode agent or chat, both mostly returns "peak hours issue" dialogue whenever website traffic is too much which is the case all the time these days. they keep the prompt loaded in the textbox and I had to manually click esc or cancel the peak hour notification dialogue and re click the send button or enter as many times unless it produces output, on average 4 times. max case being around 13 times. 

✅ parse.js patched (XML tags, json_mode, conversationId extraction)
✅ routes.js patched (conversationId pass-through)

✅ queue.js patched (conversationId in meta) --- we will learn from the renowned llm's and compeletely use the webGUI interfaces just as a api would for these models.

✅ PoolManager.js patched (conversationAffinity Map, sticky worker) --- poolmanager. As I've started the working of the project and I'd mentioned a very important and core thing that the trouble of all different platforms having different memory base is trouble some, I wanted the memory to be in one place effectively and smartly, when I'll have a GUI, I'll have a interface like any other platform, but all the memory context will accessible to all llm's whicever way I'm using them, they should be able to (other than their own webGUI context memory) think from the project memory pool and smart retrieval and not like going through everyting to find out. the memory pool will serve and convert the knowledge to wisdom pool managed by another superior agent where this wisdom will be smartly curated,  these all and more will be part of my wisdom os within kairos.

✅ waitTimeout raised to 600000 (10 minutes) we need to be safe, we will learn and keep doing improvement related to this.

✅ logLevel set to warn . I'm thinking eventually after the current work is done. to change the webai2api completely to english to avoid any language led confusion. 

✅ 5 browser instances configured (chatgpt, deepseek, gemini, claude, zai) right now this the great asset. 
```

### --- Tool Framework tools are the very essence of a agentic operator and harness. we need deep-research, extensive web-crawl, btw questions, /watch tool like claude has, and so many tools while the core being the very important ones. Kairos tool-framework will be no less than claude-codes or roo code's. 
```
✅ BaseTool, ToolResult, ToolContext, ToolPermission
✅ ToolRegistry (register, execute, list_schemas, list_react_descriptions)
✅ Permission classifier (SAFE / MODERATE / DANGEROUS)
✅ 14 built-in tools:
   - Filesystem: read_file, write_file, edit_file, list_dir, mkdir
   - Terminal: execute (whitelisted), background_job
   - Git: git_status, git_diff, git_log, git_commit, git_branch
   - Search: grep, glob
✅ ToolAgent base class (tool loop support)
✅ route_with_tools() for native function calling (Groq/Gemini)
✅ react_loop() for ReAct text-based tool calling (web bridge)
✅ Tool framework test suite (6 tests, all passing)
```

### --- Prompt Engineering we will learn from the renowned llm's or agent frameworks and compeletely use the webGUI interfaces just as a api would perform. As learning from some of the finest agents out there both in open source and premium tiers. We have direct example how much before we had knowledge of webai2api system through scanning its whole repo, the trouble with faced with getting a desired json or xml output, now after that json mode true we have it has become easier, since once you before said, the models through api also works with returning output in json and ingesting out prompt after parsing it themselves in json.
below agents aren't enough we need more which must shall be smartly orchestrated with great prompts, and even sometimes we need parallel execution, 
```
✅ Thinker: task caps (1-3 max), examples, needs_research rules
✅ Coder: draconian output contract, language selection guide, HTML/CSS/JS examples
✅ Reviewer: 6-check verification checklist, "if you can't name the defect, APPROVE"
✅ Bugfixer: "fix ONLY defects, don't rewrite" (separate from coder prompt)
✅ <blocked> tag protocol (agents can decline safely)
✅ Jinja2 template variables (task_id, description, acceptance_criteria, etc.)
```

### TUI (Terminal User Interface) --- TUI is temporary or a option that will be available. We'll be operating through the TUI as soon as agentic capabilities will be set with the adapters in place and fine working as mentioned above. After we achieved something claude-code efficiently, we'll start building the GUI with it in agentic loop system. Many features likes Job Hunter and Wisdom OS and OpenDesign and more does require a visualisation. 
And If we can fetch the webBridged SOTA's thinking process and visualise in the terminal it would be better, believing that it wouldn't consume much resource. But if too much waste it is then we just have a simple three dot animation represented in front of a model, I think only active models should be visible that is running for the particular step in the process. Unlike now where all the models are shown and one highlights when it is active. all models should only be visible through a tab in setting through slash command or key shortcut.
```
✅ 3-panel layout (Agent Flow | Code Changes | Conversation Log)
✅ Model-colored status indicators (brand colors per model)
✅ Real-time polling (every 2 seconds from FastAPI /state)
✅ Syntax-highlighted code diffs (rich.syntax, monokai theme)
✅ Inline HITL approvals (Ctrl+A / Ctrl+R)

✅ /btw side questions (Ctrl+T — modal dialog, non-blocking) --- the current btw doesn't takes long file posting, and ctrl s also doesn't work. It goes to the reviewer  to be added in the next iteration, so to tell, it won't necessarily always be change that I'm asking, It could simply be a question that I'm asking about what is going on with current process or a random question. The agent handling this should have the knowledge of the whole memory pool along with ongoing project deeply. 

✅ /btw backend integration (POST /btw → state/btw_queue.json → orchestrator reads)
✅ /blueprint mode (Ctrl+B — idea refinement wizard) --- we will learn from the renowned llm's and compeletely use the webGUI interfaces just as a api would for these models. There might be a copy of claude code's version of it. and other online tools, we will research and find our suitability.

✅ Slash commands (/help, /status, /reset, /step, /logs, /models, /tools, /btw, /blueprint)
✅ Keyboard shortcuts (all with priority=True)
✅ Agent flow visualization (DAG with status icons)
✅ Color-coded log (green=success, red=error, yellow=paused, cyan=wrote)
✅ Task list display
✅ Recent jobs display
✅ Plugin system architecture (BasePlugin, PluginManager)

✅ File tree browser widget (FileTreePanel) --- I'm not sure what you're exactly intending from it, but bro we don't have that sort of time if we are trying to replace file browser or file tree (ctrl B) in vs code. Those are beautiful plus they provide several extension that go along in vs code!

✅ WebSocket endpoint (/ws — ready for real-time streaming)
```

### Other
```
✅ Telegram bot (created, partially working — bot starts but notifications may not fire)

✅ ChromaDB vector store (embedded, persistent) --- we will learn from the renowned agent harnesses or frameworks as this is related to a very core aspect.
✅ Codemap (ctags preferred + regex fallback for Python/JS/TS/Go/Rust) we will review the whole codegraph github url and their functioning so to be able to implement in our system!

✅ Retriever (combines vector + codemap into bounded context)

✅ Tavily + trafilatura researcher, --- I've discussed above how important deep web research is for us. We will also separate smart crawlers which can crawl any website we need information from.

✅ MCP client (one-shot sessions, official SDK) --- this can be done in last phases, when I'll be connecting my mail boxes, calendar, alarm clock and so many other things with restrictive security protocols.

✅ Smoke test (mode-aware: LIVE vs MOCK, all 5 phases verified) --- smoke test is good when considered testing with mock, you must do dummy test aswell considering sample test cases of all sorts or common outliers so to have saved my time a little by doing in your web terminal itself.

✅ Tool test suite (6 tests, all passing)
```

---

## ⚠️ PARTIALLY DONE (Code Exists But Not Working/Enabled)

```
⚠️ Tool-loop mode
   - Code exists: ToolAgent, route_with_tools, react_loop
   - use_tools: false in agents.yaml (disabled)
   - NOT TESTED with real SOTA models
   - Needs: enable use_tools: true, test with coder agent

⚠️ WebSocket streaming in TUI
   - /ws endpoint exists in FastAPI
   - TUI still uses polling (every 2 seconds)
   - Needs: switch TUI to WebSocket client

⚠️ File tree browser in TUI layout
   - FileTreePanel widget exists
   - NOT wired into the main 3-panel layout
   - Needs: add as toggleable panel (Ctrl+D or similar)

⚠️ Plugin auto-loading
   - PluginManager exists
   - Does NOT auto-load plugins from ~/.kairos/plugins/
   - Needs: directory scanning + dynamic import

⚠️ Blueprint LLM integration
   - BlueprintScreen calls route() with Claude
   - NOT TESTED — Claude needs to respond with QUESTION:/BLUEPRINT: format
   - May need prompt tuning

⚠️ MCP client
   - Code exists in tools/mcp.py
   - NOT TESTED with real MCP servers
   - Needs: config/mcp.yaml + one test server

⚠️ Memory compaction (partially) --- very important when eventually the memory pool will start getting very big there are many compaction methods out there, we will research and work on it. also note the memory which will be passing to the wisdom pool must be very much refined, redundancy free, and curation according to the wisom os as the title sounds and as I've discussed above a little. 

   - ChromaDB indexes raw file chunks
   - Returns bloated context (raw chunks, not signatures)
   - Codemap exists but uses regex, not tree-sitter AST
```

--- A very cool and smart thing I learnt is how a router exists for llm who are MoE based. A router so smart handling a model as big as 755B with around 256 Experts each with size. upon a prompt it finds the top performers for that aspect and word by word changes the experts according to the best fit. We'll reserach this further more.

---

## ❌ NOT IMPLEMENTED (Planned But Not Started)

### Phase 2: Memory Compaction (4-6 hours)
```
❌ tree-sitter AST parsing in codemap.py
❌ Signature-based retrieval (function/class signatures, not raw chunks)
❌ Dependency graph (networkx — what calls what)
❌ Visual code graph (TUI panel showing code structure)

❌ Context compaction (10x smaller prompts, 10x better relevance) --- yeah should be a help of another agent or tool or brainstormer agent itself or after the brainstormer or prompt refiner agent as discussed above is done.
```

### Phase 3: Agent Tools (6-8 hours)
```
❌ Enable tool-loop mode (use_tools: true for coder/reviewer)
❌ Reviewer tools: run_pytest, run_lint, diff
❌ Researcher tools: web_search, web_scrape, summarize
❌ Thinker tools: read_repo_map, list_files
❌ Test execution in reviewer (can't run code, only reads it)
❌ Diff-based coder (search/replace blocks instead of full files — Aider style)
```

### Phase 4: Branch Sandbox (4-5 hours) --- Gitlab provides a very beautiful design for keep track of changes and branches and rollback features and is obviously the industry standard. our sandboxing shuold work along with it.
```
❌ Plandex-style branch isolation (worktrees exist but no comparison UI)
❌ Branch comparison UI (TUI panel showing diff between branches)
❌ Merge conflict resolution agent
❌ Branch rollback per task
```

### Phase 5: Architecture Visualization (6-8 hours) --- After being done with the kairos GUI, i.e, all implementation and features have been made and perfectly functioning, I'll be undertaking several projects related to designing, the open design we will research if it's fitted to be called web desiger only, we will make a agent with such capability and call it that. I remind you that open design is a open source alternative of claude design. and is a good competitor.
```
❌ OpenDesign-like tool integration
❌ System architecture diagram generation
❌ Code graph visualization (D3.js or TUI)
❌ Real-time DAG execution visualization
```

### Phase 6: Directive Research Agent (4-5 hours)
```
❌ Dynamic questioning when goal is vague (Blueprint mode is the start)
❌ Scoped local + web research
❌ Chain-of-thought visualization
❌ HITL clarification gates (separate from plan_approval)
```

### Phase 7: Wisdom Pool (4-5 hours)
```
❌ Curated knowledge storage (persistent across runs)
❌ Note-like curation features
❌ Learning-optimized collage format
❌ Visualization of memory pool
❌ Archivist agent (summarize completed runs into wisdom)
```

### Phase 8: Mobile HITL (2-3 hours)
```
❌ Fix Telegram integration (notifications not firing)
❌ Summarize + ask for decisions via phone
❌ Resume orchestrator from phone approval
❌ Error notifications via phone
❌ Run completion notifications via phone
```

### Phase 9: Model Routing Agent (2-3 hours)
```
❌ Provider health monitoring (ping each provider)
❌ Rate limit tracking (X-RateLimit-Remaining headers)
❌ Slug deprecation alerts ("model X expiring next month")
❌ Config change suggestions ("switch from A to B because A has 60% failure rate")
❌ /router_status endpoint
```

### Phase 10: Smart Side-Kick Models (3-4 hours)
```
❌ In-call guidance during running orchestrations
❌ Query injection without blocking (/btw is the foundation)
❌ Context-aware assistance
❌ Real-time status queries ("what's happening now?")
```

### Phase 11: Dynamic DAG (4-5 hours)
```
❌ Task-type-aware orchestration (different DAG for research vs coding)
❌ Runtime DAG modification (add tasks mid-run)
❌ Conditional agent insertion (thinker injects researcher mid-task)
❌ Dynamic node creation from agent output
```

### Phase 12: Complete Autonomy (ongoing)
```
❌ Full HITL loop (pause/resume from any state)
❌ Full research loop (autonomous web research)
❌ Full implementation loop (code → test → fix → merge)
❌ "Does everything" state
❌ Per-project persistent state (resume partial projects)
```

### Phase 13: GUI (8-12 hours)
```
❌ Tauri desktop app
❌ Full GUI with drag-drop
❌ System tray integration
❌ Multiple project workspaces
❌ Visual DAG editor
❌ Architecture diagram generation
```

### Phase 14: VS Code Extension (4-6 hours)
```
❌ Connect to same FastAPI backend
❌ File tree integration
❌ Inline code review
❌ Terminal panel for agent output
❌ Status bar with current agent + model
```

### Phase 15: --- OpenSpec  is open source tool or harness which keeps agents in a framework directive towards the goal and not allow them ran astray, we'll learn and how we implement it for our kairos. very important, as you can see or you might not realise but I'm having a hard time writing prompts now, My prompts are not structurally good, and redundant over places because I get afraid if we will run amock from what I had initially outlayed too. Since My knowledge is too basic, I sometimes don't now but I can set a idea out loud in my language very well plus with the help of prompt refine agent (i'm having a hard time naming I mean keeping it aligned, you see!).
```

### Other Features Mentioned
```
❌ Job Hunter feature (mentioned briefly, no details) --- once we are done with TUI we build the GUI and features such as Wisdom OS, Job Hunter Directly right after it.

❌ Presentation layer (research → presentation format, visual output) --- This I need a dynamic visualiser for each Project, So I can keep track of my agents are building and I can visualise easily. We'll work on it after Wisdom OS is done.

❌ Custom GPTs / Claude Projects integration (persistent system prompt carriers)--- right now after we have the capbility of receiving output in json, we'll skip it and reserach it at last to see if it can improve performance of our system much further.

❌ Local LLM (Ollama) integration --- for last phases
❌ Colab/Kaggle GPU hosting for 14B models --- for last phases
❌ DuckDuckGo AI chat bridge (free frontier models) --- no we won't use this anymore.

❌ SearXNG self-hosted search --- I don't know much about it right now, But it seems that it would come handly later, we'll see at last phases

❌ Cloudflare bypass tools (trawl, browser-search) --- and more, we research deeply much further.

❌ Cost tracking (tokens-per-call metric, daily/weekly breakdown) --- a very imortant dynamic hard coded with agent by side. both to provide visuals and change route plans as per the metric evalaution, will research more and enhance the fallback system to a industry level markdown.

❌ Multi-task merge conflict handling (T1 + T2 touching same file) --- these are some very root problem related to webBridged Sota output, I hope it doesn't occur and it shouldn't be occuring in first place at all because it's something so basic!

❌ Run history search (like Mnemonai — fuzzy search across past runs) --- and with hermes this would be so beautiful

❌ Headless API for analysis (JSON export of runs)
❌ Configuration system (TOML for TUI preferences)
❌ Sound notifications
❌ Theme customization
```

### Known Bugs (Not Fixed)
```
❌ Bugfixer overwrites good code with simpler version
   - Cause: Bugfixer prompt says "REWRITE from scratch" — too aggressive. --- When this happened on that clock prompt i gave in, I myself was not exactly sure if why that happened, it could be that bugfixer did it or the files were never updated, I don't to keep handling such problems manually, another agent or system should have access to these files and the worktree of it with terminal log automatically to check. safety and sanboxing considered.
   - Fix: Change to "fix ONLY the specific defects, don't rewrite unrelated code"

❌ GPT-4o web bridge truncates long output --- (since you, the model I'm working with have a knowledge cut off from 1.5 years, date today is 16 July 2026, 5:00PM IST, you don't realise the up to date details, like just a week ago gpt 5.6 was launched, a direct competitor of fable 5, fable is a upgrade series from opus. and is the leading indsutry model. btw you're model is called glm5.2 developed by Zhipu.ai and hosted on url chat.z.ai. a open source model. Your agent mode is on par with any premium models, we must get the adapter to be able to use this agent mode efficiently and reach the automation AI soon)
   - Cause: SSE listener in chatgpt_text.js cuts off early .. we need not have any problem with the web bridging. it must run smoothly for us to win in this project. it is doable.
   - Fix: Investigate waitApiResponse idle timer in page.js

❌ ChatGPT "page load timeout" errors
   - Cause: Browser navigation timeout (constants.js may not be copied)
   - Fix: Verify constants.js is in the container with 60s timeout

❌ Coder produces garbled output (CSS mixed into HTML)
   - Cause: SOTA model confusion via web bridge
   - Fix: Partly addressed (validation catches it), but root cause is web bridge reliability

❌ Reviewer rejects repeatedly without actionable feedback
   - Cause: Reviewer prompt improved but SOTA models still vague
   - Fix: Further prompt tuning or use Groq for reviewer (more reliable)
```

---

## Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│  STATUS SUMMARY                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ✅ DONE (working & verified):     65+ features                      │
│  ⚠️ PARTIALLY DONE (code exists):   8 features                      │
│  ❌ NOT IMPLEMENTED:               50+ features                      │
│  🐛 KNOWN BUGS:                     5 bugs                          │
│                                                                     │
│  ESTIMATED REMAINING WORK:                                         │
│    - Fix bugs:                    2-3 hours                         │
│    - Enable tool-loop:            1-2 hours                         │
│    - Phase 2 (Memory):            4-6 hours                         │
│    - Phase 3 (Tools):             6-8 hours                         │
│    - Phase 4-14:                  40-60 hours                       │
│    - GUI + VS Code:               12-18 hours                       │
│    Total:                         ~65-90 hours                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```a