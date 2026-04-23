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
# User-configured helper values are never overwritten on update.
# =============================================================================

set -e

# Mode: "full" (default) runs pip installs. "sync" just copies files.
MODE=${1:-full}

SRC=/config/custom_components/amber_integration
CONFIG=/config/configuration.yaml
ERRORS=0

echo "============================================="
echo " Home Assistant Custom Amber Electric"
echo " Integration - Install Script"
echo "============================================="
echo ""

if [ "$MODE" = "full" ]; then
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

    # Install pycognito
    echo "🐍 Installing pycognito..."
    pip3 install pycognito --break-system-packages
    echo ""
else
    echo "⚡ Sync mode — skipping python/pip checks"
    echo ""
fi

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
# Load HA credentials — needed for all API calls below
# -----------------------------------------------------------------------------
SECRETS=/config/secrets.yaml
HA_URL=$(grep "^ha_url:" $SECRETS 2>/dev/null | sed 's/ha_url: *//' | tr -d '"' || echo "http://localhost:8123")
HA_TOKEN=$(grep "^ha_long_lived_token:" $SECRETS 2>/dev/null | sed 's/ha_long_lived_token: *//' | tr -d '"')

if [ -z "$HA_TOKEN" ]; then
    echo ""
    echo "⚠️  ha_long_lived_token not found in secrets.yaml"
    echo "   Skipping helper configuration — run install.sh again after adding your token."
fi

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

get_state() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "" && return
    curl -s \
        "$HA_URL/api/states/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo ""
}

set_number_if_default() {
    local entity_id=$1
    local default_value=$2
    local description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_number/set_value" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\", \"value\": $default_value}"
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_datetime_if_default() {
    local entity_id=$1
    local default_value=$2
    local description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_datetime/set_datetime" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\", \"time\": \"$default_value\"}"
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_boolean_off_if_new() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_boolean/turn_off" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\"}"
        echo "   ✅ OFF: $entity_id (first install default)"
    else
        echo "   ⏭️  $entity_id already $current — keeping user value"
    fi
}

hide_entity() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    result=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
        "$HA_URL/api/config/entity_registry/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"hidden_by": "user"}')
    if [ "$result" = "200" ]; then
        echo "   ✅ Hidden: $entity_id"
    else
        echo "   ⚠️  Could not hide $entity_id (HTTP $result)"
    fi
}

# -----------------------------------------------------------------------------
# Set automation enable booleans to OFF (first install only)
# -----------------------------------------------------------------------------
echo ""
echo "🔧 Setting automation enable booleans..."
set_boolean_off_if_new "input_boolean.amber_enable_block_smart_shift"
set_boolean_off_if_new "input_boolean.amber_enable_charge_on_negative_buy"
set_boolean_off_if_new "input_boolean.amber_enable_force_export_custom_fit"
set_boolean_off_if_new "input_boolean.amber_enable_negative_price_notify"

# Force export notifications default ON
set_boolean_on_if_new() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_boolean/turn_on" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\"}"
        echo "   ✅ ON: $entity_id (first install default)"
    else
        echo "   ⏭️  $entity_id already $current — keeping user value"
    fi
}
set_boolean_on_if_new "input_boolean.amber_enable_force_export_notify"

# -----------------------------------------------------------------------------
# Set default values for configurable helpers (first install only)
# On HACS updates these are skipped — user values are preserved
# -----------------------------------------------------------------------------
echo ""
echo "🔧 Setting default values for configurable helpers..."
set_number_if_default   "input_number.amber_min_sell_price"                  0.15     "Min Sell Price"
set_number_if_default   "input_number.amber_min_soc_to_sell"                 10       "Min SOC to Sell"
set_datetime_if_default "input_datetime.amber_charge_on_negative_start"      "10:00:00" "Charge on Negative Start"
set_datetime_if_default "input_datetime.amber_charge_on_negative_end"        "17:00:00" "Charge on Negative End"
set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_start" "16:00:00" "Force Sell Start"
set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_end"  "06:00:00" "Force Sell End"
set_datetime_if_default "input_datetime.amber_block_smart_shift_start"       "00:00:00" "Block Smart Shift Start"
set_datetime_if_default "input_datetime.amber_block_smart_shift_end"         "06:00:00" "Block Smart Shift End"

# -----------------------------------------------------------------------------
# Hide internal state flag helpers from the HA UI
# -----------------------------------------------------------------------------
echo ""
echo "🙈 Hiding internal state flag helpers..."
hide_entity "input_boolean.amber_grid_charging_active"
hide_entity "input_boolean.amber_block_smart_shift_active"
hide_entity "input_boolean.amber_force_export_active"
hide_entity "input_boolean.amber_battery_offline"

echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

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
    echo " ⚡ Future HACS updates will run this script automatically"
    echo "    via the amber_hacs_auto_install automation."
else
    echo " ⚠️  Install complete with $ERRORS warning(s) above."
    echo ""
    echo " Fix the configuration.yaml issues listed above,"
    echo " then restart HA: Settings → System → Restart"
fi

echo "============================================="
