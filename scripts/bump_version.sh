#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# NekoPi Field Unit — version bump helper
#
# Usage: ./scripts/bump_version.sh 1.4.0 "NuevoCodename"
#
# Updates the VERSION file (single source of truth for backend + installer)
# and the hardcoded references in the static landing page. The UI (ui/index.html),
# backend (api/main.py), and installer (build_installer_v2.py) all read
# VERSION at runtime, so no edits are needed there.

set -e

NEW_VERSION="$1"
NEW_CODENAME="$2"

if [ -z "$NEW_VERSION" ] || [ -z "$NEW_CODENAME" ]; then
    echo "Usage: $0 <version> <codename>"
    echo "Example: $0 1.4.0 Pelusa"
    exit 1
fi

# Resolve repo root relative to this script so it works from any CWD.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Update VERSION file — single source of truth
echo "$NEW_VERSION"  >  VERSION
echo "$NEW_CODENAME" >> VERSION

# Update landing-page header comment (GitHub Pages, cannot read VERSION at runtime)
sed -i "s|VERSION: .* | CODENAME: .*|VERSION: $NEW_VERSION | CODENAME: $NEW_CODENAME|" index.html || true

# Update demo.html static marketing content
sed -i "s/v[0-9]\+\.[0-9]\+\.[0-9]\+/v$NEW_VERSION/g" ui/demo.html

echo "✅ Version bumped to $NEW_VERSION ($NEW_CODENAME)"
echo "   Backend, frontend About, and installer read VERSION file automatically."
echo "   Review index.html manually — the nav logo subtitle and footer also"
echo "   carry a short version string (e.g. 'v1.3') that sed cannot safely"
echo "   rewrite without risking false matches."
echo ""
echo "Next steps:"
echo "  git add VERSION index.html ui/demo.html"
echo "  git commit -m \"chore: bump version to $NEW_VERSION ($NEW_CODENAME)\""
echo "  git tag v$NEW_VERSION"
echo "  git push && git push --tags"
