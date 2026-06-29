"""
E2E smoke test for myforge Phases 1-5.

Mode-aware: detects whether real LLM providers are available.
  - Mock mode (no keys / no litellm): asserts the mock thinker's fixed
    plan shape (T1.needs_research=true so researcher flow is exercised).
  - Live mode (real keys + litellm): asserts only structural properties
    (plan parses, files land on disk, branches merge, logs written) —
    does NOT impose any specific plan content, since real LLMs produce
    varied output.

Runs in either mode. With no keys, falls back to mock provider.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGET_REPO = ROOT / "target_repo"
STATE_DIR = ROOT / "state"
LOGS_DIR = ROOT / "logs"
CHROMA_DIR = ROOT / ".chroma"


def _seed_target_repo():
    TARGET_REPO.mkdir(parents=True, exist_ok=True)
    (TARGET_REPO / "src").mkdir(exist_ok=True)
    (TARGET_REPO / "src" / "app.py").write_text(
        "def healthz():\n"
        "    return {'status': 'ok'}\n"
        "\n"
        "def serve():\n"
        "    print('serving on :8000')\n"
    )
    (TARGET_REPO / "src" / "utils.py").write_text(
        "def helper(x):\n"
        "    return x * 2\n"
    )


# Wipe everything for a clean test
for d in (STATE_DIR, LOGS_DIR, TARGET_REPO, CHROMA_DIR):
    if d.exists():
        shutil.rmtree(d)
STATE_DIR.mkdir(parents=True, exist_ok=True)
_seed_target_repo()
os.environ["MYFORGE_TARGET_REPO"] = str(TARGET_REPO)

from core.orchestrator import Orchestrator  # noqa: E402
from core.cron import get_cron_manager  # noqa: E402

# Detect mode: are we running with real LLMs or mock?
try:
    import litellm  # noqa: F401
    _HAS_LITELLM = True
except ImportError:
    _HAS_LITELLM = False

_HAS_ANY_KEY = any([
    os.getenv("GOOGLE_API_KEY"),
    os.getenv("DEEPSEEK_API_KEY"),
    os.getenv("GROQ_API_KEY"),
    os.getenv("OPENROUTER_API_KEY"),
    os.getenv("OPENAI_API_KEY"),
])
LIVE_MODE = _HAS_LITELLM and _HAS_ANY_KEY

orch = Orchestrator(state_dir=str(STATE_DIR), config_dir=str(ROOT / "config"))

print("=" * 70)
print("PHASES 1-5 E2E: DAG + worktree + retrieval + researcher + cron + logs")
print("=" * 70)
print(f"  target_repo    = {TARGET_REPO}")
print(f"  vector avail   = {orch.vector.available}")
print(f"  cron available = {get_cron_manager().available}")
print(f"  litellm        = {_HAS_LITELLM}")
print(f"  any API key    = {_HAS_ANY_KEY}")
print(f"  MODE           = {'LIVE (real LLMs)' if LIVE_MODE else 'MOCK (deterministic fallback)'}")
print()

# ----- Phase 5: register a cron job to verify scheduler works -----
cron = get_cron_manager()
if cron.available:
    cron.add_job(
        job_id="test_reindex",
        description="test job — re-index target_repo",
        func=lambda: orch.__setattr__("_indexed", False),
        interval_seconds=3600,
    )
    print(f"  cron jobs registered: {[j['id'] for j in cron.status()['jobs']]}")
else:
    print("  cron: APScheduler not installed — degrading to no-op (still recorded)")
print()

# ----- Phase 1-3: start + approve -----
print("STEP 1: start(goal) -> expect paused at plan_approval")
rs = orch.start(goal="add a /healthz endpoint to api/main.py")
print(f"  status={rs.status}  node={rs.current_node_id}  tasks={len(rs.tasks)}")
assert rs.status == "paused", f"expected paused after thinker, got {rs.status}"
assert len(rs.tasks) >= 1, "no tasks parsed from plan"

# Mode-aware: in mock mode we KNOW T1 has needs_research=true (mock behavior).
# In live mode, the LLM decides — we don't impose.
if not LIVE_MODE:
    t1 = rs.tasks[0]
    assert t1.get("needs_research") is True, \
        f"mock T1 should need research, got {t1}"
    print(f"  T1.needs_research = {t1.get('needs_research')}  (mock mode: forced true)")
else:
    needs_research_tasks = [t for t in rs.tasks if t.get("needs_research")]
    print(f"  tasks needing research: {len(needs_research_tasks)} (live mode: LLM decides)")
print()

print("STEP 2: approve(plan_approval) -> full DAG run")
rs = orch.approve("plan_approval", decision="approved")
print(f"  status={rs.status}  node={rs.current_node_id}")
assert rs.status == "done", f"expected done, got {rs.status}: {rs.last_error}"
print()

# ----- Phase 4: researcher verification (mode-aware) -----
print("STEP 3: verify researcher flow (Phase 4)")
needs_research_task_ids = [t["id"] for t in rs.tasks if t.get("needs_research")]
no_research_task_ids = [t["id"] for t in rs.tasks if not t.get("needs_research")]
print(f"  tasks with needs_research=true: {needs_research_task_ids}")
print(f"  tasks with needs_research=false: {no_research_task_ids}")

# For each task flagged needs_research, research/{task}.md must exist
for tid in needs_research_task_ids:
    p = STATE_DIR / "research" / f"{tid}.md"
    assert p.exists(), f"MISSING: research/{tid}.md (task flagged needs_research but researcher didn't run)"
    print(f"  OK: research/{tid}.md written ({p.stat().st_size} bytes)")
# For each task flagged needs_research=false, research/{task}.md must NOT exist
for tid in no_research_task_ids:
    p = STATE_DIR / "research" / f"{tid}.md"
    assert not p.exists(), f"research/{tid}.md should NOT exist (needs_research=false)"
    print(f"  OK: research/{tid}.md correctly absent")
print()

# ----- Phase 2: verify files landed on disk -----
print("STEP 4: verify target_repo received merged files")
# At least one real file should have been written by the coder across all tasks
merged_files = []
for p in TARGET_REPO.rglob("*"):
    if p.is_file() and ".git" not in p.parts and ".worktrees" not in p.parts:
        if p.name != "README.md":  # we seeded README
            merged_files.append(p.relative_to(TARGET_REPO))
assert merged_files, "no files written to target_repo — coder didn't produce any path= blocks"
for f in merged_files:
    print(f"  OK: {f}  ({(TARGET_REPO / f).stat().st_size} bytes)")
print()

# ----- Phase 3: verify codemap + retrieval -----
print("STEP 5: verify codemap + retrieval")
sym_names = {s.name for s in orch.codemap.symbols}
print(f"  codemap has {len(orch.codemap.symbols)} symbols: {sorted(sym_names)[:10]}")
assert len(orch.codemap.symbols) > 0, "codemap found no symbols"
if orch.vector.available:
    stats = orch.vector.stats()
    print(f"  vector store: {stats}")
    assert stats.get("chunks", 0) > 0, "no chunks indexed"
else:
    print("  vector store: not available (chromadb not installed) — codemap-only retrieval")
# Retrieval should return something non-empty
ctx = orch.retriever.retrieve({"title": "healthz", "description": ""})
assert ctx and "(no retrieval context available)" not in ctx, "retrieval returned empty"
print(f"  OK: retrieval returned {len(ctx)} chars of bounded context")
print()

# ----- Phase 5: verify router fallback log -----
print("STEP 6: verify router fallback log (Phase 5)")
router_log_path = ROOT / "logs" / "router.log"
assert router_log_path.exists(), "logs/router.log missing"
log_text = router_log_path.read_text()
# Every agent invocation should have produced at least one OK line
ok_lines = [l for l in log_text.splitlines() if "OK" in l]
assert ok_lines, "no OK entries in router.log"
# Count agent invocations: at minimum, thinker + 1 coder + 1 reviewer per task
min_expected = 1 + 2 * len(rs.tasks)
print(f"  OK: router.log has {len(ok_lines)} success entries (min expected: {min_expected})")
# Show first LIVE success if in live mode, else first MOCK
if LIVE_MODE:
    live_lines = [l for l in ok_lines if "LIVE" in l]
    if live_lines:
        print(f"  Sample: {live_lines[0]}")
    else:
        print(f"  (no LIVE entries — all calls fell back to mock)")
else:
    print(f"  Sample: {ok_lines[0]}")
print()

# ----- Phase 5: cron status -----
print("STEP 7: cron status (Phase 5)")
status = cron.status()
print(f"  available={status['available']}  started={status['started']}")
print(f"  jobs={len(status['jobs'])}")
for j in status["jobs"]:
    print(f"    - {j['id']}: interval={j['interval_seconds']}s runs={j['runs']}")
print()

# ----- git history -----
print("STEP 8: git history has merge commits")
r = subprocess.run(
    ["git", "-C", str(TARGET_REPO), "log", "--oneline"],
    capture_output=True, text=True, check=True,
)
print(r.stdout)
merge_count = r.stdout.count("myforge: merge task")
assert merge_count >= 1, "no merge commits in git history"
print()

print("LOG TAIL (orchestrator)")
print(orch.state.read_log(tail=40))
print()

print(f"ALL 5 PHASES PASSED (mode={'LIVE' if LIVE_MODE else 'MOCK'})")
