"""
File Tree Browser — shows workspace files in a tree view.

Uses Textual's DirectoryTree widget to show the file structure
of the current workspace or worktree.
"""
from __future__ import annotations

from pathlib import Path
from textual.widgets import Static, Tree, DirectoryTree
from textual.containers import Vertical


class FileTreePanel(Vertical):
    """Panel showing workspace file tree."""

    DEFAULT_CSS = """
    FileTreePanel {
        width: 1fr;
        border: solid $surface;
        padding: 0;
    }
    FileTreePanel > .panel-title {
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    FileTreePanel > DirectoryTree {
        padding: 0 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._title = Static("  Files", classes="panel-title")
        self._tree: DirectoryTree | None = None
        self._current_path: str | None = None

    def compose(self):
        yield self._title
        # Placeholder until workspace is set
        yield Static("[dim]No workspace selected[/dim]", id="tree-placeholder")

    def update_workspace(self, workspace_path: str) -> None:
        """Update the file tree with a new workspace path."""
        if workspace_path == self._current_path:
            return  # Already showing this path

        self._current_path = workspace_path
        path = Path(workspace_path)
        if not path.exists():
            return

        # Remove placeholder or old tree
        try:
            self.query_one("#tree-placeholder", Static).remove()
        except Exception:
            pass
        if self._tree:
            self._tree.remove()

        # Create new directory tree
        self._tree = DirectoryTree(
            path=str(path),
            id="file-tree",
        )
        # Filter out hidden dirs and common ignores
        self._tree.filter_dirs = lambda p: not (
            p.name.startswith(".")
            or p.name == "__pycache__"
            or p.name == "node_modules"
            or p.name == ".venv"
            or p.name == ".worktrees"
        )
        self.mount(self._tree)
