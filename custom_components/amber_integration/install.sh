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

MODE=${1:-full}

# Exit on error in full mode only — sync mode continues on errors
[ "$MODE" = "full" ] && set -e || true
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
# Detect existing packages folder name
if [ -d "/config/package" ] && ! [ -d "/config/packages" ]; then
    PKG_DIR=/config/package
else
    PKG_DIR=/config/packages
fi
mkdir -p "$PKG_DIR"
cp -v $SRC/packages/amber.yaml "$PKG_DIR/"

echo ""
echo "📄 Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/amber.yaml /config/templates/

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
# Load / prompt for credentials
# -----------------------------------------------------------------------------
SECRETS=/config/secrets.yaml
[ -f "$SECRETS" ] || echo "" > "$SECRETS"

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
# Email notifications (full mode only)
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    echo ""
    echo "📧 Email Notifications (optional)"
    echo "   By default notifications go to the HA bell only."
    echo "   You can also receive email alerts."
    echo ""
    read -r -p "   Set up email notifications now? (y/N): " setup_email
    if [[ "$setup_email" =~ ^[Yy]$ ]]; then
        prompt_if_missing "smtp_username" "Email address (e.g. you@gmail.com)"
        prompt_if_missing "smtp_password" "Email app password (Gmail: use an App Password — https://myaccount.google.com/apppasswords)"

        echo ""
        echo -n "   SMTP server (press Enter for smtp.gmail.com): "
        read -r smtp_server_input
        SMTP_SERVER=${smtp_server_input:-smtp.gmail.com}
        if ! grep -q "^smtp_server:" $SECRETS; then
            echo "smtp_server: "${SMTP_SERVER}"" >> $SECRETS
            echo "   ✅ smtp_server set to $SMTP_SERVER"
        else
            SMTP_SERVER=$(grep "^smtp_server:" $SECRETS | sed "s/smtp_server: *//" | tr -d '"')
            echo "   ⏭️  smtp_server already set to $SMTP_SERVER — skipping"
        fi

        # Apply SMTP config to package now that secrets.yaml and packages/amber.yaml both exist
        SMTP_USER=$(grep "^smtp_username:" $SECRETS 2>/dev/null | sed "s/smtp_username: *//" | tr -d '"')
        PKG=${PKG_DIR:-/config/packages}/amber.yaml
        if [ -f "$PKG" ]; then
            python3 $SRC/scripts/configure_smtp.py "$PKG" "$SMTP_USER"
            echo "   ✅ Email notifications configured in amber.yaml"
        fi
    else
        echo "   Skipped — see Email Notifications in README to configure later."
    fi
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

# Check if a number helper is at its minimum/unset value
# HA sets input_number to min value on first load if no stored state
number_needs_default() {
    local entity_id=$1
    local default_value=$2
    local min_value=$3
    [ -z "$HA_TOKEN" ] && echo "yes" && return
    current=$(get_state "$entity_id")
    # Set default if: unavailable, unknown, empty, OR at minimum value (freshly created)
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ] || \
       [ "$current" = "$min_value" ] || python3 -c "exit(0 if abs(float('$current') - float('$min_value')) < 0.0001 else 1)" 2>/dev/null; then
        echo "yes"
    else
        echo "no"
    fi
}

# Check if a datetime helper is at midnight (unset default)
datetime_needs_default() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "yes" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ] || \
       [ "$current" = "00:00:00" ]; then
        echo "yes"
    else
        echo "no"
    fi
}

set_number_if_default() {
    local entity_id=$1 default_value=$2 description=$3 min_value=$4
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    if [ "$(number_needs_default "$entity_id" "$default_value" "$min_value")" = "yes" ]; then
        ha_post "services/input_number/set_value" "{\"entity_id\": \"$entity_id\", \"value\": $default_value}" > /dev/null
        echo "   ✅ $description set to $default_value"
    else
        current=$(get_state "$entity_id")
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_datetime_if_default() {
    local entity_id=$1 default_value=$2 description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    if [ "$(datetime_needs_default "$entity_id")" = "yes" ]; then
        ha_post "services/input_datetime/set_datetime" "{\"entity_id\": \"$entity_id\", \"time\": \"$default_value\"}" > /dev/null
        echo "   ✅ $description set to $default_value"
    else
        current=$(get_state "$entity_id")
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
# Create Amber dashboard (optional)
# -----------------------------------------------------------------------------
echo ""
echo "📊 Dashboard"
DASHBOARD_DIR="/config/lovelace"
DASHBOARD_FILE="$DASHBOARD_DIR/amber.yaml"
LOVELACE_SRC="$SRC/lovelace/amber.yaml"

mkdir -p "$DASHBOARD_DIR"

if [ -f "$DASHBOARD_FILE" ]; then
    echo "   ℹ️  Amber dashboard already exists."
    read -r -p "   Overwrite with default? This resets any customisations. (y/N): " overwrite_dash
    if [[ "$overwrite_dash" =~ ^[Yy]$ ]]; then
        if [ -f "$LOVELACE_SRC" ]; then
            cp "$LOVELACE_SRC" "$DASHBOARD_FILE"
            echo "   ✅ Dashboard overwritten: $DASHBOARD_FILE"
        else
            echo "   ⚠️  Dashboard template not found: $LOVELACE_SRC"
        fi
    else
        echo "   ⏭️  Keeping existing dashboard"
    fi
else
    read -r -p "   Create Amber dashboard in sidebar? (Y/n): " create_dash
    if [[ ! "$create_dash" =~ ^[Nn]$ ]]; then
        if [ -f "$LOVELACE_SRC" ]; then
            cp "$LOVELACE_SRC" "$DASHBOARD_FILE"
            echo "   ✅ Dashboard created: $DASHBOARD_FILE"
        else
            echo "   ⚠️  Dashboard template not found: $LOVELACE_SRC"
        fi
    else
        echo "   Skipped — see Dashboard Card section in README to add manually later."
    fi
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
elif [ -f "/config/automations.yaml" ]; then
    echo "   ℹ️  Found existing automations.yaml — migrating to automations/ directory..."
    mkdir -p /config/automations
    cp /config/automations.yaml /config/automations/automations_existing.yaml
    if grep -q "automation: !include automations.yaml" $CONFIG; then
        sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" $CONFIG
    elif grep -q "^automation:" $CONFIG; then
        sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" $CONFIG
    fi
    echo "   ✅ Existing automations backed up to automations/automations_existing.yaml"
    echo "   ✅ automation: updated to !include_dir_merge_list automations/"
elif grep -q "^automation:" $CONFIG; then
    sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" $CONFIG
    echo "✅ automation: updated to !include_dir_merge_list automations/"
else
    echo "" >> $CONFIG
    echo "automation: !include_dir_merge_list automations/" >> $CONFIG
    echo "✅ automation: !include_dir_merge_list automations/ — added"
fi

# Detect existing packages folder name (some users use package/ not packages/)
if grep -q "include_dir_named packages" $CONFIG || grep -q "include_dir_named package" $CONFIG; then
    echo "✅ packages config — found"
elif [ -d "/config/package" ] && ! [ -d "/config/packages" ]; then
    echo "   ℹ️  Found existing package/ folder — using that instead of packages/"
    if grep -q "^homeassistant:" $CONFIG; then
        sed -i "/^homeassistant:/a\\  packages: !include_dir_named package/" $CONFIG
    else
        printf "\nhomeassistant:\n  packages: !include_dir_named package/\n" >> $CONFIG
    fi
    echo "✅ packages: !include_dir_named package/ — added"
else
    if grep -q "^homeassistant:" $CONFIG; then
        sed -i "/^homeassistant:/a\\  packages: !include_dir_named packages/" $CONFIG
    else
        printf "\nhomeassistant:\n  packages: !include_dir_named packages/\n" >> $CONFIG
    fi
    echo "✅ packages: !include_dir_named packages/ — added"
fi

if grep -q "lovelace-amber" $CONFIG; then
    echo "✅ lovelace dashboard entry — found"
elif [ -f "$DASHBOARD_FILE" ]; then
    cat >> $CONFIG << 'LOVELACE'

lovelace:
  dashboards:
    lovelace-amber:
      mode: yaml
      title: Amber
      icon: mdi:lightning-bolt
      filename: lovelace/amber.yaml
      show_in_sidebar: true
LOVELACE
    echo "✅ lovelace dashboard entry — added"
fi

# -----------------------------------------------------------------------------
# Reload YAML then set defaults
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    reload_yaml

    echo ""
    echo "🔧 Setting automation enable booleans..."
    set_boolean_if_new "input_boolean.amber_enable_block_smart_shift"          "off"
    set_boolean_if_new "input_boolean.amber_enable_force_export_custom_fit"    "off"
    set_boolean_if_new "input_boolean.amber_enable_negative_price_notify"      "off"
    set_boolean_if_new "input_boolean.amber_enable_force_charge_custom_rate"   "off"
    set_boolean_if_new "input_boolean.amber_enable_force_export_notify"        "on"

    echo ""
    echo "🔧 Setting default values for configurable helpers..."
    # Args: entity_id, default_value, description, min_value
    set_number_if_default   "input_number.amber_min_sell_price"                   0.15      "Min Sell Price"              0
    set_number_if_default   "input_number.amber_min_soc_to_sell"                  10        "Min SOC to Sell"             0
    set_number_if_default   "input_number.amber_max_buy_price_to_charge"          0.05      "Max Buy Price"              -1
    set_number_if_default   "input_number.amber_max_soc_to_charge"                100       "Max SOC to Charge"           0
    set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_start" "16:00:00" "Force Sell Start"
    set_datetime_if_default "input_datetime.amber_force_sell_on_custom_fit_end"   "06:00:00" "Force Sell End"
    set_datetime_if_default "input_datetime.amber_block_smart_shift_start"        "00:00:00" "Block Smart Shift Start"
    set_datetime_if_default "input_datetime.amber_block_smart_shift_end"          "06:00:00" "Block Smart Shift End"
    set_datetime_if_default "input_datetime.amber_force_charge_start"             "11:00:00" "Force Charge Start"
    set_datetime_if_default "input_datetime.amber_force_charge_end"               "13:00:00" "Force Charge End"

    reload_yaml
fi

# -----------------------------------------------------------------------------
# Run auth and test poll
# -----------------------------------------------------------------------------
echo ""
echo "🔐 Running authentication..."
python3 /config/scripts/amber_auth.py && echo "   ✅ Authentication successful" || echo "   ⚠️  Auth failed — check amber_email and amber_password in secrets.yaml"

echo ""
echo "📡 Running test price poll..."
python3 /config/scripts/amber_graphql.py live && echo "   ✅ Poll successful — prices updated" || echo "   ⚠️  Poll failed — check your credentials and HA token"

echo ""
echo "============================================="
echo " ✅ Install complete!"
echo ""
echo " ⚡ Future HACS updates will run this script automatically"
echo "    via the amber_hacs_auto_install automation."
echo "============================================="
echo ""

if [ "$MODE" = "full" ]; then
    echo ""
    echo "🔄 Restart Required"
    echo "   Go to Settings → System → Restart to apply all changes."
    echo "   After restart the Amber prices will start polling automatically."
fi
