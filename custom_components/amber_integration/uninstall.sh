#!/bin/bash
# =============================================================================
# Amber - Part 2 uninstaller
# =============================================================================
#
# Removes what install.sh added: the blueprints, the automations created from
# them, and the dashboard. Prompts for scope - remove everything, or just the
# dashboard while leaving the blueprints, automations and rule settings in
# place. The integration itself (Part 1) is NOT touched either way.
#
# To remove Part 1 as well, do that afterwards through the UI:
#   Settings > Devices & Services > HA Custom Amber Electric Integration
#   > three-dot menu > Delete
#
# Your settings (rules, prices, battery thresholds) live on the integration
# as entities, so they disappear with Part 1, not with this script.
#
# Usage:
#   bash /config/custom_components/amber_integration/uninstall.sh
# =============================================================================

set -e

SRC=/config/custom_components/amber_integration
CONFIG=/config/configuration.yaml

# Automations created by install.sh, plus every name used by earlier
# versions of this project - so this cleans up regardless of which version
# was originally installed.
CURRENT_AUTOMATIONS="amber_auto_sell amber_auto_buy amber_fallback_self_consumption"
LEGACY_AUTOMATIONS="amber_force_export amber_force_charge amber_block_smart_shift \
amber_price_poll amber_auth_login_startup amber_battery_connection \
amber_negative_price_notify amber_force_export_at_custom_fit \
amber_force_charge_on_custom_rate amber_hacs_update"

echo "============================================="
echo " Amber - Part 2 uninstaller"
echo "============================================="
echo ""
echo "What do you want to remove?"
echo ""
echo "  1) Everything - blueprints, their automations, and the dashboard"
echo "  2) Just the dashboard - keeps the blueprints, automations and"
echo "     your rule settings untouched"
echo ""
read -r -p "Choice [1/2, default 1]: " scope_choice
if [[ "$scope_choice" == "2" ]]; then
    DASHBOARD_ONLY=true
    echo ""
    echo "This removes only the dashboard."
    echo "The blueprints, automations, and the integration itself (Part 1)"
    echo "are NOT touched."
else
    DASHBOARD_ONLY=false
    echo ""
    echo "This removes the blueprints, their automations, and the dashboard."
    echo "The integration itself (Part 1) is NOT touched - remove that from"
    echo "Settings > Devices & Services if you want it gone too."
fi
echo ""
read -r -p "Continue? (y/N): " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

if [ "$DASHBOARD_ONLY" = false ]; then

# --- automations ---
echo ""
echo "Removing automations..."
FOUND=false
for f in $CURRENT_AUTOMATIONS $LEGACY_AUTOMATIONS; do
    if [ -f "/config/automations/$f.yaml" ]; then
        rm "/config/automations/$f.yaml"
        echo "  removed $f.yaml"
        FOUND=true
    fi
done
[ "$FOUND" = false ] && echo "  none found"

# --- blueprints ---
echo ""
echo "Removing blueprints..."
if [ -d /config/blueprints/automation/amber ]; then
    rm -rf /config/blueprints/automation/amber
    echo "  removed /config/blueprints/automation/amber/"
else
    echo "  none found"
fi

# --- leftovers from versions that used a package and shell scripts ---
echo ""
echo "Removing leftovers from earlier versions..."
FOUND=false
for f in /config/packages/amber.yaml /config/package/amber.yaml \
         /config/scripts/amber_graphql.py /config/scripts/amber_auth.py \
         /config/scripts/configure_smtp.py /config/scripts/amber_token_cache.json \
         /config/.amber_token_cache /config/templates/amber.yaml; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "  removed $f"
        FOUND=true
    fi
done
[ "$FOUND" = false ] && echo "  none found"

fi

# --- dashboard ---
echo ""
echo "Dashboard..."
# mode: yaml dashboards are read-only in the UI, so the only way this could
# differ from what was installed is a direct file edit - not worth checking
# for, just remove it.
DASH=/config/lovelace/amber.yaml
REMOVED_DASH=false
if [ -f "$DASH" ]; then
    rm "$DASH"
    echo "  removed"
    REMOVED_DASH=true
else
    echo "  none found"
fi

# Drop the sidebar entry only if the file is actually gone, otherwise HA
# errors on a dashboard pointing at a missing file.
if [ "$REMOVED_DASH" = true ] && grep -q "lovelace-amber" "$CONFIG"; then
    python3 - "$CONFIG" << 'PYEOF'
import re, sys
p = sys.argv[1]
cfg = open(p).read()
cfg = re.sub(r'\n    lovelace-amber:\n(?:      .*\n)+', '\n', cfg)
cfg = re.sub(r'\nlovelace:\n  dashboards:\n(?=\n|$)', '\n', cfg)
open(p, 'w').write(cfg)
PYEOF
    echo "  removed lovelace-amber from configuration.yaml"
fi

echo ""
echo "============================================="
echo " Done"
echo "============================================="
echo ""
echo " Restart Home Assistant:"
echo "   Settings > System > Restart"
echo ""
if [ "$DASHBOARD_ONLY" = true ]; then
    echo " The blueprints and their automations are still installed and"
    echo " enabled exactly as they were - only the dashboard is gone."
else
    echo " Your rules and thresholds are entities on the integration, so they"
    echo " are still there if you reinstall Part 2 later. They only disappear"
    echo " if you delete the integration itself."
fi
echo ""
