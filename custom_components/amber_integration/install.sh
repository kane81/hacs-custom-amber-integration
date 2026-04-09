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
CONFIG=/config/configuration.yaml
ERRORS=0

echo "============================================="
echo " Home Assistant Custom Amber Electric"
echo " Integration - Install Script"
echo "============================================="
echo ""

# Ensure python3 is available
echo "🔍 Checking python3..."
if ! command -v python3 &>/dev/null; then
    echo "   python3 not found, installing..."
    apk add python3
fi
echo "   python3 $(python3 --version)"

# Ensure pip3 is available
echo "🔍 Checking pip3..."
if ! command -v pip3 &>/dev/null; then
    echo "   pip3 not found, installing..."
    apk add py3-pip
fi
echo "   pip3 found"
echo ""

# Install pycognito Python dependency
echo "🐍 Installing pycognito..."
pip3 install pycognito --break-system-packages
echo ""

# Automations
echo "📋 Copying automations..."
mkdir -p /config/automations
cp -v $SRC/automations/*.yaml /config/automations/

# Scripts
echo ""
echo "🐍 Copying scripts..."
mkdir -p /config/scripts
cp -v $SRC/scripts/*.py /config/scripts/

# Package
echo ""
echo "📦 Copying package..."
mkdir -p /config/packages
cp -v $SRC/packages/amber.yaml /config/packages/

# Templates
echo ""
echo "📄 Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/amber.yaml /config/templates/

echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

# Check automation dir merge line
if grep -q "include_dir_merge_list automations" $CONFIG; then
    echo "✅ automation: !include_dir_merge_list automations/ — found"
else
    echo "⚠️  MISSING — automation directory not configured!"
    echo ""
    echo "   Add this line to $CONFIG:"
    echo "   automation: !include_dir_merge_list automations/"
    echo ""
    echo "   If you already have 'automation: !include automations.yaml'"
    echo "   replace that line with the one above."
    ERRORS=$((ERRORS + 1))
fi

# Check packages line
if grep -q "include_dir_named packages" $CONFIG; then
    echo "✅ packages: !include_dir_named packages/ — found"
else
    echo "⚠️  MISSING — packages directory not configured!"
    echo ""
    echo "   Add these lines to $CONFIG under homeassistant::"
    echo "   homeassistant:"
    echo "     packages: !include_dir_named packages/"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "============================================="

if [ $ERRORS -eq 0 ]; then
    echo " ✅ Install complete!"
    echo ""
    echo " Reload HA config to apply changes:"
    echo " Developer Tools → YAML → Reload All"
    echo ""
    echo " ⚡ Future HACS updates will run this script"
    echo "    automatically via amber_hacs_auto_install."
else
    echo " ⚠️  Install complete with $ERRORS warning(s) above."
    echo ""
    echo " Fix the configuration.yaml issues listed above,"
    echo " then restart HA: Settings → System → Restart"
fi

echo "============================================="
