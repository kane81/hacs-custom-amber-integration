{#
=========================================================================
Amber Electric - Amber-Only Dashboard Card
=========================================================================
Use this card if you only have hacs-custom-amber-integration installed
without hacs-goodwe-sems-curtailment.

For the unified card (with power flow and SEMS curtailment status),
use DashboardCardExample.md from hacs-goodwe-sems-curtailment instead.

Steps:
  1. Go to Settings → Dashboards → open your dashboard
  2. Click the pencil icon (top right) to enter edit mode
  3. Click + Add Card → Select Markdown card
  4. Paste everything after the #} line into the Content field
  5. Click Save

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
{# --- Automation Enable Flags --- #}
{% set en_force_export = is_state('input_boolean.amber_enable_force_export_custom_fit', 'on') %}
{% set en_block_ss     = is_state('input_boolean.amber_enable_block_smart_shift', 'on') %}
{% set en_grid_charge  = is_state('input_boolean.amber_enable_charge_on_negative_buy', 'on') %}
{% set en_neg_notify   = is_state('input_boolean.amber_enable_negative_price_notify', 'on') %}
{# --- Automation Session State Flags --- #}
{% set force_export_active = is_state('input_boolean.amber_force_export_active', 'on') %}
{% set ss_blocked          = is_state('input_boolean.amber_block_smart_shift_active', 'on') %}
{% set grid_charging       = is_state('input_boolean.amber_grid_charging_active', 'on') %}
{% set battery_offline     = is_state('input_boolean.amber_battery_offline', 'on') %}
{# --- Icon logic: 🚫 disabled · 🟢 active · 🔴 enabled/waiting --- #}
{% set ic_force_export = '⚠️' if (battery_offline and en_force_export) else ('🚫' if not en_force_export else ('🟢' if force_export_active else '🔴')) %}
{% set ic_block_ss     = '⚠️' if (battery_offline and en_block_ss)     else ('🚫' if not en_block_ss     else ('🟢' if ss_blocked          else '🔴')) %}
{% set ic_grid_charge  = '⚠️' if (battery_offline and en_grid_charge)  else ('🚫' if not en_grid_charge  else ('🟢' if grid_charging        else '🔴')) %}
{% set ic_neg_notify   = '🚫' if not en_neg_notify   else '🟢' %}

**💲 Amber**
&nbsp;&nbsp;Buy **{{ (buy_price * 100) | round(0) | int }}c** &nbsp;&nbsp; Sell **{{ sell_display }}c** &nbsp;&nbsp; SOC **{{ '⚠️' if battery_offline else (soc | round(0) | int ~ '%') }}**
{{ '&nbsp;&nbsp;⚠️ **Amber Battery Connection Offline**' if battery_offline else '' }}
&nbsp;&nbsp;Import **${{ '%.2f' | format(import_cost / 100) }}** &nbsp;&nbsp; Export **${{ '%.2f' | format((export_earnings / 100) | abs) }}** &nbsp;&nbsp; {{ '💰 Credit **$' ~ '%.2f' | format(total_earnings / 100) ~ '**' if total_earnings > 0 else '💸 Expense **$' ~ '%.2f' | format((total_earnings / 100) | abs) ~ '**' if total_earnings < 0 else '**$0.00**' }}
&nbsp;&nbsp;Last checked **{{ states('input_datetime.amber_last_polled') | as_timestamp | timestamp_custom('%I:%M %p') }}**

**🤖 Automations**
&nbsp;&nbsp;{{ ic_force_export }} **Export**{{ ' 🔕' if not en_export_notify else '' }} - FiT {{ (min_sell_price * 100) | round(0) | int }}c · Min SOC {{ min_soc_to_sell | round(0) | int }}% · {{ fit_start }}–{{ fit_end }}
&nbsp;&nbsp;{{ ic_block_ss }} **Block Smart Shift** - {{ ss_block_start }}–{{ ss_block_end }}{{ ' · Active' if ss_blocked else '' }}
&nbsp;&nbsp;{{ ic_grid_charge }} **Grid Charge on Negative Buy** - {{ charge_start }}-{{ charge_end }}
&nbsp;&nbsp;{{ ic_neg_notify }} **Negative Price Notify** - {{ charge_start }}–{{ charge_end }}