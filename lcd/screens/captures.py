"""Submenú CAPTURES."""

from screens.submenu import render_submenu


def render(ctx):
    return render_submenu(ctx, "captures", "CAPTURES")
