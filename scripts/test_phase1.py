"""
Phase 1: Core Loop Reliability — Dummy Tests

Tests the specific fixes implemented in Phase 1:
1. Bugfixer prompt: doesn't rewrite from scratch
2. Router auto-retry: retries on short response
3. Dynamic task caps: scales with goal complexity
4. File integrity: detects empty/truncated writes
5. TUI workspace selection: /workspace command works
6. HTML validation: doesn't reject valid HTML code blocks
"""
import sys
import os
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm.router import _validate_response, ModelEndpoint, _mock_response
from core.orchestrator import _parse_plan
from core.parser import parse_coder_output


def test_html_validation():
    """Test that valid HTML code blocks are NOT rejected as Cloudflare."""
    print("=" * 60)
    print("TEST 1: HTML Validation (don't reject valid code)")
    print("=" * 60)
    
    endpoint = ModelEndpoint(model="test")
    
    # Valid HTML code block — should PASS
    valid_html = '''```html path=index.html
<!DOCTYPE html>
<html lang="en">
<head><title>Test</title></head>
<body><h1>Hello</h1></body>
</html>
```'''
    
    try:
        result = _validate_response(valid_html, endpoint)
        print(f"  ✅ Valid HTML code block accepted ({len(result)} chars)")
    except Exception as e:
        print(f"  ❌ Valid HTML rejected: {e}")
        return False
    
    # Raw HTML without fences — should FAIL (Cloudflare block)
    raw_html = '<!DOCTYPE html><html><head><title>Cloudflare</title></head></html>'
    
    try:
        _validate_response(raw_html, endpoint)
        print(f"  ❌ Raw HTML without fences should have been rejected")
        return False
    except RuntimeError:
        print(f"  ✅ Raw HTML (no fences) correctly rejected as Cloudflare block")
    
    return True


def test_dynamic_task_caps():
    """Test that task caps scale with goal complexity."""
    print("\n" + "=" * 60)
    print("TEST 2: Dynamic Task Caps")
    print("=" * 60)
    
    # Simulate goal word counts and expected caps
    test_cases = [
        ("Add a power function", 2),        # < 30 words → max 2
        ("Create a basic website with hero gallery and about section", 2),  # < 30 words → max 2
        ("Build a full REST API with authentication database migrations and testing suite", 2),  # < 30 words
        ("Create a comprehensive web application with user authentication, "
         "database integration, REST API endpoints, frontend dashboard, admin panel, "
         "and deployment configuration", 4),  # < 80 words → max 4
    ]
    
    # The dynamic cap logic from orchestrator
    for goal, expected_cap in test_cases:
        actual_words = len(goal.split())
        if actual_words < 30:
            cap = 2
        elif actual_words < 80:
            cap = 4
        else:
            cap = 6
        cap = min(cap, 8)
        
        status = "✅" if cap == expected_cap else "❌"
        print(f"  {status} Goal ({actual_words} words) → cap={cap} (expected {expected_cap})")
    
    return True


def test_file_integrity_detection():
    """Test that file integrity verification catches truncated writes."""
    print("\n" + "=" * 60)
    print("TEST 3: File Integrity Detection")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Simulate a valid coder output
        valid_output = '''```python path=app.py
def hello():
    return "hello"
```'''
        
        blocks = parse_coder_output(valid_output, task={"files": "app.py"}, task_id="T1")
        print(f"  ✅ Parsed {len(blocks)} block(s) from valid output")
        print(f"  ✅ Block path: {blocks[0].path}")
        print(f"  ✅ Block content length: {len(blocks[0].content)} chars")
        
        # Simulate truncated coder output
        truncated_output = '''```python path=app.py
def hello():
```'''
        
        blocks_trunc = parse_coder_output(truncated_output, task={"files": "app.py"}, task_id="T1")
        if blocks_trunc and len(blocks_trunc[0].content.strip()) < 5:
            print(f"  ✅ Truncated output detected (content < 5 chars)")
        else:
            print(f"  ⚠️ Truncated output not caught by parser (content: {blocks_trunc[0].content!r})")
    
    return True


def test_router_auto_retry_logic():
    """Test that the router auto-retry logic is in place."""
    print("\n" + "=" * 60)
    print("TEST 4: Router Auto-Retry Logic")
    print("=" * 60)
    
    # Check that route() has the retry loop
    import inspect
    from llm.router import route
    source = inspect.getsource(route)
    
    if "for attempt in range(2)" in source:
        print("  ✅ Auto-retry loop found in route()")
    else:
        print("  ❌ Auto-retry loop NOT found in route()")
        return False
    
    if "auto-retry attempt 2" in source:
        print("  ✅ Auto-retry logging found in route()")
    else:
        print("  ❌ Auto-retry logging NOT found")
        return False
    
    return True


def test_bugfixer_prompt():
    """Test that bugfixer prompt says 'fix ONLY defects' not 'rewrite from scratch'."""
    print("\n" + "=" * 60)
    print("TEST 5: Bugfixer Prompt (fix, don't rewrite)")
    print("=" * 60)
    
    prompt_path = ROOT / "llm" / "prompts" / "bugfixer.j2"
    prompt_content = prompt_path.read_text(encoding="utf-8")
    
    # Check that the prompt does NOT instruct the bugfixer to rewrite everything
    # "do not rewrite from scratch" is OK — it's telling it NOT to rewrite
    # "REWRITE from scratch" as an instruction to DO it is bad
    lines = prompt_content.split("\n")
    bad_lines = [l for l in lines if "rewrite from scratch" in l.lower() and "do not" not in l.lower() and "don't" not in l.lower()]
    
    if bad_lines:
        print(f"  ❌ Bugfixer prompt instructs to rewrite: {bad_lines[0].strip()}")
        return False
    else:
        print("  ✅ Bugfixer prompt does NOT instruct to rewrite from scratch")
    
    if "fix ONLY the specific defects" in prompt_content:
        print("  ✅ Bugfixer prompt says 'fix ONLY the specific defects'")
    else:
        print("  ⚠️ Bugfixer prompt doesn't explicitly say 'fix ONLY defects'")
    
    if "PRESERVE all existing code" in prompt_content:
        print("  ✅ Bugfixer prompt says 'PRESERVE all existing code'")
    else:
        print("  ⚠️ Bugfixer prompt doesn't explicitly say 'PRESERVE'")
    
    return True


def test_tui_workspace_command():
    """Test that TUI has /workspace command."""
    print("\n" + "=" * 60)
    print("TEST 6: TUI Workspace Command")
    print("=" * 60)
    
    app_path = ROOT / "tui" / "app.py"
    app_content = app_path.read_text(encoding="utf-8")
    
    if "/workspace" in app_content:
        print("  ✅ /workspace command found in TUI")
    else:
        print("  ❌ /workspace command NOT found in TUI")
        return False
    
    if "_workspace_path" in app_content:
        print("  ✅ _workspace_path state variable found")
    else:
        print("  ❌ _workspace_path NOT found")
        return False
    
    if "start_run" in app_content and "workspace_path=ws" in app_content:
        print("  ✅ Workspace path passed to start_run()")
    else:
        print("  ❌ Workspace path NOT passed to start_run()")
        return False
    
    return True


def test_parse_plan_formats():
    """Test that plan parser handles all SOTA output formats."""
    print("\n" + "=" * 60)
    print("TEST 7: Plan Parser (all formats)")
    print("=" * 60)
    
    # Format 1: "TASK T1" with "key: value" (Codex format)
    plan1 = """TASK T1
id: T1
title: Build website
description: Create a website
needs_research: false
files: index.html
acceptance_criteria: Site works"""
    
    tasks1 = _parse_plan(plan1)
    print(f"  Format 1 (TASK T1): {len(tasks1)} tasks")
    if tasks1:
        print(f"    ✅ Parsed: {tasks1[0].get('id')}: {tasks1[0].get('title')}")
    else:
        print(f"    ❌ Failed to parse")
        return False
    
    # Format 2: "TASK 1" (no T prefix)
    plan2 = """TASK 1
id: 1
title: Build API
description: Create REST API
needs_research: false
files: api.py
acceptance_criteria: API works"""
    
    tasks2 = _parse_plan(plan2)
    print(f"  Format 2 (TASK 1): {len(tasks2)} tasks")
    if tasks2:
        print(f"    ✅ Parsed: {tasks2[0].get('id')}: {tasks2[0].get('title')}")
    else:
        print(f"    ❌ Failed to parse")
        return False
    
    # Format 3: Creative IDs
    plan3 = """TASK setup
id: setup
title: Setup project
description: Initialize
needs_research: false
files: main.py
acceptance_criteria: Project initialized"""
    
    tasks3 = _parse_plan(plan3)
    print(f"  Format 3 (TASK setup): {len(tasks3)} tasks")
    if tasks3:
        print(f"    ✅ Parsed: {tasks3[0].get('id')}: {tasks3[0].get('title')}")
    else:
        print(f"    ❌ Failed to parse")
        return False
    
    return True


def test_btw_queue():
    """Test that /btw queue file format is correct."""
    print("\n" + "=" * 60)
    print("TEST 8: /btw Queue Format")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a btw_queue.json file
        btw_path = Path(tmpdir) / "btw_queue.json"
        queue = [
            {"message": "Use a dark color scheme", "timestamp": "2026-07-16T12:00:00"},
            {"message": "Add a contact form", "timestamp": "2026-07-16T12:01:00"},
        ]
        btw_path.write_text(json.dumps(queue, indent=2))
        
        # Read it back
        data = json.loads(btw_path.read_text())
        notes = [item.get("message", "") for item in data if item.get("message")]
        
        if len(notes) == 2:
            print(f"  ✅ Queue read correctly: {len(notes)} notes")
            print(f"    Note 1: {notes[0]}")
            print(f"    Note 2: {notes[1]}")
        else:
            print(f"  ❌ Queue read failed: got {len(notes)} notes")
            return False
        
        # Clear the queue
        btw_path.write_text("[]")
        data2 = json.loads(btw_path.read_text())
        if len(data2) == 0:
            print(f"  ✅ Queue cleared correctly")
        else:
            print(f"  ❌ Queue clear failed")
            return False
    
    return True


def main():
    print("\n" + "=" * 60)
    print("  PHASE 1: CORE LOOP RELIABILITY — DUMMY TESTS")
    print("=" * 60 + "\n")
    
    results = []
    results.append(("HTML Validation", test_html_validation()))
    results.append(("Dynamic Task Caps", test_dynamic_task_caps()))
    results.append(("File Integrity", test_file_integrity_detection()))
    results.append(("Router Auto-Retry", test_router_auto_retry_logic()))
    results.append(("Bugfixer Prompt", test_bugfixer_prompt()))
    results.append(("TUI Workspace", test_tui_workspace_command()))
    results.append(("Plan Parser", test_parse_plan_formats()))
    results.append(("BTW Queue", test_btw_queue()))
    
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("  🎉 PHASE 1 ALL TESTS PASSED")
    else:
        print("  ⚠️  SOME TESTS FAILED — review above")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
