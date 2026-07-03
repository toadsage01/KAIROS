┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: Stabilize SOTA (NOW — 1-2 hours)                         │
├─────────────────────────────────────────────────────────────────────┤
│  ✅ Web bridge working (done)                                       │
│  ✅ Prompt logging (done — this update)                             │
│  ⬜ Fix coder parsing (run with new coder.j2, paste me the logs)   │
│  ⬜ Verify multi-provider fallback works                            │
│  RESULT: Reliable SOTA agent runs                                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: Memory Compaction (NEXT — 4-6 hours)                     │
├─────────────────────────────────────────────────────────────────────┤
│  ⬜ tree-sitter AST parsing in codemap.py                           │
│  ⬜ Signature-based retrieval (not raw chunks)                      │
│  ⬜ Dependency graph (networkx)                                     │
│  ⬜ Visual code graph (streamlit tab)                               │
│  RESULT: 10x smaller prompts, 10x better relevance                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 3: Agent Tools (AFTER — 6-8 hours)                          │
├─────────────────────────────────────────────────────────────────────┤
│  ⬜ Tool framework (each agent gets specific tools)                 │
│  ⬜ Coder tools: file_read, file_write, run_tests                   │
│  ⬜ Reviewer tools: run_pytest, run_lint, diff                      │
│  ⬜ Researcher tools: web_search, web_scrape, summarize             │
│  ⬜ Thinker tools: read_repo_map, list_files                        │
│  RESULT: Agents can actually execute, not just generate text       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 4: Branch Sandbox (FUTURE — 4-5 hours)                      │
├─────────────────────────────────────────────────────────────────────┤
│  ⬜ Plandex-style branch isolation (already have worktrees)         │
│  ⬜ Branch comparison UI                                            │
│  ⬜ Merge conflict resolution agent                                 │
│  ⬜ Branch rollback per task                                        │
│  RESULT: Safe experimentation without breaking main                │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 5: Architecture Visualization (FUTURE — 6-8 hours)           │
├─────────────────────────────────────────────────────────────────────┤
│  ⬜ OpenDesign-like tool integration                                │
│  ⬜ System architecture diagram generation                          │
│  ⬜ Code graph visualization (D3.js or similar)                     │
│  ⬜ Real-time DAG execution visualization                           │
│  RESULT: Visual understanding of what the agent is doing           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 6: Directive Research Agent (FUTURE — 4-5 hours)             │
├─────────────────────────────────────────────────────────────────────┤
│  ⬜ Dynamic questioning when goal is vague                          │
│  ⬜ Scoped local + web research                                     │
│  ⬜ Chain-of-thought visualization                                  │
│  ⬜ HITL clarification gates                                        │
│  RESULT: Agent can handle vague ideas and clarify them             │
└─────────────────────────────────────────────────────────────────────┘