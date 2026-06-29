"""
DAG — task graph for the orchestrator.

A DAG is loaded from config/workflow.yaml. Nodes are either:
  - agent nodes (invoke an agent with bounded context)
  - hitl nodes (pause until state/hitl/{gate}.json says approved)
  - branch nodes (read a status field, route to next)
  - terminal nodes (done)

This module is pure data + topology. Execution lives in orchestrator.py.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class Node:
    id: str
    kind: str  # "agent" | "hitl" | "branch" | "terminal"
    agent: str | None = None
    gate: str | None = None
    next: str | None = None
    if_approved: str | None = None
    if_rejected: str | None = None


@dataclass
class DAG:
    nodes: dict[str, Node] = field(default_factory=dict)
    entry: str = "thinker"
    max_review_iterations: int = 3
    max_tasks_per_goal: int = 2
    conditional_agents: list[dict[str, Any]] = field(default_factory=list)
    target_repo: str = "./target_repo"

    @classmethod
    def from_yaml(cls, path: str) -> "DAG":
        with open(path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        # Expand ${ENV_VAR:default} in target_repo
        target_repo_raw = spec.get("target_repo", "./target_repo")
        target_repo = _expand_env(target_repo_raw)
        dag = cls(
            max_review_iterations=spec.get("max_review_iterations", 3),
            max_tasks_per_goal=spec.get("max_tasks_per_goal", 2),
            conditional_agents=spec.get("conditional_agents", []),
            target_repo=target_repo,
        )
        for n_spec in spec["dag"]:
            kind = "agent"
            if n_spec.get("type") == "hitl":
                kind = "hitl"
            elif n_spec.get("type") == "branch":
                kind = "branch"
            elif n_spec.get("type") == "terminal":
                kind = "terminal"
            node = Node(
                id=n_spec["id"],
                kind=kind,
                agent=n_spec.get("agent"),
                gate=n_spec.get("gate"),
                next=n_spec.get("next"),
                if_approved=n_spec.get("if_approved"),
                if_rejected=n_spec.get("if_rejected"),
            )
            dag.nodes[node.id] = node
        # Entry point = first node in the list
        dag.entry = spec["dag"][0]["id"]
        return dag

    def next_node(self, current_id: str, branch_decision: str | None = None) -> Node | None:
        node = self.nodes[current_id]
        if node.kind == "branch":
            if branch_decision == "approved" and node.if_approved:
                return self.nodes.get(node.if_approved)
            if branch_decision == "rejected" and node.if_rejected:
                return self.nodes.get(node.if_rejected)
            return None
        if node.next:
            return self.nodes.get(node.next)
        return None


_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):([^}]*)\}")


def _expand_env(value: str) -> str:
    """Expand ${VAR:default} -> os.environ.get('VAR', default)."""
    def repl(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default)
    return _ENV_RE.sub(repl, value)
