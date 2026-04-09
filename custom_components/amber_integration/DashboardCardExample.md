{#
=========================================================================
Home Power Board - Amber Card
=========================================================================
Displays Amber Electric live pricing, current interval cost/earnings,
and the status of all ha-custom-amber-integration automations.

This card only requires ha-custom-amber-integration to be installed.
It has no dependency on ha-sems-solar-curtailment or any battery sensors.

How to add this card to your Home Assistant dashboard:

Prerequisites:
  - ha-custom-amber-integration installed and running
  - At least one successful price poll (amber_last_polled must have a value)

Steps:
  1. Go to Settings → Dashboards → Add Dashboard → New dashboard from scratch
  2. Open the new dashboard and click the pencil icon (top right)
  3. Click + Add Section
  4. Select Markdown card
  5. Paste the content below into the Content field
  6. Click Save

Card config example:
  type: markdown
  content: |
    << PASTE TEMPLATE HERE >>

Note: This card uses standard HA markdown. If you want richer styling
you can use type: custom:tailwindcss-template-card instead (requires HACS).

Automation status icon legend:
  🟢  Enabled and currently active / running
  🔴  Enabled but not currently active (waiting for conditions)
  🚫  Disabled — automation enable boolean is OFF, will not run
=========================================================================
#}

{# --- Amber Prices --- #}
{% set buy_price    = states('input_number.amber_general_price_actual') | float(0) %}
{% set sell_price   = states('input_number.amber_feed_in_price_actual') | float(0) %}
{% set sell_display = (sell_price * 100) | round(0) | int if sell_price >= 0 else (sell_price * 100) | round(0, 'floor') | int %}

{# --- Current Interval Cost/Earnings (cents → dollars) --- #}
{% set import_cost     = states('input_number.amber_import_cost_cents') | float(0) %}
{% set export_earnings = states('input_number.amber_export_earnings_cents') | float(0) %}
{% set total_earnings  = states('input_number.amber_total_earnings_cents') | float(0) %}

{# --- Automation Thresholds --- #}
{% set min_sell_price  = states('input_number.amber_min_sell_price') | float(0.15) %}
{% set min_soc_to_sell = states('input_number.amber_min_soc_to_sell') | float(10) %}
{% set soc             = states('input_number.amber_battery_soc') | float(0) %}

{# --- Time Windows (HH:MM only) --- #}
{% set fit_start      = states('input_datetime.amber_force_sell_on_custom_fit_start')[0:5] %}
{% set fit_end        = states('input_datetime.amber_force_sell_on_custom_fit_end')[0:5] %}
{% set ss_block_start = states('input_datetime.amber_block_smart_shift_start')[0:5] %}
{% set ss_block_end   = states('input_datetime.amber_block_smart_shift_end')[0:5] %}
{% set charge_start   = states('input_datetime.amber_charge_on_negative_start')[0:5] %}
{% set charge_end     = states('input_datetime.amber_charge_on_negative_end')[0:5] %}

{# --- Automation Enable Flags (input_boolean - persists across restarts) --- #}
{% set en_force_export   = is_state('input_boolean.amber_enable_force_export_custom_fit', 'on') %}
{% set en_block_ss       = is_state('input_boolean.amber_enable_block_smart_shift', 'on') %}
{% set en_grid_charge    = is_state('input_boolean.amber_enable_charge_on_negative_buy', 'on') %}
{% set en_neg_notify     = is_state('input_boolean.amber_enable_negative_price_notify', 'on') %}

{# --- Automation Session State Flags (set/cleared by the automations themselves) --- #}
{% set force_export_active = is_state('input_boolean.amber_force_export_active', 'on') %}
{% set ss_blocked          = is_state('input_boolean.amber_block_smart_shift_active', 'on') %}
{% set grid_charging       = is_state('input_boolean.amber_grid_charging_active', 'on') %}

{#
  Icon logic for optional automations:
    🚫 = automation disabled (enable boolean is OFF) — will not run regardless of conditions
    🟢 = enabled and currently active/running
    🔴 = enabled but not currently active (waiting for conditions to be met)
#}

**💲 Amber**
&nbsp;&nbsp;Buy **{{ (buy_price * 100) | round(0) | int }}c** &nbsp;&nbsp; Sell **{{ sell_display }}c** &nbsp;&nbsp; SOC **{{ soc | round(0) | int }}%**
&nbsp;&nbsp;Import **${{ (import_cost / 100) | round(2) }}** &nbsp;&nbsp; Export **${{ (export_earnings / 100) | abs | round(2) }}** &nbsp;&nbsp; {% if total_earnings > 0 %}💰 Credit **${{ (total_earnings / 100) | round(2) }}**{% elif total_earnings < 0 %}💸 Expense **${{ (total_earnings / 100) | abs | round(2) }}**{% else %}**$0.00**{% endif %}
{% if battery_offline %}🚫 **Amber Battery Connection Offline** — check Amber app for details
{% endif %}{% if not battery_online %}🚫 **Amber Battery Connection Offline** — check Amber app for details
{% endif %}&nbsp;&nbsp;Last checked **{{ states('input_datetime.amber_last_polled') | as_timestamp | timestamp_custom('%I:%M %p') }}**

**🤖 Automations**
&nbsp;&nbsp;{% if not en_force_export %}🚫{% elif force_export_active %}🟢{% else %}🔴{% endif %} **Force Export** — Min FiT {{ (min_sell_price * 100) | round(0) | int }}c · Min SOC {{ min_soc_to_sell | round(0) | int }}% · {{ fit_start }}–{{ fit_end }}
&nbsp;&nbsp;{% if not en_block_ss %}🚫{% elif ss_blocked %}🟢{% else %}🔴{% endif %} **Block Smart Shift** — Window {{ ss_block_start }}–{{ ss_block_end }}{% if ss_blocked %} · Active{% endif %}
&nbsp;&nbsp;{% if not en_grid_charge %}🚫{% elif grid_charging %}🟢{% else %}🔴{% endif %} **Grid Charge on Negative Buy** — Window {{ charge_start }}–{{ charge_end }}
&nbsp;&nbsp;{% if not en_neg_notify %}🚫{% else %}🟢{% endif %} **Negative Price Notify** — Window {{ charge_start }}–{{ charge_end }}
