#!/bin/bash
# =============================================================================
# Home Assistant Custom Amber Electric Integration - Uninstall Script
# =============================================================================
#
# HACS only removes the custom_components folder when you uninstall.
# Run this script to fully remove all integration files and helpers.
#
# Usage:
#   bash /config/custom_components/amber_integration/uninstall.sh
#
# This script will:
#   - Remove all automation files
#   - Remove the package file (helpers, shell commands, notify)
#   - Remove scripts
#   - Remove templates
#   - Remove configuration.yaml entries (if safe to do so)
#
# After running, restart HA to apply changes.
# =============================================================================

echo "============================================="
echo " Home Assistant Custom Amber Electric"
echo " Integration - Uninstall Script"
echo "============================================="
echo ""
echo "⚠️  This will remove all Amber integration files."
echo "    Your secrets.yaml credentials will NOT be removed."
echo ""
read -r -p "Are you sure you want to uninstall? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "🗑️  Removing automations..."
for f in \
    amber_auth_login_startup \
    amber_price_poll \
    amber_block_smart_shift \
    amber_force_export_at_custom_fit \
    amber_force_charge_on_custom_rate \
    amber_negative_price_notify \
    amber_battery_connection \
    amber_hacs_update; do
    if [ -f "/config/automations/${f}.yaml" ]; then
        rm "/config/automations/${f}.yaml"
        echo "   ✅ Removed: /config/automations/${f}.yaml"
    fi
done

echo ""
echo "🗑️  Removing package..."
for PKG in /config/packages/amber.yaml /config/package/amber.yaml; do
    if [ -f "$PKG" ]; then
        rm "$PKG"
        echo "   ✅ Removed: $PKG"
    fi
done

echo ""
echo "🗑️  Removing scripts..."
for f in amber_graphql.py amber_auth.py; do
    if [ -f "/config/scripts/$f" ]; then
        rm "/config/scripts/$f"
        echo "   ✅ Removed: /config/scripts/$f"
    fi
done

echo ""
echo "🗑️  Removing templates..."
if [ -f "/config/templates/amber.yaml" ]; then
    rm /config/templates/amber.yaml
    echo "   ✅ Removed: /config/templates/amber.yaml"
fi

echo ""
echo "🗑️  Removing dashboard..."
CONFIG=/config/configuration.yaml
if [ -f "/config/lovelace/amber.yaml" ]; then
    rm /config/lovelace/amber.yaml
    echo "   ✅ Removed: /config/lovelace/amber.yaml"
fi
if [ -f "$CONFIG" ] && grep -q "lovelace-amber:" "$CONFIG"; then
    sed -i '/^\s*lovelace-amber:/,/show_in_sidebar: true/d' "$CONFIG"
    echo "   ✅ Removed lovelace-amber entry from configuration.yaml"
    if grep -A2 "^lovelace:" "$CONFIG" | grep -q "dashboards:\s*$"; then
        echo "   ⚠️  configuration.yaml still has an empty 'lovelace: dashboards:' block —"
        echo "      remove it manually if you have no other custom dashboards defined there."
    fi
fi

echo ""
echo "🗑️  Removing auth cache..."
if [ -f "/config/.amber_token_cache" ]; then
    rm /config/.amber_token_cache
    echo "   ✅ Removed: /config/.amber_token_cache"
fi

echo ""
echo "============================================="
echo " ✅ Uninstall complete!"
echo ""
echo " Next steps:"
echo "  1. Remove HACS integration: HACS → Integrations → Amber → Remove"
echo "  2. Restart HA: Settings → System → Restart"
echo "  3. Optionally remove credentials from /config/secrets.yaml:"
echo "     amber_email, amber_password, ha_long_lived_token"
echo "  4. If no other integrations use packages, remove from configuration.yaml:"
echo "     homeassistant:"
echo "       packages: !include_dir_named packages/"
echo "============================================="
