#!/bin/bash
# =============================================================================
# Home Assistant Custom Amber Electric Integration - Install Script
# =============================================================================
#
# Usage:
#   bash /config/custom_components/amber_integration/install.sh
#
# Mode: "full" (default) runs pip installs and sets defaults.
#       "sync" just copies files — used on HA startup.
# =============================================================================

set -e

MODE=${1:-full}
SRC=/config/custom_components/amber_integration
CONFIG=/config/configuration.yaml
ERRORS=0

echo "============================================="
echo " Home Assistant Custom Amber Electric"
echo " Integration - Install Script"
echo "============================================="
echo ""

# -----------------------------------------------------------------------------
# Python / pip checks (full mode only)
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    echo "🔍 Checking python3..."
    if ! command -v python3 &>/dev/null; then
        echo "   python3 not found, installing..."
        apk add python3
    fi
    echo "   python3 $(python3 --version)"

    echo "🔍 Checking pip3..."
    if ! command -v pip3 &>/dev/null; then
        echo "   pip3 not found, installing..."
        apk add py3-pip
    fi
    echo "   pip3 found"
    echo ""

    echo "🐍 Installing pycognito..."
    pip3 install pycognito --break-system-packages
    echo ""
else
    echo "⚡ Sync mode — skipping python/pip checks"
    echo ""
fi

# -----------------------------------------------------------------------------
# Copy files
# -----------------------------------------------------------------------------
echo "📋 Copying automations..."
mkdir -p /config/automations
cp -v $SRC/automations/*.yaml /config/automations/

echo ""
echo "🐍 Copying scripts..."
mkdir -p /config/scripts
cp -v $SRC/scripts/*.py /config/scripts/

echo ""
echo "📦 Copying package..."
mkdir -p /config/packages
cp -v $SRC/packages/amber.yaml /config/packages/

echo ""
echo "📄 Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/amber.yaml /config/templates/

# -----------------------------------------------------------------------------
# Remove deprecated files
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

# -----------------------------------------------------------------------------
# Load credentials
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
            echo "${key}: \"${value}\"" >> $SECRETS
            echo "   ✅ ${key} saved to secrets.yaml"
        else
            echo "   ⚠️  Skipped — add ${key} to secrets.yaml manually later"
        fi
    else
        echo "   ⏭️  ${key} already set — skipping"
    fi
}

if [ "$MODE" = "full" ]; then
    echo ""
    echo "🔑 Checking credentials in secrets.yaml..."
    prompt_if_missing "amber_email"         "Amber Electric login email"
    prompt_if_missing "amber_password"      "Amber Electric login password"
    prompt_if_missing "ha_long_lived_token" "HA Long-Lived Access Token (Profile → Long-Lived Access Tokens → Create Token)"
    if ! grep -q "^ha_url:" $SECRETS; then
        echo "ha_url: \"http://localhost:8123\"" >> $SECRETS
        echo "   ✅ ha_url set to http://localhost:8123 (default)"
    fi
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

ha_post() {
    local endpoint=$1
    local data=$2
    curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$HA_URL/api/$endpoint" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$data"
}

get_state() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "" && return
    curl -s \
        "$HA_URL/api/states/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo ""
}

set_number_if_default() {
    local entity_id=$1 default_value=$2 description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        ha_post "services/input_number/set_value" "{\"entity_id\": \"$entity_id\", \"value\": $default_value}" > /dev/null
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_datetime_if_default() {
    local entity_id=$1 default_value=$2 description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        ha_post "services/input_datetime/set_datetime" "{\"entity_id\": \"$entity_id\", \"time\": \"$default_value\"}" > /dev/null
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_boolean_if_new() {
    local entity_id=$1 state=$2
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        ha_post "services/input_boolean/turn_${state}" "{\"entity_id\": \"$entity_id\"}" > /dev/null
        echo "   ✅ ${state^^}: $entity_id (first install default)"
    else
        echo "   ⏭️  $entity_id already $current — keeping user value"
    fi
}

reload_yaml() {
    [ -z "$HA_TOKEN" ] && return
    echo ""
    echo "🔄 Reloading HA YAML configuration..."
    result=$(ha_post "services/homeassistant/reload_all" "{}")
    if [ "$result" = "200" ]; then
        echo "   ✅ YAML reloaded — waiting 15 seconds for helpers to initialise..."
        sleep 15
    else
        echo "   ⚠️  Could not reload YAML (HTTP $result)"
    fi
}

# -----------------------------------------------------------------------------
# Create Amber dashboard
# -----------------------------------------------------------------------------
echo ""
echo "📊 Creating Amber dashboard..."

DASHBOARD_DIR="/config/lovelace"
DASHBOARD_FILE="$DASHBOARD_DIR/amber.yaml"
LOVELACE_SRC="$SRC/lovelace/amber.yaml"

mkdir -p "$DASHBOARD_DIR"

if [ -f "$DASHBOARD_FILE" ]; then
    echo "   ⏭️  Dashboard already exists — skipping"
elif [ -f "$LOVELACE_SRC" ]; then
    cp "$LOVELACE_SRC" "$DASHBOARD_FILE"
    echo "   ✅ Dashboard created: $DASHBOARD_FILE"
else
    echo "   ⚠️  Dashboard template not found: $LOVELACE_SRC"
fi

# -----------------------------------------------------------------------------
# Update configuration.yaml
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

if grep -q "include_dir_merge_list automations" $CONFIG; then
    echo "✅ automation: !include_dir_merge_list automations/ — found"
elif grep -q "automation: !include automations.yaml" $CONFIG; then
    sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" $CONFIG
    echo "✅ automation: updated to !include_dir_merge_list automations/"
elif grep -q "^automation:" $CONFIG; then
    sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" $CONFIG
    echo "✅ automation: updated to !include_dir_merge_list automations/"
else
    echo "" >> $CONFIG
    echo "automation: !include_dir_merge_list automations/" >> $CONFIG
    echo "✅ automation: !include_dir_merge_list automations/ — added"
fi

if grep -q "include_dir_named packages" $CONFIG; then
    echo "✅ packages: !include_dir_named packages/ — found"
elif grep -q "^homeassistant:" $CONFIG; then
    sed -i "/^homeassistant:/a\\  packages: !include_dir_named packages/" $CONFIG
    echo "✅ packages: !include_dir_named packages/ — added under homeassistant:"
else
    echo "" >> $CONFIG
    echo "homeassistant:" >> $CONFIG
    echo "  packages: !include_dir_named packages/" >> $CONFIG
    echo "✅ homeassistant: packages: — added"
fi

if grep -q "lovelace-amber" $CONFIG; then
    echo "✅ lovelace dashboard entry — found"
elif grep -q "^lovelace:" $CONFIG; then
    sed -i "/^lovelace:/a\\  dashboards:\n    lovelace-amber:\n      mode: yaml\n      title: Amber\n      icon: mdi:lightning-bolt\n      filename: lovelace/amber.yaml\n      show_in_sidebar: true" $CONFIG
    echo "✅ lovelace dashboard entry — added"
else
    echo "" >> $CONFIG
    echo "lovelace:" >> $CONFIG
    echo "  dashboards:" >> $CONFIG
    echo "    lovelace-amber:" >> $CONFIG
    echo "      mode: yaml" >> $CONFIG
    echo "      title: Amber" >> $CONFIG
    echo "      icon: mdi:lightning-bolt" >> $CONFIG
    echo "      filename: lovelace/amber.yaml" >> $CONFIG
    echo "      show_in_sidebar: true" >> $CONFIG
    echo "✅ lovelace dashboard entry — added"
fi

# -----------------------------------------------------------------------------
# Reload YAML so helpers are available before setting defaults
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    reload_yaml

    # -----------------------------------------------------------------------------
    # Set automation enable booleans (first install only)
    # -----------------------------------------------------------------------------
    echo ""
    echo "🔧 Setting automation enable booleans..."
    set_boolean_if_new "input_boolean.amber_enable_block_smart_shift"          "off"
    set_boolean_if_new "input_boolean.amber_enable_force_export_custom_fit"    "off"
    set_boolean_if_new "input_boolean.amber_enable_negative_price_notify"      "off"
    set_boolean_if_new "input_boolean.amber_enable_force_charge_custom_rate"   "off"
    set_boolean_if_new "input_boolean.amber_enable_force_export_notify"        "on"

    # -----------------------------------------------------------------------------
    # Set configurable helper defaults (first install only)
    # -----------------------------------------------------------------------------
    echo ""
    echo "🔧 Setting default values for configurable helpers..."
    set_number_if_default   "input_number.amber_min_sell_price"                   0.15      "Min Sell Price"
    set_number_if_default   "input_number.amber_min_soc_to_sell"                  10        "Min SOC to Sell"
    set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_start" "16:00:00" "Force Sell Start"
    set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_end"   "06:00:00" "Force Sell End"
    set_datetime_if_default "input_datetime.amber_block_smart_shift_start"        "00:00:00" "Block Smart Shift Start"
    set_datetime_if_default "input_datetime.amber_block_smart_shift_end"          "06:00:00" "Block Smart Shift End"
    set_number_if_default   "input_number.amber_max_buy_price_to_charge"          0.05      "Max Buy Price"
    set_number_if_default   "input_number.amber_max_soc_to_charge"                100       "Max SOC to Charge"
    set_datetime_if_default "input_datetime.amber_force_charge_start"             "11:00:00" "Force Charge Start"
    set_datetime_if_default "input_datetime.amber_force_charge_end"               "13:00:00" "Force Charge End"

    # -----------------------------------------------------------------------------
    # Final YAML reload
    # -----------------------------------------------------------------------------
    reload_yaml
fi

echo ""
echo "============================================="
echo " ✅ Install complete!"
echo ""
echo " ⚡ Future HACS updates will run this script automatically"
echo "    via the amber_hacs_auto_install automation."
echo ""
echo " Restart HA for all changes to take effect:"
echo " Settings → System → Restart"
echo "============================================="
