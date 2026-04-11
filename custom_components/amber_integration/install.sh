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


# -----------------------------------------------------------------------------
# Hide internal state flag helpers from the HA UI
# These are set/cleared by automations and should not be toggled manually.
# Hiding prevents user confusion — they still work, just not visible in Helpers.
# -----------------------------------------------------------------------------
echo ""
echo "🙈 Hiding internal state flag helpers..."

SECRETS=/config/secrets.yaml
HA_URL=$(grep "^ha_url:" $SECRETS 2>/dev/null | sed 's/ha_url: *//' | tr -d '"' || echo "http://localhost:8123")
HA_TOKEN=$(grep "^ha_long_lived_token:" $SECRETS | sed 's/ha_long_lived_token: *//' | tr -d '"')

if [ -z "$HA_TOKEN" ]; then
    echo "   ⚠️  ha_long_lived_token not found in secrets.yaml — skipping auto-hide"
    echo "   You can hide these manually via Settings → Entities → search → Hidden toggle:"
fi

hide_entity() {
    local entity_id=$1
    if [ -z "$HA_TOKEN" ]; then
        echo "   - $entity_id"
        return
    fi
    result=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
        "$HA_URL/api/config/entity_registry/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"hidden_by": "user"}')
    if [ "$result" = "200" ]; then
        echo "   ✅ Hidden: $entity_id"
    else
        echo "   ⚠️  Could not hide $entity_id (HTTP $result) — hide manually if needed"
    fi
}
hide_entity "input_boolean.amber_grid_charging_active"
hide_entity "input_boolean.amber_block_smart_shift_active"
hide_entity "input_boolean.amber_force_export_active"
hide_entity "input_boolean.amber_battery_offline"

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
