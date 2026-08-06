#!/bin/bash
# =============================================================================
# Amber - dashboard and automation installer
# =============================================================================
#
# Installs everything Part 2 needs beyond what HACS + Add Integration already
# did:
#
#   - blueprint TEMPLATES  -> /config/blueprints/automation/amber/
#     (so they show up in Settings > Automations > Blueprints automatically -
#     no manual "Import a blueprint" URL paste needed)
#
#   - three ready-to-go AUTOMATIONS, each using one of those blueprints with
#     Part 1's actual entity IDs already filled in -> /config/automations/
#     (so there is nothing left to click through in the UI either - they
#     exist and are visible in Settings > Automations the moment you restart)
#
#   - the dashboard -> /config/lovelace/amber.yaml (optional, asks first)
#
# All three automations are created but INERT. Each blueprint checks its own
# "Enable ..." switch as a condition, and every one of those switches
# defaults to off, so nothing moves your battery until you turn one on
# yourself under Configuration on the device page.
#
# There is no login here, no token, no secrets.yaml, no package system. The
# script restarts Home Assistant for you at the end via `ha core restart`
# (Home Assistant OS / Supervised only - see the note near the bottom of
# this file for the plain-container fallback).
#
# Usage:
#   bash /config/custom_components/amber_integration/install.sh
# =============================================================================

set -e

SRC=/config/custom_components/amber_integration
CONFIG=/config/configuration.yaml

# Automation files from every earlier version of this project. Defined once
# here rather than repeated in the detect and remove loops below, so the two
# can't drift apart. These called shell commands and polled Amber directly -
# both now handled by the integration - and would error on every trigger if
# left in place.
LEGACY_AUTOMATIONS="amber_price_poll amber_auth_login_startup \
amber_battery_connection amber_negative_price_notify \
amber_force_export_at_custom_fit amber_force_charge_on_custom_rate \
amber_hacs_update amber_force_export amber_force_charge \
amber_block_smart_shift"

LEGACY_FILES="/config/packages/amber.yaml /config/package/amber.yaml \
/config/scripts/amber_auth.py \
/config/scripts/configure_smtp.py /config/scripts/amber_token_cache.json \
/config/.amber_token_cache /config/templates/amber.yaml"

echo "============================================="
echo " Amber dashboard and automation installer"
echo "============================================="
echo ""

if [ ! -d "$SRC/blueprints" ]; then
    echo "ERROR: blueprint files not found at $SRC/blueprints"
    echo "       Install the integration via HACS first."
    exit 1
fi

# -----------------------------------------------------------------------------
# Clean up files from before the blueprint rewrite
# -----------------------------------------------------------------------------
echo "Checking for files from previous versions..."
FOUND_OLD=false
for f in $LEGACY_AUTOMATIONS; do
    [ -f "/config/automations/$f.yaml" ] && FOUND_OLD=true
done
for f in $LEGACY_FILES; do
    [ -f "$f" ] && FOUND_OLD=true
done

if [ "$FOUND_OLD" = true ]; then
    echo ""
    echo "  Found files from an earlier version of this project. These are"
    echo "  replaced by the integration and the blueprints, and will log"
    echo "  errors on every trigger if left in place."
    echo ""
    read -r -p "  Remove them? (Y/n): " ans
    if [[ ! "$ans" =~ ^[Nn]$ ]]; then
        for f in $LEGACY_AUTOMATIONS; do
            [ -f "/config/automations/$f.yaml" ] && rm "/config/automations/$f.yaml" && echo "    removed $f.yaml"
        done
        for f in $LEGACY_FILES; do
            [ -f "$f" ] && rm "$f" && echo "    removed $f"
        done
        echo ""
        echo "  Old settings are now entities on the integration's device page"
        echo "  under Configuration - set them there if you haven't already."
    else
        echo "    Left in place. Expect errors in your log until they're removed."
    fi
else
    echo "  None found."
fi

# -----------------------------------------------------------------------------
# Blueprint templates - the auto-discovery location, not custom_components
# -----------------------------------------------------------------------------
echo ""
echo "Installing blueprint templates..."
mkdir -p /config/blueprints/automation/amber
cp -v "$SRC"/blueprints/automation/amber/*.yaml /config/blueprints/automation/amber/

# -----------------------------------------------------------------------------
# Automations that use those blueprints, with Part 1's entity IDs filled in
# -----------------------------------------------------------------------------
echo ""
echo "Installing automations..."
mkdir -p /config/automations
for f in "$SRC"/automations_from_blueprint/*.yaml; do
    name=$(basename "$f")
    dest="/config/automations/$name"
    if [ -f "$dest" ]; then
        echo "  $name already exists."
        read -r -p "    Overwrite? Any input customisation via the UI editor will be lost. (y/N): " ans
        if [[ "$ans" =~ ^[Yy]$ ]]; then
            cp "$f" "$dest"
            echo "    overwritten"
        else
            echo "    kept"
        fi
    else
        cp "$f" "$dest"
        echo "  created $name"
    fi
done

# -----------------------------------------------------------------------------
# Dashboard (optional)
# -----------------------------------------------------------------------------
echo ""
echo "Dashboard"
DASH_DIR=/config/lovelace
DASH_FILE="$DASH_DIR/amber.yaml"
DASH_SRC="$SRC/lovelace/amber.yaml"
mkdir -p "$DASH_DIR"

echo ""
echo "  Two ways to get the dashboard:"
echo ""
echo "    1) Automatic - installs now, ready to use immediately. Can only"
echo "       be edited afterward by editing the YAML file directly - Home"
echo "       Assistant deliberately locks UI editing for this kind of"
echo "       dashboard, so there's no drag-and-drop editor for it."
echo "    2) Manual - skip this and build your own instead, via Settings >"
echo "       Dashboards, pasting lovelace/amber.yaml into the Raw"
echo "       configuration editor. Fully editable in the UI afterward -"
echo "       see the README's 'Manually Adding the Card' section for"
echo "       the exact steps."
echo ""
read -r -p "  Install the dashboard automatically? (Y/n): " dash_choice
if [[ "$dash_choice" =~ ^[Nn]$ ]]; then
    echo "  Skipped."
    if [ -f "$DASH_FILE" ]; then
        echo "  Note: $DASH_FILE already exists from a previous run - it's"
        echo "  still there and still registered. Run uninstall.sh first if"
        echo "  you want it gone before building your own."
    fi
else
    cp "$DASH_SRC" "$DASH_FILE"
    echo "  Installed $DASH_FILE"
fi

# -----------------------------------------------------------------------------
# configuration.yaml
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

# automations/ directory include - preserves any existing automations.yaml
# rather than orphaning them, same as previous versions of this script.
if grep -q "include_dir_merge_list automations" "$CONFIG"; then
    echo "OK  automation: include already present"
elif [ -f /config/automations.yaml ]; then
    echo "    Found an existing automations.yaml - migrating it into automations/"
    mkdir -p /config/automations
    cp /config/automations.yaml /config/automations/automations_existing.yaml
    sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    sed -i "s|^automation:$|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    echo "OK  existing automations preserved as automations/automations_existing.yaml"
elif grep -q "^automation:" "$CONFIG"; then
    sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    echo "OK  automation: include updated"
else
    printf "\nautomation: !include_dir_merge_list automations/\n" >> "$CONFIG"
    echo "OK  automation: include added"
fi

# lovelace dashboard entry
if grep -q "lovelace-amber" "$CONFIG"; then
    echo "OK  lovelace dashboard entry already present"
elif [ -f "$DASH_FILE" ]; then
    cat >> "$CONFIG" << 'LOVELACE'

lovelace:
  dashboards:
    lovelace-amber:
      mode: yaml
      title: Amber
      icon: mdi:lightning-bolt
      filename: lovelace/amber.yaml
      show_in_sidebar: true
LOVELACE
    echo "OK  lovelace dashboard entry added"
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Done"
echo "============================================="
echo ""
echo " Three automations already exist under"
echo "   Settings > Automations & Scenes"
echo " but none of them will do anything yet - each checks its own switch"
echo " first, and all of those default to off."
echo ""
echo " To enable them, open the integration's device page:"
echo "   Settings > Devices & Services > HA Custom Amber Electric Integration"
echo " and under Configuration switch on whichever you want:"
echo "   Enable Sell Rule 1 / 2 / 3        (Auto Sell)"
echo "   Enable Buy Rule 1 / 2 / 3         (Auto Buy)"
echo "   Auto Disable Smart Shift When Idle"
echo ""

# `ha core restart` only exists on Home Assistant OS / Supervised, via the
# Supervisor - it's not present in a plain container (docker exec -it
# homeassistant bash, the other way this script is documented to run). A
# script running inside a plain container has no supervisor and no socket
# access to restart itself from the inside, so that case still needs the
# manual step.
if command -v ha >/dev/null 2>&1; then
    echo " Restarting Home Assistant now..."
    ha core restart
else
    echo " Restart Home Assistant to load everything:"
    echo "   Settings > System > Restart"
    echo ""
    echo " (couldn't restart automatically - the 'ha' command isn't available"
    echo " here, which is normal for a plain container install rather than"
    echo " Home Assistant OS or Supervised)"
    echo ""
fi
