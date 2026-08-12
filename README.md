# Kinetico Powerline Pro

Home Assistant custom integration for Kinetico Powerline Pro series water softeners.

## Status

🚀 **Beta Release** — Core authentication and read functionality are verified.

## How It Works

This integration communicates with Kinetico Powerline water treatment devices
over **Bluetooth Low Energy (BLE)** using the Nordic UART Service (NUS). The
protocol was reverse-engineered from the official Kinetico Powerline PRO
Android app.

### Supported Devices

- **Metered Softener** (Tested & Verified)

*Note: The integration code may support other Kinetico devices (like Timeclock Softener, Backwashing Filter, Ultra Filter, etc.), but currently only the Metered Softener has been actively tested and verified.*

### Sensors Exposed

- Days until next regeneration
- Days since last regeneration
- Water hardness (GPG)
- Capacity remaining (grains)
- Salt status (OK / Low)
- Regeneration status (active / idle)
- Firmware version
- Device type

### Controls

- Trigger regeneration (now / next scheduled)
- Set salt level
- Sync clock

## Installation

This integration is built to be installed via **HACS** (Home Assistant Community Store).

1. Open HACS in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add this repository's URL (`https://github.com/highamperage/ha-kinetico-powerline`) and choose **Integration** as the category.
4. Click **Add** and then download the integration.
5. Restart Home Assistant.
6. Go to **Settings > Devices & Services > Add Integration** and search for "Kinetico Powerline Pro".

*(Note: Ensure your Home Assistant host has a working Bluetooth adapter and the official **Bluetooth** integration is set up!)*

## Authentication Note
This integration implements the Kinetico LFSR authentication protocol for firmware v4.20+. 
If you have set a custom PIN in the Kinetico app, you will need to provide it during setup. If you have not set a custom PIN, the integration will seamlessly authenticate using the default PIN (`1234`).

## Requirements

- **BLE adapter**: Any Bluetooth 4.0+ adapter (and the Home Assistant **Bluetooth** integration must be installed and configured)
- **Python 3.10+**
- **bleak** (BLE library, installed automatically by HA)

## License

MIT

---

*Disclaimer: AI was used to assist in building this project.*
