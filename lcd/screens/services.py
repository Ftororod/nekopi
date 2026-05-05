"""Submenú SERVICES."""

from screens.submenu import render_submenu


def render(ctx):
    return render_submenu(ctx, "services", "SERVICES")
