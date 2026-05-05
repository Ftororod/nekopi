"""Submenú TOOLS."""

from screens.submenu import render_submenu


def render(ctx):
    return render_submenu(ctx, "tools", "TOOLS")
