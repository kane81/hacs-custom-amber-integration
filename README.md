<table><tr><td><img src="brand/icon.png" width="80"/></td><td><h1>Home Assistant Custom Amber Electric Integration</h1></td></tr></table>

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/kane81)


[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/kane81/hacs-custom-amber-integration.svg)](https://github.com/kane81/hacs-custom-amber-integration/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.amber_integration.total)](https://analytics.home-assistant.io)

> **Home Assistant integration that connects to Amber Electric's Smart Shift API to automate battery charging, discharging and solar export based on real-time electricity prices.**

> **Battery agnostic** — works with any battery enrolled in Amber Smart Shift. The integration controls the battery via the Amber API, not directly, so no local battery connection is required.

> ☀️ **Have a GoodWe solar inverter?** Add automatic solar curtailment when prices are negative with the companion project: [hacs-goodwe-sems-curtailment](https://github.com/kane81/hacs-goodwe-sems-curtailment)

📐 [Click here to view the Architecture Diagram](images/architecture.png)

---

## ⚠️ Prerequisites

- Active **Amber Electric** subscription with Smart Shift enabled
- **Smart Shift compatible battery** enrolled in the Amber app
- **Home Assistant OS or Supervised** with HACS installed
- Basic familiarity with Home Assistant

---

## ⚠️ Disclaimer

This project uses Amber Electric's internal API which is not publicly documented or officially supported. Amber may change or remove it at any time without notice. This project has no affiliation with Amber Electric. Use at your own risk — battery control actions directly affect your energy system and electricity costs. The author accepts no responsibility for energy costs, battery damage, or system issues.

### New to Home Assistant?

If you are new to editing Home Assistant configuration files it is strongly recommended to test in a virtual machine before making changes to your live installation.

**[Setting up Home Assistant in a Virtual Machine](https://www.youtube.com/watch?v=GDlUzAsEO30)**

When configuring the VM network adapter use **Bridged Adapter** and **Paravirtualized Network (virtio-net)** — without this, downloads inside the VM can hang for 20+ minutes.

---

## What It Does

| Feature | Description |
|---|---|
| **Price polling** | Fetches live Amber buy/sell prices every 5 minutes |
| **Force Export** | Discharges battery to grid when sell price exceeds your threshold |
| **Grid Charging** | Charges battery from grid when buy price goes negative |
| **Block Smart Shift** | Disables Smart Shift overnight to preserve battery for next day |
| **Price Notifications** | Alerts when buy price goes negative and when it recovers |
| **Battery Offline Detection** | Detects when Amber cannot communicate with the battery — notifies once when offline and again when restored. Shows a warning on the dashboard card. |

All optional automations are **off by default** — enable them individually via the dashboard card or Overview → Devices → Helpers once you are confident the integration is working correctly.

---

## Installation

### Step 1 — Install Prerequisites

#### Install HACS (if not already installed)

HACS (Home Assistant Community Store) is required to install this integration. If it is already in your sidebar, skip ahead to Step 0b.

1. Go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (top right) → **Custom repositories**
3. Paste: `https://github.com/hacs/addons` → Category: **Add-on** → **Add**
4. Search for **HACS** → **Install**
5. Go to the **Info** tab → **Start** → **Restart Home Assistant** when prompted
6. After restart go to **Settings → Devices & Services → Add Integration**
7. Search for **HACS** → follow the setup steps (requires a GitHub account)
8. Once configured, **HACS** will appear in your left sidebar

#### Step 1b — Install Required Add-ons

You also need two add-ons from the **official Home Assistant Add-on Store**.

Open: **Settings → Add-ons → Add-on Store**

#### Studio Code Server — file editor

Used to edit `configuration.yaml` and `secrets.yaml` directly in your browser. Required for Steps 2 and 3.

1. Search for `Studio Code Server` → **Install**
2. Go to the **Info** tab → **Start**
3. Toggle **Show in sidebar** to on

#### Terminal & SSH — command line

Used to run the install script and test authentication. Required for Steps 1, 4 and 5.

1. Search for `Terminal & SSH` → **Install**
2. Go to the **Configuration** tab → click **Show unused optional configuration options** → expand **ssh** → set a username and password — **this is required or the add-on will not start**
3. Go to the **Info** tab → **Start**
4. Toggle **Show in sidebar** to on

---

### Step 2 — Add via HACS

1. Open **HACS** in your HA sidebar
2. Click **⋮** (top right) → **Custom repositories**
3. Paste: `https://github.com/kane81/hacs-custom-amber-integration`
4. Category: **Integration** → **Add**
5. Search for **hacs-custom-amber-integration** → **Download**

HACS downloads the integration into `/config/custom_components/amber_integration/`.

**This is a one-time step.** Open **Terminal & SSH** and run the install script:

```bash
bash /config/custom_components/amber_integration/install.sh
```

The script will:
- Install python3 and pip3 if not already present
- Install the pycognito Python library
- Copy all automations, scripts, packages and templates to `/config/`
- Check your `configuration.yaml` for any missing lines and tell you exactly what to fix

**Verify it completed successfully** — the output should end with:
```
✅ Install complete!
```

If you see any ⚠️ warnings about missing `configuration.yaml` lines, follow the instructions printed by the script before continuing.

> **After this first run** the `amber_hacs_auto_install` automation is installed and active. All future HACS updates will trigger the install script automatically — you will never need to run it manually again.

---

### Step 3 — Update configuration.yaml

Open **Studio Code Server** from the sidebar. In the file explorer on the left open `/config/configuration.yaml`.

Make sure these two lines are present — add any that are missing:

**1. Load automations from the automations folder:**
```yaml
automation: !include_dir_merge_list automations/
```

> If you already have `automation: !include automations.yaml` replace that line with the one above.

**2. Load the integration package (helpers, shell commands, notify):**
```yaml
homeassistant:
  packages: !include_dir_named packages/
```

> If you already have a `homeassistant:` section, add just the `packages:` line underneath it.

Save with **Ctrl+S**.

---

### Step 4 — Add Credentials

#### Step 4a — Get your HA Long-Lived Access Token

The integration needs a token to communicate with Home Assistant's API.

1. Click your **profile avatar** (bottom left of the HA sidebar)
2. Scroll down to **Long-Lived Access Tokens**
3. Click **Create Token**
4. Name it `amber_smartshift` and click **OK**
5. **Copy the token immediately** — it will not be shown again

#### Step 4b — Add credentials to secrets.yaml

In **Studio Code Server**, open `/config/secrets.yaml` and add:

```yaml
amber_email: "your-email-you-use-to-login-to-the-amber-app"
amber_password: "your-password-you-use-to-login-to-the-amber-app"
ha_long_lived_token: "your-long-lived-access-token"

# Optional — only needed if adding email notifications
smtp_username: "your@gmail.com"
smtp_password: "your-app-password"
```

Save with **Ctrl+S**.


Restart HA: **Settings → System → Restart**

---

### Step 5 — Test Authentication

```bash
python3 /config/scripts/amber_auth.py
```

Expected output:
```
Authenticating as your@email.com...
Authentication successful
Site ID:   01K...
Config ID: 01K...
Token cached successfully
```

Then test a live price poll:

```bash
python3 /config/scripts/amber_graphql.py live
```

Expected output:
```
Buy:    28.5c/kWh
Sell:   5.2c/kWh
HA updated. Last polled: 2026-04-08 10:30:00
```

---

### Step 6 — Add Dashboard Card

The dashboard card shows live Amber prices, current interval cost/earnings, and the status of all automations at a glance.

![Dashboard Card](images/dashboard_card.jpeg)

**Icon legend:** 🟢 enabled & active · 🔴 enabled, waiting for conditions · 🚫 disabled

### Adding the card

1. Go to **Settings → Dashboards**
2. Open the dashboard you want to add the card to (or create a new one with **Add Dashboard**)
3. Click the **pencil icon** (top right) to enter edit mode
4. Click **+ Add Card**
5. Scroll down and select **Markdown**
6. Delete any placeholder text in the content field
7. Paste the full template below
8. Click **Save**

```jinja
{# --- Amber Prices --- #}
{% set buy_price    = states('input_number.amber_general_price_actual') | float(0) %}
{% set sell_price   = states('input_number.amber_feed_in_price_actual') | float(0) %}
{% set sell_display = (sell_price * 100) | round(0) | int if sell_price >= 0 else (sell_price * 100) | round(0, 'floor') | int %}
{% set soc          = states('input_number.amber_battery_soc') | float(0) %}
{# --- Current Interval Cost/Earnings (cents → dollars) --- #}
{% set import_cost     = states('input_number.amber_import_cost_cents') | float(0) %}
{% set export_earnings = states('input_number.amber_export_earnings_cents') | float(0) %}
{% set total_earnings  = states('input_number.amber_total_earnings_cents') | float(0) %}
{# --- Automation Thresholds --- #}
{% set min_sell_price  = states('input_number.amber_min_sell_price') | float(0.15) %}
{% set min_soc_to_sell = states('input_number.amber_min_soc_to_sell') | float(10) %}
{% set max_buy_price   = states('input_number.amber_max_buy_price_to_charge') | float(0.05) %}
{% set max_soc_charge  = states('input_number.amber_max_soc_to_charge') | float(100) %}
{# --- Time Windows (HH:MM only) --- #}
{% set fit_start      = states('input_datetime.amber_force_sell_on_custom_fit_start')[0:5] %}
{% set fit_end        = states('input_datetime.amber_force_sell_on_custom_fit_end')[0:5] %}
{% set ss_block_start = states('input_datetime.amber_block_smart_shift_start')[0:5] %}
{% set ss_block_end   = states('input_datetime.amber_block_smart_shift_end')[0:5] %}
{% set fc_start       = states('input_datetime.amber_force_charge_start')[0:5] %}
{% set fc_end         = states('input_datetime.amber_force_charge_end')[0:5] %}
{# --- Automation Enable Flags --- #}
{% set en_force_export  = is_state('input_boolean.amber_enable_force_export_custom_fit',    'on') %}
{% set en_block_ss      = is_state('input_boolean.amber_enable_block_smart_shift',          'on') %}
{% set en_neg_notify    = is_state('input_boolean.amber_enable_negative_price_notify',      'on') %}
{% set en_force_charge  = is_state('input_boolean.amber_enable_force_charge_custom_rate',   'on') %}
{# --- Automation Session State Flags --- #}
{% set force_export_active = is_state('input_boolean.amber_force_export_active', 'on') %}
{% set force_charge_active = is_state('input_boolean.amber_force_charge_active', 'on') %}
{% set ss_blocked          = is_state('input_boolean.amber_block_smart_shift_active', 'on') %}
{% set battery_offline     = is_state('input_boolean.amber_battery_offline', 'on') %}
{# --- Icon logic: 🚫 disabled · 🟢 active · 🔴 enabled/waiting · ⚠️ blocked --- #}
{% set ic_force_export = '⚠️' if (battery_offline and en_force_export) else ('🚫' if not en_force_export else ('🟢' if force_export_active else '🔴')) %}
{% set ic_force_charge = '⚠️' if (battery_offline and en_force_charge) else ('🚫' if not en_force_charge else ('🟢' if force_charge_active else '🔴')) %}
{% set ic_block_ss     = '⚠️' if (battery_offline and en_block_ss)     else ('🚫' if not en_block_ss     else ('🟢' if ss_blocked          else '🔴')) %}
{% set ic_neg_notify   = '🚫' if not en_neg_notify   else '🟢' %}

**💲 Amber**
&nbsp;&nbsp;Buy **{{ (buy_price * 100) | round(0) | int }}c** &nbsp;&nbsp; Sell **{{ sell_display }}c** &nbsp;&nbsp; SOC **{{ '⚠️' if battery_offline else (soc | round(0) | int ~ '%') }}**
{{ '&nbsp;&nbsp;⚠️ **Amber Battery Connection Offline**' if battery_offline else '' }}
&nbsp;&nbsp;Import **${{ '%.2f' | format(import_cost / 100) }}** &nbsp;&nbsp; Export **${{ '%.2f' | format((export_earnings / 100) | abs) }}** &nbsp;&nbsp; {{ '💰 Credit **$' ~ '%.2f' | format(total_earnings / 100) ~ '**' if total_earnings > 0 else '💸 Expense **$' ~ '%.2f' | format((total_earnings / 100) | abs) ~ '**' if total_earnings < 0 else '**$0.00**' }}
&nbsp;&nbsp;Last checked **{{ states('input_datetime.amber_last_polled') | as_timestamp | timestamp_custom('%I:%M %p') }}**

**🤖 Automations**
&nbsp;&nbsp;{{ ic_force_export }} **Export** >= {{ (min_sell_price * 100) | round(0) | int }}c · Min SOC {{ min_soc_to_sell | round(0) | int }}% · {{ fit_start }}–{{ fit_end }}
&nbsp;&nbsp;{{ ic_force_charge }} **Charge** <= {{ (max_buy_price * 100) | round(0) | int }}c · Max SOC {{ max_soc_charge | int }}% · {{ fc_start }}–{{ fc_end }}
&nbsp;&nbsp;{{ ic_block_ss }} **Block Smart Shift** - {{ ss_block_start }}–{{ ss_block_end }}{{ ' · Active' if ss_blocked else '' }}
&nbsp;&nbsp;{{ ic_neg_notify }} **Negative Price Notify**
```

---

#### Optional — Add Entity Controls to the Dashboard

Add toggle and number controls directly to your dashboard so you can control automations and adjust settings without navigating to Helpers. The automations in **Settings → Automations** should always remain enabled — control is via the **Enable Automation** toggles below. When OFF, the automation runs but exits immediately without doing anything.

The dashboard card shows live automation state using icon indicators — 🟢 active · 🔴 enabled/waiting · 🚫 disabled · ⚠️ blocked by battery offline.

For each group below, add an **Entities** card and include the listed entities.

> **Tip:** You can adjust the width of entity cards in edit mode — click the card → drag the resize handle, or use **Layout** options to set columns.

---

**Price Poller**
- `Amber Price Poller` — polls every 5 minutes and 30 seconds to get actual pricing rather than an estimate

---

**Block Smart Shift** — disables Smart Shift overnight to preserve battery charge for peak periods
- `Enable Automation: Block Smart Shift`
- `Amber Block Smart Shift Start`
- `Amber Block Smart Shift End`

---

**Force Export** — discharges battery to grid when sell price is at or above your threshold
- `Enable Automation: Force Export`
- `Amber Min Sell Price` — minimum sell price to trigger export
- `Amber Min SOC to Sell` — minimum battery % before stopping export
- `Amber Force Sell Start`
- `Amber Force Sell End`

---

**Force Charge** — charges battery from grid when buy price is at or below your threshold; switches to preserve mode at max SOC
- `Enable Automation: Force Charge`
- `Amber Max Buy Price` — maximum buy price to trigger charging
- `Amber Max SOC to Charge` — stop charging at this battery %
- `Amber Force Charge Start`
- `Amber Force Charge End`

---

**Notifications**
- `Enable Automation: Force Export Notifications` — notifications when force export starts, stops or fails
- `Enable Automation: Negative Price Notify` — notification when buy price goes negative

---

#### ⚠️ Note on the Automation Editor

When you open an automation from **Settings → Automations** you may see a warning that the automation was created outside the UI and cannot be edited here. This is expected — automations stored in YAML files under `/config/automations/` appear as read-only in the GUI. Leave them as-is.

---




## Testing the Integration

📐 [Click here to view the Architecture Diagram](images/architecture.png)

Optional — the following steps can be used to verify the integration is working end to end.

### Step 1 — Verify price polling is working

1. Go to **Settings → Automations** and confirm **Amber Price Poller** is listed
2. Check the dashboard card — buy and sell prices should be updating every 5 minutes
3. If prices are 0 or stale, run manually in Terminal:
   ```bash
   python3 /config/scripts/amber_graphql.py live
   ```

### Step 2 — Test Smart Shift control

This confirms your credentials are correct and the API can actually control your battery.

1. In Terminal, disable Smart Shift:
   ```bash
   python3 /config/scripts/amber_graphql.py smartshift_off
   ```
2. Open the **Amber app** on your phone → check that Smart Shift shows as **disabled**
3. Re-enable Smart Shift:
   ```bash
   python3 /config/scripts/amber_graphql.py smartshift_on
   ```
4. Check the Amber app again — Smart Shift should show as **enabled**

If both steps work your credentials and API connection are good and it is safe to enable automations.

## Manual Commands

These can be run from Terminal & SSH at any time:

```bash
python3 /config/scripts/amber_graphql.py status        # battery status and active overrides
python3 /config/scripts/amber_graphql.py live          # poll prices now
python3 /config/scripts/amber_graphql.py discharge 30  # force discharge for 30 minutes
python3 /config/scripts/amber_graphql.py charge 60     # force charge for 60 minutes
python3 /config/scripts/amber_graphql.py cancel        # cancel any active override
python3 /config/scripts/amber_graphql.py smartshift_on
python3 /config/scripts/amber_graphql.py smartshift_off
python3 /config/scripts/amber_auth.py                  # manually refresh auth token
```

---

## Troubleshooting

**Automations not appearing** — re-run the install script: `bash /config/custom_components/amber_integration/install.sh`. Confirm `automation: !include_dir_merge_list automations/` is in `configuration.yaml`, then restart HA.

**Auth fails on startup** — check `amber_email` and `amber_password` in `secrets.yaml`. Run `python3 /config/scripts/amber_auth.py` in Terminal to see the exact error.

**Prices not updating** — check the `Amber Price Poller` automation trace in Settings → Automations. Run `python3 /config/scripts/amber_graphql.py live` to test manually.

**Optional automation not firing** — confirm its enable toggle is ON in Overview → Devices → Helpers. Check the automation trace — the condition block shows exactly why it exited early.

**notify.notification unknown action error** — the package hasn't loaded yet. Reload: Developer Tools → YAML → Reload All.

**After any change to configuration.yaml** — Developer Tools → YAML → Reload All (or restart HA).

---

## License

MIT — see [LICENSE](LICENSE) file. Note the disclaimer above regarding the undocumented Amber API.

## Contributing

Issues and PRs welcome. Contributions should include testing against the current Amber app to verify API compatibility.
