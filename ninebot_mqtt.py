#!/usr/bin/env python3
"""Ninebot BLE → MQTT bridge for Home Assistant."""

import asyncio
import configparser
import json
import struct
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner
from ninebot_crypto import NinebotCrypto
from models import get_model, DERIVED_SENSORS, META_SENSORS
import paho.mqtt.client as mqtt

# === Load configuration ===
CONFIG_FILE = Path(__file__).parent / "config.ini"
if not CONFIG_FILE.exists():
    print(f"Config file not found: {CONFIG_FILE}")
    print("Run setup.py or copy config.sample.ini to config.ini and edit it.")
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_FILE)

SCOOTER_ADDRESS = config.get("scooter", "address")
SCOOTER_NAME = config.get("scooter", "name")
SCOOTER_MODEL = config.get("scooter", "model", fallback="g3")
CREDENTIALS_FILE = Path(__file__).parent / "ninebot_credentials.json"

MQTT_BROKER = config.get("mqtt", "broker")
MQTT_PORT = config.getint("mqtt", "port")
MQTT_USER = config.get("mqtt", "user", fallback="")
MQTT_PASS = config.get("mqtt", "password", fallback="")

POLL_INTERVAL = config.getint("timing", "poll_interval", fallback=1200)
SCAN_INTERVAL = config.getint("timing", "scan_interval", fallback=60)
SCAN_TIMEOUT = config.getfloat("timing", "scan_timeout", fallback=5.0)
CONNECT_TIMEOUT = config.getfloat("timing", "connect_timeout", fallback=20.0)
BLE_KEEP_ALIVE = config.getboolean("ble", "keep_alive", fallback=False)
BLE_RECONNECT_DELAY = config.getint("ble", "reconnect_delay", fallback=30)

MODEL = get_model(SCOOTER_MODEL)
WRITE_UUID = MODEL["ble"]["write_uuid"]
NOTIFY_UUIDS = MODEL["ble"]["notify_uuids"]
BLE_BOARD = MODEL["ble_board"]
BOARDS = MODEL["boards"]

# === BLE Protocol ===
HEADER = bytes([0x5A, 0xA5])
HOST = 0x3E
CMD_READ = 0x01
CMD_PRE_COMM = 0x5B
CMD_AUTH = 0x5D

response_queue = asyncio.Queue()
shutdown_event = asyncio.Event()


def notification_handler(sender, data: bytearray):
    response_queue.put_nowait(bytes(data))


def build_packet(src, dst, cmd, arg, data=b""):
    pkt_body = bytes([len(data), src, dst, cmd, arg]) + data
    return HEADER + pkt_body


async def receive_response(timeout=5.0):
    fragments = []
    try:
        first = await asyncio.wait_for(response_queue.get(), timeout=timeout)
        fragments.append(first)
        await asyncio.sleep(0.15)
        while not response_queue.empty():
            fragments.append(response_queue.get_nowait())
    except asyncio.TimeoutError:
        return None
    return b"".join(fragments)


async def authenticate(client, device_name):
    creds = None
    if CREDENTIALS_FILE.exists():
        creds = json.loads(CREDENTIALS_FILE.read_text())

    crypto = NinebotCrypto(device_name)

    pre_comm = build_packet(HOST, BLE_BOARD, CMD_PRE_COMM, 0x00)
    while not response_queue.empty():
        response_queue.get_nowait()
    encrypted = crypto.encrypt(pre_comm)
    await client.write_gatt_char(WRITE_UUID, encrypted, response=False)
    raw = await receive_response(timeout=5.0)
    if not raw:
        return None, None
    resp = crypto.decrypt(raw)
    if len(resp) < 23:
        return None, None

    auth_param = resp[7:23]
    serial_bytes = resp[23:37] if len(resp) >= 37 else b""
    serial = serial_bytes.decode('ascii', errors='ignore').rstrip('\x00')
    has_stored_pwd = resp[6] != 0

    if not (has_stored_pwd and creds and creds.get("serial") == serial):
        print("No valid credentials. Run setup.py or ninebot.py first to pair.")
        return None, None

    password = bytes.fromhex(creds["password"])
    crypto._calc_sha1_key(password[:16].ljust(16, b'\x00'), auth_param)
    crypto.ble_data = auth_param
    if crypto.msg_it == 0:
        crypto.msg_it = 1

    serial_data = serial.encode('ascii').ljust(14, b'\x00')[:14]
    auth = build_packet(HOST, BLE_BOARD, CMD_AUTH, 0x00, serial_data)
    while not response_queue.empty():
        response_queue.get_nowait()
    encrypted = crypto.encrypt(auth)
    await client.write_gatt_char(WRITE_UUID, encrypted, response=False)
    raw = await receive_response(timeout=5.0)
    if raw:
        resp = crypto.decrypt(raw)
        if len(resp) > 6 and resp[5] == CMD_AUTH and resp[6] == 0x01:
            return crypto, serial
    return None, None


async def read_register(client, crypto, board, register, size):
    pkt = build_packet(HOST, board, CMD_READ, register, bytes([size]))
    while not response_queue.empty():
        response_queue.get_nowait()
    encrypted = crypto.encrypt(pkt)
    await client.write_gatt_char(WRITE_UUID, encrypted, response=False)
    raw = await receive_response(timeout=3.0)
    if raw:
        decrypted = crypto.decrypt(raw)
        if len(decrypted) > 7:
            return decrypted[7:]
    return None


def setup_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{SCOOTER_NAME}_bridge")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def publish_discovery(mqtt_client):
    device_info = {
        "identifiers": [SCOOTER_NAME],
        "name": MODEL["name"],
        "manufacturer": MODEL["manufacturer"],
        "model": MODEL["model_id"],
    }

    state_topic = f"homeassistant/sensor/{SCOOTER_NAME}/state"
    sensors = []

    for s in MODEL["sensors"]:
        entry = {
            "name": s["name"],
            "unique_id": f"{SCOOTER_NAME}_{s['key']}",
            "value_template": "{{ value_json." + s["key"] + " }}",
        }
        if "unit" in s:
            entry["unit_of_measurement"] = s["unit"]
        if "device_class" in s:
            entry["device_class"] = s["device_class"]
        if "icon" in s:
            entry["icon"] = s["icon"]
        sensors.append(entry)

        if "derive" in s:
            for derived_key, derived_cfg in s["derive"].items():
                d_meta = DERIVED_SENSORS.get(derived_key, {})
                d_entry = {
                    "name": d_meta.get("name", derived_key),
                    "unique_id": f"{SCOOTER_NAME}_{derived_key}",
                    "value_template": "{{ value_json." + derived_key + " }}",
                }
                if "icon" in d_meta:
                    d_entry["icon"] = d_meta["icon"]
                sensors.append(d_entry)

    for ms in META_SENSORS:
        entry = {
            "name": ms["name"],
            "unique_id": f"{SCOOTER_NAME}_{ms['key']}",
            "value_template": "{{ value_json." + ms["key"] + " }}",
        }
        if "device_class" in ms:
            entry["device_class"] = ms["device_class"]
        if "icon" in ms:
            entry["icon"] = ms["icon"]
        sensors.append(entry)

    for sensor in sensors:
        sensor["device"] = device_info
        sensor["state_topic"] = state_topic
        topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_client.publish(topic, json.dumps(sensor), retain=True)

    print(f"Published HA discovery for {len(sensors)} sensors ({MODEL['name']})")


async def read_all_sensors(client, crypto):
    data = {}
    gear_modes = MODEL.get("gear_modes", {})

    for s in MODEL["sensors"]:
        board_addr = BOARDS[s["board"]]
        raw = await read_register(client, crypto, board_addr, s["reg"], s["size"])
        if not raw or len(raw) < s["size"]:
            continue

        value = struct.unpack(s["fmt"], raw[:struct.calcsize(s["fmt"])])[0]
        value = value * s["scale"]
        if "round" in s:
            value = round(value, s["round"])

        transform = s.get("transform")
        if transform == "gear_mode":
            data[s["key"]] = gear_modes.get(int(value), str(int(value)))
        elif transform == "bms_temp_packed":
            raw_val = struct.unpack(s["fmt"], raw[:struct.calcsize(s["fmt"])])[0]
            data[s["key"]] = (raw_val & 0xFF) - 20
        else:
            data[s["key"]] = value

        if "derive" in s:
            for derived_key, derived_cfg in s["derive"].items():
                if value > 0:
                    data[derived_key] = derived_cfg["positive"]
                else:
                    data[derived_key] = derived_cfg["negative"]

    return data


async def interruptible_sleep(seconds):
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def main():
    loop = asyncio.get_running_loop()

    def request_shutdown():
        print("\nShutting down...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(request_shutdown))

    mode = "keep-alive" if BLE_KEEP_ALIVE else "connect-per-poll"
    print(f"Ninebot MQTT Bridge ({MODEL['name']})")
    print(f"  Scooter: {SCOOTER_ADDRESS}")
    print(f"  Model:   {SCOOTER_MODEL}")
    print(f"  MQTT:    {MQTT_BROKER}:{MQTT_PORT}")
    print(f"  Poll:    {POLL_INTERVAL}s ({POLL_INTERVAL // 60} min)")
    print(f"  BLE:     {mode}")

    mqtt_client = setup_mqtt()
    publish_discovery(mqtt_client)

    state_topic = f"homeassistant/sensor/{SCOOTER_NAME}/state"
    avail_topic = f"homeassistant/sensor/{SCOOTER_NAME}/availability"

    while not shutdown_event.is_set():
        print("  Scanning for scooter...")
        device = None
        while not shutdown_event.is_set() and not device:
            device = await BleakScanner.find_device_by_address(
                SCOOTER_ADDRESS, timeout=SCAN_TIMEOUT)
            if not device:
                await interruptible_sleep(SCAN_INTERVAL)

        if shutdown_event.is_set():
            break

        device_name = device.name or "1CGBF2539C0792"
        print(f"  Scooter found! Connecting...")

        try:
            async with BleakClient(device, timeout=CONNECT_TIMEOUT) as client:
                try:
                    await client._backend._acquire_mtu()
                except Exception:
                    pass

                for uuid in NOTIFY_UUIDS:
                    await client.start_notify(uuid, notification_handler)
                await asyncio.sleep(0.3)

                crypto, serial = await authenticate(client, device_name)
                if not crypto:
                    print(f"  Auth failed, retrying in {BLE_RECONNECT_DELAY}s...")
                    await interruptible_sleep(BLE_RECONNECT_DELAY)
                    continue

                print(f"  Connected to {serial}")
                mqtt_client.publish(avail_topic, "online", retain=True)

                if BLE_KEEP_ALIVE:
                    while not shutdown_event.is_set() and client.is_connected:
                        try:
                            data = await read_all_sensors(client, crypto)
                            if data:
                                data["last_update"] = datetime.now(timezone.utc).isoformat()
                                mqtt_client.publish(state_topic, json.dumps(data))
                                print(f"  -> Bat={data.get('battery')}% "
                                      f"Range={data.get('range')}km "
                                      f"Spd={data.get('speed')}km/h")
                        except Exception as e:
                            print(f"  Read error: {e}")
                            break
                        await interruptible_sleep(POLL_INTERVAL)
                else:
                    try:
                        data = await read_all_sensors(client, crypto)
                        if data:
                            data["last_update"] = datetime.now(timezone.utc).isoformat()
                            mqtt_client.publish(state_topic, json.dumps(data))
                            print(f"  -> Bat={data.get('battery')}% "
                                  f"Range={data.get('range')}km "
                                  f"Spd={data.get('speed')}km/h")
                    except Exception as e:
                        print(f"  Read error: {e}")

        except Exception as e:
            print(f"  Connection lost: {e}")

        mqtt_client.publish(avail_topic, "offline", retain=True)

        if BLE_KEEP_ALIVE:
            print(f"  Disconnected. Reconnecting in {BLE_RECONNECT_DELAY}s...")
            await interruptible_sleep(BLE_RECONNECT_DELAY)
        else:
            print(f"  Done. Next poll in {POLL_INTERVAL}s...")
            await interruptible_sleep(POLL_INTERVAL)

    mqtt_client.publish(avail_topic, "offline", retain=True)
    mqtt_client.disconnect()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
