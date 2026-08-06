## After downloading

**1. Restart Home Assistant.** The integration only appears after a restart.

**2. Add the integration.** Settings → Devices & Services → **+ Add Integration** → search **Amber** → pick **HA Custom Amber Electric Integration** (not Home Assistant's built-in Amber Electric, which can't control your battery). Sign in with your Amber app email and password.

That's it for the core integration — you now have live prices, battery status, and manual charge/discharge/preserve/self-consume controls.

## Optional: automations and dashboard

If you also want the ready-made price automations and dashboard, run this once from a terminal:

```
bash /config/custom_components/amber_integration/install.sh
```

then restart again. It installs three blueprint automations and a dashboard — nothing else. No login, no token.

See the [README](https://github.com/kane81/hacs-custom-amber-integration#readme) for full details.
