#!/bin/bash
# =============================================================================
# Home Assistant Custom Amber Electric Integration - Install Script
# =============================================================================
#
# Run this after every HACS install or update to copy integration files
# into their correct /config/ locations.
#
# Usage:
#   bash /config/custom_components/amber_integration/install.sh
#
# Safe to re-run — existing files are overwritten, nothing is deleted.
# =============================================================================

set -e

SRC=/config/custom_components/amber_integration
echo "Installing Home Assistant Custom Amber Electric Integration..."
echo "Source: $SRC"
echo ""

# Automations
echo "Copying automations..."
mkdir -p /config/automations
cp -v $SRC/automations/*.yaml /config/automations/

# Scripts
echo ""
echo "Copying scripts..."
mkdir -p /config/scripts
cp -v $SRC/scripts/*.py /config/scripts/

# Package (config helpers, shell commands, notify)
echo ""
echo "Copying package..."
mkdir -p /config/packages
cp -v $SRC/packages/amber.yaml /config/packages/

# Templates
echo ""
echo "Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/amber.yaml /config/templates/

echo ""
echo "✅ Done! Files copied to /config/"
echo ""
echo "⚡ Future HACS updates will run this script automatically via the"
echo "   amber_hacs_auto_install automation."
echo ""
echo "Next steps:"
echo "  1. Ensure configuration.yaml has: homeassistant: packages: !include_dir_named packages/"
echo "  2. Reload: Developer Tools → YAML → Reload All"
echo "  3. Or restart HA: Settings → System → Restart"
