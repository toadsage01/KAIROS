"""
Plugin System — extensible architecture for Kairos TUI.

Plugins can:
  - Add custom panels to the TUI layout
  - Add slash commands
  - Add keyboard shortcuts
  - Hook into agent events (before/after run, on tool call, etc.)

Based on the CloudCLI plugin architecture pattern.

Usage:
    from tui.plugins import BasePlugin, PluginContext

    class MyPlugin(BasePlugin):
        name = "my_plugin"
        version = "1.0.0"

        def get_commands(self):
            return {
                "/mycommand": self.handle_command,
            }

        def get_panel(self):
            return MyCustomPanel()

        def on_agent_event(self, event: str, data: dict):
            if event == "tool_called":
                print(f"Tool used: {data.get('tool_name')}")
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class PluginContext:
    """Context passed to plugins for initialization."""
    api_url: str = "http://localhost:8000"
    workspace_path: str | None = None
    state: dict | None = None


class BasePlugin(ABC):
    """Base class for all Kairos TUI plugins.

    Subclasses can override any of these methods:
      - get_commands(): Return {"/command": handler} dict
      - get_panel(): Return a Textual widget to add as a panel
      - get_bindings(): Return list of (key, action_name, description)
      - on_agent_event(): Hook called on agent state changes
      - on_startup(): Called when TUI starts
      - on_shutdown(): Called when TUI exits
    """

    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx

    def get_commands(self) -> dict[str, Callable]:
        """Return slash commands this plugin provides.

        Returns:
            Dict mapping "/command" to a callable handler.
            Handler receives (app, args: str) -> None
        """
        return {}

    def get_panel(self) -> Any | None:
        """Return a Textual widget to add as a panel, or None.

        The widget will be added to the main content area.
        """
        return None

    def get_bindings(self) -> list[tuple[str, str, str]]:
        """Return keyboard shortcuts.

        Returns:
            List of (key, action_name, description) tuples.
            Example: [("ctrl+p", "my_action", "My Action")]
        """
        return []

    def on_agent_event(self, event: str, data: dict) -> None:
        """Hook called when agent state changes.

        Events:
          - "run_started": data = {goal, workspace}
          - "run_paused": data = {gate, plan}
          - "run_resumed": data = {gate, decision}
          - "run_completed": data = {tasks_count}
          - "run_error": data = {error}
          - "agent_started": data = {agent, task_id}
          - "agent_completed": data = {agent, task_id, output_path}
          - "tool_called": data = {tool, args, result}
          - "model_fallback": data = {agent, failed_model, next_model}
        """
        pass

    def on_startup(self) -> None:
        """Called when the TUI starts and plugin is loaded."""
        pass

    def on_shutdown(self) -> None:
        """Called when the TUI exits."""
        pass


class PluginManager:
    """Manages plugin lifecycle.

    Plugins are loaded from:
    1. Built-in plugins (in tui/plugins/)
    2. User plugins (in ~/.kairos/plugins/)

    Each plugin is a Python file that defines a class extending BasePlugin.
    """

    def __init__(self):
        self._plugins: list[BasePlugin] = []
        self._commands: dict[str, tuple[BasePlugin, Callable]] = {}
        self._panels: list[Any] = []
        self._bindings: list[tuple[str, str, str]] = []

    def load_plugin(self, plugin: BasePlugin) -> None:
        """Load and register a plugin."""
        self._plugins.append(plugin)
        plugin.on_startup()

        # Register commands
        commands = plugin.get_commands()
        for cmd, handler in commands.items():
            self._commands[cmd] = (plugin, handler)

        # Register panel
        panel = plugin.get_panel()
        if panel is not None:
            self._panels.append(panel)

        # Register bindings
        bindings = plugin.get_bindings()
        self._bindings.extend(bindings)

    def get_command(self, command: str) -> tuple[BasePlugin, Callable] | None:
        """Look up a command handler."""
        return self._commands.get(command)

    def get_all_commands(self) -> list[str]:
        """List all registered commands."""
        return sorted(self._commands.keys())

    def get_panels(self) -> list[Any]:
        """Return all plugin panels."""
        return self._panels

    def get_bindings(self) -> list[tuple[str, str, str]]:
        """Return all plugin keyboard bindings."""
        return self._bindings

    def broadcast_event(self, event: str, data: dict) -> None:
        """Send an event to all plugins."""
        for plugin in self._plugins:
            try:
                plugin.on_agent_event(event, data)
            except Exception:
                pass  # Plugins shouldn't crash the TUI

    def shutdown(self) -> None:
        """Shutdown all plugins."""
        for plugin in self._plugins:
            try:
                plugin.on_shutdown()
            except Exception:
                pass


# Singleton
_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
