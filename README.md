# Ninebot BLE-MQTT Bridge for Home Assistant

Connect your Ninebot/Segway scooter to Home Assistant via BLE and MQTT.

## Supported Models

| Model | Key | Protocol | Status |
|-------|-----|----------|--------|
| Max G3 | `g3` | Gen2 (VCU) | Tested |
| Max G30 / G30D / G30LP | `g30` | Gen1 (ESC) | Community |
| Max G2 / G2E | `g2` | Gen1 (ESC) | Community |
| Max G65 | `g65` | Gen1 (ESC) | Community |
| F2 / F2 Plus / F2 Pro | `f2` | Gen1 (ESC) | Community |
| E22 / E25 / E45 | `e` | Gen1 (ESC) | Community |
| ES2 / ES4 | `es` | Gen1 (ESC) | Community |

The model is auto-detected from the scooter's serial number during pairing.

## Sensors

Battery, Speed, Range, Odometer, Temperature, Trip Distance, Trip Time, Total Runtime, Total Ride Time, Gear Mode, Error/Warning Codes, Voltage, Current, Charging State, Charge Cycles, BMS Temperature, Battery Health.

## Quick Start

```bash
python setup.py
```

The interactive setup will guide you through:

1. **Dependencies** — creates a virtualenv and installs `bleak`, `paho-mqtt`, `cryptography`
2. **BLE Scan** — finds your scooter or lets you enter the MAC address manually
3. **Model Selection** — pick your scooter model (auto-detected during pairing)
4. **MQTT** — configure broker, port, credentials
5. **BLE Options** — keep-alive vs. connect-per-poll, reconnect delay
6. **Pairing** — authenticate with your scooter (press the power button when prompted)
7. **Systemd Service** — optional, for running as a background service on Linux

## Manual Setup

1. Copy `config.sample.ini` to `config.ini` and edit it
2. Run `python ninebot.py` to pair with your scooter
3. Run `python ninebot_mqtt.py` to start the bridge

## Configuration

All settings are in `config.ini`:

```ini
[scooter]
address = XX:XX:XX:XX:XX:XX    # BLE MAC address
model = g3                      # g3, g30, g2, g65, f2, e, es
name = ninebot_max_g3           # HA entity prefix

[mqtt]
broker = 192.168.1.100
port = 1883
user =
password =

[timing]
poll_interval = 1200            # seconds between reads (default: 20 min)
scan_interval = 60              # seconds between scans when searching
scan_timeout = 5.0
connect_timeout = 20.0

[ble]
keep_alive = false              # true = stay connected, false = connect per poll
reconnect_delay = 30            # seconds before reconnect after connection loss
```

### BLE Modes

- **`keep_alive = false`** (default) — connects, reads sensors, disconnects. Best for long poll intervals. Saves scooter battery.
- **`keep_alive = true`** — stays connected between polls. Faster reads, but drains scooter battery and blocks other BLE connections.

## Files

| File | Purpose |
|------|---------|
| `setup.py` | Interactive setup wizard |
| `ninebot_mqtt.py` | Main MQTT bridge (runs as service) |
| `ninebot.py` | Pairing & test read tool |
| `ninebot_crypto.py` | BLE encryption/decryption |
| `models.py` | Scooter model profiles (registers, UUIDs) |
| `config.sample.ini` | Configuration template |
| `ninebot-mqtt.service` | Systemd service file |
| `lovelace_card.yaml` | Home Assistant dashboard card |

## Home Assistant Dashboard

Import `lovelace_card.yaml` for a pre-built vehicle status card. Requires the [Vehicle Status Card](https://github.com/ngocjohn/vehicle-status-card) custom component.

## Requirements

- Python 3.9+
- Linux with BlueZ (Raspberry Pi recommended) or Windows/macOS
- MQTT broker (e.g. Mosquitto)
- Home Assistant with MQTT integration

## Systemd Service (Linux)

```bash
sudo cp ninebot-mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ninebot-mqtt
```

## Contributing

If you have a scooter model that isn't listed or the sensor values seem wrong, please open an issue with:
- Your scooter model and serial number prefix
- Which sensors work/don't work
- Any raw register data from `ninebot.py`

## License

MIT
