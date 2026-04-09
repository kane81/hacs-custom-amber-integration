## ⚠️ Before You Install

**This integration uses Amber Electric's internal API which is not publicly documented or supported.**

- Amber may change or remove it at any time without notice
- This project has no affiliation with Amber Electric

**Use at your own risk.**

---

## 📋 Manual Steps Required After Install

This is not a plug-and-play integration. After clicking Download you will need to:

1. Open **Terminal & SSH** and run the install script:
   ```
   bash /config/custom_components/amber_integration/install.sh
   ```
2. Add two lines to `configuration.yaml` (Studio Code Server)
3. Add your Amber credentials to `secrets.yaml`
4. Restart Home Assistant

Full instructions are in the [README](https://github.com/kane81/hacs-custom-amber-integration#readme).

---

## ✅ Requirements

- Active Amber Electric subscription with Smart Shift enabled
- Smart Shift compatible battery enrolled in the Amber app
- Home Assistant OS or Supervised
- Studio Code Server add-on (file editing)
- Terminal & SSH add-on (running the install script)
