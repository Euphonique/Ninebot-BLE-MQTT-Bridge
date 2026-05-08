"""Ninebot scooter model profiles — board addresses, registers, BLE UUIDs."""

# BLE UUID sets
_NUS_UUIDS = {
    "write_uuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "notify_uuids": [
        "6e400004-0000-0000-006e-696e65626f74",
        "6e400006-0000-0000-006e-696e65626f74",
        "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    ],
}

_NB_UUIDS = {
    "write_uuid": "6e400002-0000-0000-006e-696e65626f74",
    "notify_uuids": [
        "6e400004-0000-0000-006e-696e65626f74",
        "6e400006-0000-0000-006e-696e65626f74",
    ],
}

# Shared sensor templates for Gen1 (ESC-based) models
_GEN1_ESC_SENSORS = [
    {"key": "speed",         "board": "esc", "reg": 0x26, "size": 2, "fmt": "<h",
     "name": "Speed", "unit": "km/h", "device_class": "speed", "icon": "mdi:speedometer"},
    {"key": "range",         "board": "esc", "reg": 0x25, "size": 2, "fmt": "<H", "scale": 0.01,
     "name": "Range", "unit": "km", "device_class": "distance", "icon": "mdi:map-marker-distance"},
    {"key": "odometer",      "board": "esc", "reg": 0x29, "size": 4, "fmt": "<I", "scale": 0.001,
     "name": "Odometer", "unit": "km", "device_class": "distance", "icon": "mdi:counter"},
    {"key": "body_temp",     "board": "esc", "reg": 0x3E, "size": 2, "fmt": "<h", "scale": 0.1,
     "name": "Body Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
    {"key": "trip_distance", "board": "esc", "reg": 0xB9, "size": 2, "fmt": "<H", "scale": 0.01,
     "name": "Trip Distance", "unit": "km", "device_class": "distance", "icon": "mdi:map-marker-path"},
    {"key": "runtime",       "board": "esc", "reg": 0x32, "size": 4, "fmt": "<I", "scale": 1/3600, "round": 1,
     "name": "Total Runtime", "unit": "h", "icon": "mdi:clock-start"},
    {"key": "ride_time",     "board": "esc", "reg": 0x34, "size": 4, "fmt": "<I", "scale": 1/3600, "round": 1,
     "name": "Total Ride Time", "unit": "h", "icon": "mdi:scooter"},
    {"key": "gear_mode",     "board": "esc", "reg": 0x75, "size": 2, "fmt": "<H", "scale": 1,
     "name": "Gear Mode", "icon": "mdi:car-shift-pattern", "transform": "gear_mode"},
    {"key": "error_code",    "board": "esc", "reg": 0x1B, "size": 2, "fmt": "<H", "scale": 1,
     "name": "Error Code", "icon": "mdi:alert-circle"},
    {"key": "warn_code",     "board": "esc", "reg": 0x1C, "size": 2, "fmt": "<H", "scale": 1,
     "name": "Warning Code", "icon": "mdi:alert"},
]

_GEN1_BMS_SENSORS = [
    {"key": "voltage",       "board": "bms", "reg": 0x34, "size": 2, "fmt": "<H", "scale": 0.01,
     "name": "Battery Voltage", "unit": "V", "device_class": "voltage", "icon": "mdi:flash"},
    {"key": "current",       "board": "bms", "reg": 0x33, "size": 2, "fmt": "<h", "scale": 0.01,
     "name": "Battery Current", "unit": "A", "device_class": "current", "icon": "mdi:current-dc",
     "derive": {"charging": {"positive": "on", "negative": "off"}}},
    {"key": "charge_cycles", "board": "bms", "reg": 0x1B, "size": 2, "fmt": "<H", "scale": 1,
     "name": "Charge Cycles", "icon": "mdi:battery-sync"},
    {"key": "bms_temp",      "board": "bms", "reg": 0x35, "size": 2, "fmt": "<H", "scale": 1,
     "name": "BMS Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer",
     "transform": "bms_temp_packed"},
    {"key": "battery_health","board": "bms", "reg": 0x3B, "size": 2, "fmt": "<H", "scale": 1,
     "name": "Battery Health", "unit": "%", "icon": "mdi:battery-heart-variant"},
]


def _gen1_sensors(battery_board, battery_reg, speed_scale):
    """Build sensor list for a Gen1 model with model-specific overrides."""
    battery = {"key": "battery", "board": battery_board, "reg": battery_reg, "size": 2, "fmt": "<H", "scale": 1,
               "name": "Battery", "unit": "%", "device_class": "battery"}
    sensors = [battery]
    for s in _GEN1_ESC_SENSORS:
        entry = dict(s)
        if entry["key"] == "speed":
            entry["scale"] = speed_scale
        sensors.append(entry)
    sensors.extend(dict(s) for s in _GEN1_BMS_SENSORS)
    return sensors


MODELS = {
    # ═══════════════════ Generation 2 (VCU-based) ═══════════════════

    "g3": {
        "name": "Ninebot Max G3",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter MAX G3",
        "serial_prefixes": ["1CG"],
        "ble": _NUS_UUIDS,
        "ble_board": 0x04,
        "boards": {"vcu": 0x00, "bms": 0x07, "mcu": 0x02},
        "gear_modes": {1: "Walk", 2: "Eco", 3: "Off", 4: "Sport", 5: "Drive"},
        "sensors": [
            # ── VCU ──
            {"key": "battery",       "board": "vcu", "reg": 0x55, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Battery", "unit": "%", "device_class": "battery"},
            {"key": "speed",         "board": "vcu", "reg": 0x57, "size": 2, "fmt": "<H", "scale": 0.1,
             "name": "Speed", "unit": "km/h", "device_class": "speed", "icon": "mdi:speedometer"},
            {"key": "range",         "board": "vcu", "reg": 0x5F, "size": 4, "fmt": "<I", "scale": 0.01, "round": 1,
             "name": "Range", "unit": "km", "device_class": "distance", "icon": "mdi:map-marker-distance"},
            {"key": "odometer",      "board": "vcu", "reg": 0x62, "size": 4, "fmt": "<I", "scale": 0.1,
             "name": "Odometer", "unit": "km", "device_class": "distance", "icon": "mdi:counter"},
            {"key": "body_temp",     "board": "vcu", "reg": 0x6B, "size": 2, "fmt": "<h", "scale": 0.1,
             "name": "Body Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"key": "trip_distance", "board": "vcu", "reg": 0x68, "size": 2, "fmt": "<H", "scale": 0.01,
             "name": "Trip Distance", "unit": "km", "device_class": "distance", "icon": "mdi:map-marker-path"},
            {"key": "trip_time",     "board": "vcu", "reg": 0x6A, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Trip Time", "unit": "min", "icon": "mdi:timer-outline"},
            {"key": "runtime",       "board": "vcu", "reg": 0x64, "size": 4, "fmt": "<I", "scale": 1/36000, "round": 1,
             "name": "Total Runtime", "unit": "h", "icon": "mdi:clock-start"},
            {"key": "ride_time",     "board": "vcu", "reg": 0x66, "size": 4, "fmt": "<I", "scale": 1/3600, "round": 1,
             "name": "Total Ride Time", "unit": "h", "icon": "mdi:scooter"},
            {"key": "gear_mode",     "board": "vcu", "reg": 0x5A, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Gear Mode", "icon": "mdi:car-shift-pattern", "transform": "gear_mode"},
            {"key": "error_code",    "board": "vcu", "reg": 0x58, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Error Code", "icon": "mdi:alert-circle"},
            {"key": "warn_code",     "board": "vcu", "reg": 0x59, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Warning Code", "icon": "mdi:alert"},
            {"key": "lock_status",   "board": "vcu", "reg": 0x1D, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Lock Status", "icon": "mdi:lock", "transform": "lock_bit"},
            {"key": "led_mode",      "board": "vcu", "reg": 0x5B, "size": 2, "fmt": "<H", "scale": 1,
             "name": "LED Mode", "icon": "mdi:lightbulb"},
            {"key": "tail_light",    "board": "vcu", "reg": 0x5D, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Tail Light Mode", "icon": "mdi:car-light-dimmed"},
            {"key": "auto_off_time", "board": "vcu", "reg": 0x49, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Auto Power Off", "unit": "min", "icon": "mdi:timer-off-outline"},
            {"key": "fw_vcu",        "board": "vcu", "reg": 0x17, "size": 2, "fmt": "<H", "scale": 1,
             "name": "VCU Firmware", "icon": "mdi:chip", "transform": "fw_version"},
            {"key": "fw_mcu",        "board": "vcu", "reg": 0x18, "size": 2, "fmt": "<H", "scale": 1,
             "name": "MCU Firmware", "icon": "mdi:chip", "transform": "fw_version"},
            {"key": "fw_bms",        "board": "vcu", "reg": 0x19, "size": 2, "fmt": "<H", "scale": 1,
             "name": "BMS Firmware", "icon": "mdi:chip", "transform": "fw_version"},
            # ── BMS ──
            {"key": "voltage",       "board": "bms", "reg": 0x8C, "size": 2, "fmt": "<H", "scale": 0.01,
             "name": "Battery Voltage", "unit": "V", "device_class": "voltage", "icon": "mdi:flash"},
            {"key": "current",       "board": "bms", "reg": 0x8D, "size": 2, "fmt": "<h", "scale": 0.01,
             "name": "Battery Current", "unit": "A", "device_class": "current", "icon": "mdi:current-dc",
             "derive": {"charging": {"positive": "on", "negative": "off"}}},
            {"key": "charge_cycles", "board": "bms", "reg": 0x59, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Charge Cycles", "icon": "mdi:battery-sync"},
            {"key": "bms_temp",      "board": "bms", "reg": 0x96, "size": 4, "fmt": "<h", "scale": 1,
             "name": "BMS Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"key": "factory_capacity",   "board": "bms", "reg": 0x5A, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Factory Capacity", "unit": "mAh", "icon": "mdi:battery-plus-variant"},
            {"key": "available_capacity", "board": "bms", "reg": 0x5B, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Available Capacity", "unit": "mAh", "icon": "mdi:battery"},
            {"key": "remaining_capacity", "board": "bms", "reg": 0x8A, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Remaining Capacity", "unit": "mAh", "icon": "mdi:battery-heart-variant"},
            {"key": "time_to_full",  "board": "bms", "reg": 0x94, "size": 2, "fmt": "<H", "scale": 1,
             "name": "Time to Full Charge", "unit": "min", "icon": "mdi:battery-clock"},
            {"key": "energy_throughput",  "board": "bms", "reg": 0xE3, "size": 4, "fmt": "<I", "scale": 1,
             "name": "Lifetime Energy", "unit": "Wh", "icon": "mdi:lightning-bolt"},
            # ── MCU (Motor) ──
            {"key": "motor_temp_a",  "board": "mcu", "reg": 0x48, "size": 2, "fmt": "<h", "scale": 0.1, "round": 1,
             "name": "Motor Temp A", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"key": "motor_temp_b",  "board": "mcu", "reg": 0x49, "size": 2, "fmt": "<h", "scale": 0.1, "round": 1,
             "name": "Motor Temp B", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
        ],
    },

    # ═══════════════════ Generation 1 (ESC-based) ═══════════════════

    "g30": {
        "name": "Ninebot Max G30",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter MAX G30",
        "serial_prefixes": ["N4G"],
        "ble": _NB_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Lock", 1: "Eco", 2: "Normal", 3: "Sport"},
        "sensors": _gen1_sensors(battery_board="esc", battery_reg=0x22, speed_scale=0.001),
    },

    "g2": {
        "name": "Ninebot Max G2",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter MAX G2",
        "serial_prefixes": ["N4GM"],
        "ble": _NB_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Lock", 1: "Eco", 2: "Normal", 3: "Sport"},
        "sensors": _gen1_sensors(battery_board="esc", battery_reg=0x22, speed_scale=0.001),
    },

    "g65": {
        "name": "Ninebot Max G65",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter MAX G65",
        "serial_prefixes": ["N4GS"],
        "ble": _NB_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Lock", 1: "Eco", 2: "Normal", 3: "Sport"},
        "sensors": _gen1_sensors(battery_board="esc", battery_reg=0x22, speed_scale=0.001),
    },

    "f2": {
        "name": "Ninebot F2",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter F2",
        "serial_prefixes": ["N5G"],
        "ble": _NUS_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Normal", 1: "Eco", 2: "Sport"},
        "sensors": _gen1_sensors(battery_board="bms", battery_reg=0x32, speed_scale=0.1),
    },

    "e": {
        "name": "Ninebot E-Serie",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter E-Series",
        "serial_prefixes": ["N2GZ", "N2GQ", "N2G"],
        "ble": _NB_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Normal", 1: "Eco", 2: "Sport"},
        "sensors": _gen1_sensors(battery_board="esc", battery_reg=0x22, speed_scale=0.1),
    },

    "es": {
        "name": "Ninebot ES-Serie",
        "manufacturer": "Segway-Ninebot",
        "model_id": "KickScooter ES-Series",
        "serial_prefixes": ["N2G"],
        "ble": _NB_UUIDS,
        "ble_board": 0x21,
        "boards": {"esc": 0x20, "bms": 0x22},
        "gear_modes": {0: "Normal", 1: "Eco", 2: "Sport"},
        "sensors": _gen1_sensors(battery_board="esc", battery_reg=0x22, speed_scale=0.1),
    },
}

DERIVED_SENSORS = {
    "charging": {
        "name": "Charging",
        "icon": "mdi:battery-charging",
    },
}

META_SENSORS = [
    {"key": "avg_speed", "name": "Avg Speed (Trip)", "unit": "km/h", "device_class": "speed", "icon": "mdi:speedometer-slow"},
    {"key": "last_update", "name": "Last Update", "device_class": "timestamp", "icon": "mdi:clock-outline"},
]


def get_model(model_key):
    model_key = model_key.lower().strip()
    if model_key not in MODELS:
        available = ", ".join(MODELS.keys())
        raise ValueError(f"Unknown model '{model_key}'. Available: {available}")
    return MODELS[model_key]


def detect_model(serial):
    """Detect model from serial number prefix. Returns (key, model) or None."""
    serial = serial.upper().strip()
    candidates = []
    for key, model in MODELS.items():
        for prefix in model.get("serial_prefixes", []):
            if serial.startswith(prefix):
                candidates.append((len(prefix), key, model))
    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        _, key, model = candidates[0]
        return key, model
    return None


def list_models():
    return [(k, m["name"]) for k, m in MODELS.items()]
