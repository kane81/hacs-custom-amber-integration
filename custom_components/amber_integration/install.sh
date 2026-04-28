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
# -----------------------------------------------------------------------------
# Remove deprecated files from previous versions
# -----------------------------------------------------------------------------
echo ""
echo "🧹 Removing deprecated files..."
DEPRECATED=(
    "/config/automations/amber_charge_on_negative_buy.yaml"
)
for f in "${DEPRECATED[@]}"; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "   ✅ Removed: $f"
    fi
done

# Prompt for credentials and load HA credentials
# -----------------------------------------------------------------------------
SECRETS=/config/secrets.yaml
touch $SECRETS

prompt_if_missing() {
    local key=$1
    local label=$2
    if ! grep -q "^${key}:" $SECRETS; then
        echo ""
        echo -n "   Enter $label: "
        read -r value
        if [ -n "$value" ]; then
            echo "${key}: "${value}"" >> $SECRETS
            echo "   ✅ ${key} saved to secrets.yaml"
        else
            echo "   ⚠️  Skipped — add ${key} to secrets.yaml manually later"
        fi
    else
        echo "   ⏭️  ${key} already set — skipping"
    fi
}

echo ""
echo "🔑 Checking credentials in secrets.yaml..."
prompt_if_missing "amber_email"         "Amber Electric login email"
prompt_if_missing "amber_password"      "Amber Electric login password"
prompt_if_missing "ha_long_lived_token" "HA Long-Lived Access Token (Profile → Long-Lived Access Tokens → Create Token)"
if ! grep -q "^ha_url:" $SECRETS; then
    echo "ha_url: "http://localhost:8123"" >> $SECRETS
    echo "   ✅ ha_url set to http://localhost:8123 (default)"
fi

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
set_boolean_off_if_new "input_boolean.amber_enable_force_export_custom_fit"
set_boolean_off_if_new "input_boolean.amber_enable_negative_price_notify"
set_boolean_off_if_new "input_boolean.amber_enable_force_charge_custom_rate"

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
# Set default values for configurable helpers (first install / full mode only)
# Skipped on startup sync to avoid overwriting user values during HA boot
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    # Reload HA YAML config so helpers are created before we try to set defaults
    if [ -n "$HA_TOKEN" ]; then
        echo ""
        echo "🔄 Reloading HA YAML config so helpers are available..."
        curl -s -o /dev/null -X POST             "$HA_URL/api/services/homeassistant/reload_all"             -H "Authorization: Bearer $HA_TOKEN"             -H "Content-Type: application/json"
        echo "   Waiting 10 seconds for helpers to initialise..."
        sleep 10
        echo "   ✅ Done"
    fi

echo ""
echo "🔧 Setting default values for configurable helpers..."
set_number_if_default   "input_number.amber_min_sell_price"                  0.15     "Min Sell Price"
set_number_if_default   "input_number.amber_min_soc_to_sell"                 10       "Min SOC to Sell"
set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_start" "16:00:00" "Force Sell Start"
set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_end"  "06:00:00" "Force Sell End"
set_datetime_if_default "input_datetime.amber_block_smart_shift_start"       "00:00:00" "Block Smart Shift Start"
set_datetime_if_default "input_datetime.amber_block_smart_shift_end"         "06:00:00" "Block Smart Shift End"
set_number_if_default   "input_number.amber_max_buy_price_to_charge"         0.05       "Max Buy Price"
set_number_if_default   "input_number.amber_max_soc_to_charge"               100        "Max SOC to Charge"
set_datetime_if_default "input_datetime.amber_force_charge_start"            "11:00:00" "Force Charge Start"
set_datetime_if_default "input_datetime.amber_force_charge_end"              "13:00:00" "Force Charge End"

fi  # end MODE=full

# -----------------------------------------------------------------------------
# Hide internal state flag helpers from the HA UI
# -----------------------------------------------------------------------------
echo ""
echo "🙈 Hiding internal state flag helpers..."
hide_entity "input_boolean.amber_block_smart_shift_active"
hide_entity "input_boolean.amber_force_export_active"
hide_entity "input_boolean.amber_battery_offline"


# -----------------------------------------------------------------------------
# Offer to install the dashboard card automatically
# -----------------------------------------------------------------------------
if [ -n "$HA_TOKEN" ] && [ "$MODE" = "full" ]; then
    echo ""
    echo "📊 Dashboard Card"
    echo ""
    echo "   Would you like to automatically add the Amber dashboard card"
    echo "   to your default Overview dashboard?"
    echo ""
    read -r -p "   Add dashboard card now? (Y/n): " add_card
    if [[ ! "$add_card" =~ ^[Nn]$ ]]; then
        CARD_FILE="$SRC/dashboard_card.txt"
        if [ -f "$CARD_FILE" ]; then
            CARD_CONTENT=$(cat "$CARD_FILE")
            # Escape for JSON
            CARD_JSON=$(python3 -c "
import json, sys
content = open('$CARD_FILE').read()
card = {'type': 'markdown', 'content': content}
print(json.dumps(card))
")
            # Get current lovelace config
            LOVELACE=$(curl -s "$HA_URL/api/lovelace/config"                 -H "Authorization: Bearer $HA_TOKEN")

            # Add card via Python to handle JSON safely
            result=$(python3 << PYEOF
import json, urllib.request, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

try:
    # Get current config
    req = urllib.request.Request(
        "$HA_URL/api/lovelace/config",
        headers={"Authorization": "Bearer $HA_TOKEN"}
    )
    with urllib.request.urlopen(req, context=ctx) as r:
        config = json.loads(r.read())

    # Add card to first view
    card = {"type": "markdown", "content": open("$CARD_FILE").read()}
    if "views" in config and len(config["views"]) > 0:
        if "cards" not in config["views"][0]:
            config["views"][0]["cards"] = []
        config["views"][0]["cards"].append(card)

        # Save updated config
        data = json.dumps(config).encode()
        req2 = urllib.request.Request(
            "$HA_URL/api/lovelace/config",
            data=data,
            method="POST",
            headers={
                "Authorization": "Bearer $HA_TOKEN",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req2, context=ctx) as r:
            print("success")
    else:
        print("no_views")
except Exception as e:
    print(f"error: {e}")
PYEOF
)
            if [ "$result" = "success" ]; then
                echo "   ✅ Dashboard card added to Overview dashboard"
                echo "   Refresh your browser to see it"
            elif [ "$result" = "no_views" ]; then
                echo "   ⚠️  Could not find a dashboard view to add the card to"
                echo "   Add it manually from the Dashboard Card section in the README"
            else
                echo "   ⚠️  Could not add card automatically: $result"
                echo "   Add it manually from the Dashboard Card section in the README"
            fi
        else
            echo "   ⚠️  Card template file not found"
        fi
    else
        echo "   Skipped — add the card manually from the Dashboard Card section in the README"
    fi
fi
echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

if grep -q "include_dir_merge_list automations" $CONFIG; then
    echo "✅ automation: !include_dir_merge_list automations/ — found"
else
    # Check if old single-file format exists and replace it
    if grep -q "automation: !include automations.yaml" $CONFIG; then
        sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" $CONFIG
        echo "✅ automation: updated from !include to !include_dir_merge_list automations/"
    elif grep -q "^automation:" $CONFIG; then
        # automation: key exists but with different value - replace line
        sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" $CONFIG
        echo "✅ automation: updated to !include_dir_merge_list automations/"
    else
        # Not present at all - append to end of file
        echo "" >> $CONFIG
        echo "automation: !include_dir_merge_list automations/" >> $CONFIG
        echo "✅ automation: !include_dir_merge_list automations/ — added to configuration.yaml"
    fi
fi

if grep -q "include_dir_named packages" $CONFIG; then
    echo "✅ packages: !include_dir_named packages/ — found"
else
    # Check if homeassistant: block exists
    if grep -q "^homeassistant:" $CONFIG; then
        # Insert packages line after homeassistant:
        sed -i "/^homeassistant:/a\  packages: !include_dir_named packages/" $CONFIG
        echo "✅ packages: !include_dir_named packages/ — added under homeassistant:"
    else
        # Add full homeassistant block
        echo "" >> $CONFIG
        echo "homeassistant:" >> $CONFIG
        echo "  packages: !include_dir_named packages/" >> $CONFIG
        echo "✅ homeassistant: packages: !include_dir_named packages/ — added to configuration.yaml"
    fi
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
