"""
Permission classifier for terminal commands.

Classifies shell commands into SAFE / MODERATE / DANGEROUS based on:
  - Whitelist of allowed commands (git, pytest, ruff, python, etc.)
  - Destructive pattern detection (rm, --force, --hard, sudo, etc.)
  - Path scope check (commands must operate within workspace)

This is the "defense in depth" layer:
  1. Worktree isolation (git worktrees — already have)
  2. Command whitelist (this module)
  3. Destructive pattern detection (this module)
  4. HITL approval for DANGEROUS (ToolRegistry._check_dangerous_approval)
"""
from __future__ import annotations

import re
import shlex
from typing import Literal

from tools.base import ToolPermission

# Commands that are always allowed (read-only or safe write operations)
SAFE_COMMANDS = {
    # File inspection
    "ls", "cat", "head", "tail", "wc", "file", "stat", "tree",
    "find", "which", "whereis", "locate",
    # Code tools
    "python", "python3", "pip", "pip3", "pytest", "ruff", "mypy",
    "pylint", "flake8", "black", "isort", "mypy",
    # Git (read-only)
    "git",  # git is MODERATE generally, but read subcommands are SAFE
    # Text processing
    "grep", "rg", "sed", "awk", "cut", "sort", "uniq", "diff",
    "jq", "yq",
    # Archive (read-only)
    "tar", "unzip", "gzip", "gunzip",
    # Network (read-only — for downloading deps)
    "curl", "wget",
    # Process
    "ps", "top", "htop", "kill",  # kill is MODERATE
    # System info
    "uname", "whoami", "hostname", "env", "echo", "printf",
    # Package managers (read-only queries)
    "npm", "npx", "yarn", "pnpm",  # could install — MODERATE for install
}

# Commands that modify the filesystem (MODERATE — allowed in worktree)
MODERATE_COMMANDS = {
    "mkdir", "touch", "cp", "mv",  # cp/mv can be destructive — check patterns
    "pip", "pip3", "npm", "npx", "yarn", "pnpm",  # install subcommand
}

# Commands that are NEVER allowed (always DANGEROUS or blocked)
BLOCKED_COMMANDS = {
    "sudo", "su", "chmod", "chown", "chgrp",
    "dd", "mkfs", "fdisk", "mount", "umount",
    "systemctl", "service", "shutdown", "reboot",
    "crontab", "at",
    "ssh", "scp", "rsync",  # network operations — too risky for automation
    "docker",  # docker is handled by separate Docker tools (v3)
    "kubectl",  # k8s is handled by separate K8s tools (v3)
}

# Patterns that make any command DANGEROUS
DESTRUCTIVE_PATTERNS = [
    r"\brm\b",           # remove
    r"\brmdir\b",        # remove directory
    r"--force\b",        # force flag
    r"--hard\b",         # hard reset
    r"-rf\b",            # rm -rf
    r"-fr\b",            # rm -fr
    r"\bformat\b",       # format
    r">\s*/dev/",        # redirect to device
    r"\bsudo\b",         # privilege escalation
    r"\bkill\s+-9\b",    # force kill
    r"\bkillall\b",      # kill all
    r"\bpkill\b",        # process kill
    r"\biotop\b",        # disk monitoring (root)
    r"\bnmap\b",         # network scanner
    r"\bifconfig\b",     # network config
    r"\biptables\b",     # firewall
    r"\bexport\b",       # environment variable (can mess up shell)
]

# Git subcommands that are SAFE (read-only)
GIT_SAFE_SUBCOMMANDS = {
    "status", "diff", "log", "show", "branch", "blame",
    "remote", "stash list", "reflog", "describe", "shortlog",
    "ls-files", "ls-tree", "rev-parse", "config --get",
}

# Git subcommands that are MODERATE (modify repo state)
GIT_MODERATE_SUBCOMMANDS = {
    "add", "commit", "stash", "stash pop", "stash drop",
    "checkout -b", "switch", "restore", "reset --soft",
    "merge", "rebase", "cherry-pick", "tag",
}

# Git subcommands that are DANGEROUS
GIT_DANGEROUS_SUBCOMMANDS = {
    "reset --hard", "clean", "push --force", "push -f",
    "checkout .", "checkout --", "branch -D",
}


def classify_command(command: str) -> ToolPermission:
    """Classify a shell command into a permission level.
    
    Args:
        command: The full shell command string (e.g. "git status" or "rm foo.py")
    
    Returns:
        ToolPermission.SAFE: read-only, always execute
        ToolPermission.MODERATE: writes within workspace, log
        ToolPermission.DANGEROUS: destructive, requires HITL approval
    """
    if not command or not command.strip():
        return ToolPermission.SAFE  # empty command — no-op

    command = command.strip()
    lower = command.lower()

    # Check destructive patterns first (highest priority)
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, lower):
            return ToolPermission.DANGEROUS

    # Parse the command
    try:
        parts = shlex.split(command)
    except ValueError:
        # Unparseable command — treat as dangerous
        return ToolPermission.DANGEROUS

    if not parts:
        return ToolPermission.SAFE

    base_cmd = parts[0]

    # Check blocked commands
    if base_cmd in BLOCKED_COMMANDS:
        return ToolPermission.DANGEROUS

    # Special handling for git
    if base_cmd == "git":
        return _classify_git(command, parts)

    # Check if command is in safe list
    if base_cmd in SAFE_COMMANDS:
        # Even safe commands can be dangerous with certain flags
        for pattern in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, lower):
                return ToolPermission.DANGEROUS
        # Special case: pip/npm/yarn install is MODERATE (modifies environment)
        if base_cmd in ("pip", "pip3", "npm", "npx", "yarn", "pnpm"):
            if len(parts) > 1 and parts[1] in ("install", "uninstall", "remove",
                                                "update", "upgrade", "i", "add",
                                                "rm", "un"):
                return ToolPermission.MODERATE
        return ToolPermission.SAFE

    # Check if command is in moderate list
    if base_cmd in MODERATE_COMMANDS:
        return ToolPermission.MODERATE

    # Unknown command — treat as dangerous for safety
    return ToolPermission.DANGEROUS


def _classify_git(command: str, parts: list[str]) -> ToolPermission:
    """Classify a git command based on its subcommand."""
    if len(parts) < 2:
        return ToolPermission.SAFE  # just "git" — no-op

    subcommand = " ".join(parts[1:3])  # e.g. "stash", "stash list"
    subcommand_single = parts[1]

    # Check dangerous git subcommands
    for dangerous in GIT_DANGEROUS_SUBCOMMANDS:
        if dangerous in command.lower():
            return ToolPermission.DANGEROUS

    # Check moderate git subcommands
    for moderate in GIT_MODERATE_SUBCOMMANDS:
        if moderate in command.lower():
            return ToolPermission.MODERATE

    # Check safe git subcommands
    for safe in GIT_SAFE_SUBCOMMANDS:
        if safe in command.lower():
            return ToolPermission.SAFE

    # Default: git commit, git add, etc. are MODERATE
    if subcommand_single in ("add", "commit", "stash", "checkout", "switch",
                              "restore", "merge", "rebase", "cherry-pick",
                              "tag", "reset"):
        return ToolPermission.MODERATE

    # Unknown git subcommand — moderate
    return ToolPermission.MODERATE


def is_path_safe(path: str, workspace: str) -> bool:
    """Check if a path is within the workspace.
    
    Used by terminal.execute to validate paths passed as arguments.
    """
    from pathlib import Path
    try:
        p = Path(path).resolve()
        w = Path(workspace).resolve()
        return w in p.parents or p == w
    except Exception:
        return False
