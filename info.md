## ⚠️ Important — Manual Step Required After Download

After clicking **Download**, you **must** run the install script from **Advanced SSH & Web Terminal**:

```bash
bash /config/custom_components/amber_integration/install.sh
```

The script will prompt you for your credentials, set up the dashboard, configure automations and test the connection. **Do not restart Home Assistant before running the script.**

Full step-by-step instructions: [README](https://github.com/kane81/hacs-custom-amber-integration#readme)

---

## ⚠️ Disclaimer

This integration uses Amber Electric's internal API which is not publicly documented or officially supported. Amber may change or remove it at any time without notice. This project has no affiliation with Amber Electric. Use at your own risk.

---

## ✅ Requirements

- Active Amber Electric subscription with Smart Shift enabled
- Smart Shift compatible battery enrolled in the Amber app
- Home Assistant OS or Supervised
- Advanced SSH & Web Terminal add-on
