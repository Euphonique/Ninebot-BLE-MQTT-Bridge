#!/usr/bin/env python3
"""Ninebot BLE — pairing and test read."""

import asyncio
import configparser
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner
from ninebot_crypto import NinebotCrypto

# === Load configuration ===
CONFIG_FILE = Path(__file__).parent / "config.ini"
if not CONFIG_FILE.exists():
    print(f"Config file not found: {CONFIG_FILE}")
    print("Copy config.ini.example to config.ini and edit it.")
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_FILE)

from models import get_model, detect_model

SCOOTER_ADDRESS = config.get("scooter", "address")
SCOOTER_MODEL = config.get("scooter", "model", fallback="g3")
CREDENTIALS_FILE = Path(__file__).parent / "ninebot_credentials.json"

MODEL = get_model(SCOOTER_MODEL)
WRITE_UUID = MODEL["ble"]["write_uuid"]
NOTIFY_UUIDS = MODEL["ble"]["notify_uuids"]
BLE_BOARD = MODEL["ble_board"]
BOARDS = MODEL["boards"]

HEADER = bytes([0x5A, 0xA5])
HOST = 0x3E

CMD_READ = 0x01
CMD_PRE_COMM = 0x5B
CMD_SET_PWD = 0x5C
CMD_AUTH = 0x5D

response_queue = asyncio.Queue()


def notification_handler(sender, data: bytearray):
    print(f"    [RAW NOTIFY {len(data)}b]: {bytes(data).hex()}")
    response_queue.put_nowait(bytes(data))


def build_packet(src: int, dst: int, cmd: int, arg: int, data: bytes = b"") -> bytes:
    pkt_body = bytes([len(data), src, dst, cmd, arg]) + data
    return HEADER + pkt_body


class JavaRandom:
    """Java LCG PRNG (java.util.Random)."""
    def __init__(self, seed):
        self.seed = (seed ^ 0x5DEECE66D) & ((1 << 48) - 1)

    def _next(self, bits):
        self.seed = (self.seed * 0x5DEECE66D + 0xB) & ((1 << 48) - 1)
        return self.seed >> (48 - bits)

    def next_bytes(self, count):
        result = bytearray(count)
        i = 0
        while i < count:
            rnd = self._next(32)
            n = min(count - i, 4)
            for j in range(n):
                result[i] = (rnd >> (8 * j)) & 0xFF
                i += 1
        return bytes(result)


def generate_password(auth_param: bytes) -> bytes:
    time_ms = int(time.time() * 1000)
    seed_value = 0
    for i, b in enumerate(auth_param):
        signed_byte = b if b < 128 else b - 256
        shift = (i % 8) * 8
        val = signed_byte << (shift & 31)
        seed_value += val
    seed = time_ms + seed_value
    rng = JavaRandom(seed)
    random_bytes = rng.next_bytes(16)
    return hashlib.sha256(random_bytes).digest()[:16]


def load_credentials():
    if CREDENTIALS_FILE.exists():
        return json.loads(CREDENTIALS_FILE.read_text())
    return None


def save_credentials(serial: str, password: bytes):
    data = {"serial": serial, "password": password.hex()}
    CREDENTIALS_FILE.write_text(json.dumps(data))
    print(f"  Credentials saved!")


def _expected_packet_len(header_bytes: bytes) -> int:
    if len(header_bytes) >= 3:
        return header_bytes[2] + 13
    return 0


async def receive_response(timeout=5.0):
    buf = bytearray()
    try:
        first = await asyncio.wait_for(response_queue.get(), timeout=timeout)
        buf.extend(first)
        expected = _expected_packet_len(buf)
        while len(buf) < expected:
            try:
                frag = await asyncio.wait_for(response_queue.get(), timeout=0.5)
                buf.extend(frag)
            except asyncio.TimeoutError:
                break
    except asyncio.TimeoutError:
        return None
    expected = _expected_packet_len(buf)
    if len(buf) > expected > 0:
        remainder = bytes(buf[expected:])
        response_queue.put_nowait(remainder)
        return bytes(buf[:expected])
    return bytes(buf)


async def send_and_receive(client, crypto, packet, timeout=5.0):
    while not response_queue.empty():
        response_queue.get_nowait()
    encrypted = crypto.encrypt(packet)
    print(f"    [SEND {len(encrypted)}b ctr={crypto.msg_it}]: {encrypted.hex()}")
    await client.write_gatt_char(WRITE_UUID, encrypted, response=False)
    raw = await receive_response(timeout=timeout)
    if raw:
        decrypted = crypto.decrypt(raw)
        print(f"    [DECRYPTED {len(decrypted)}b]: {decrypted.hex()}")
        return decrypted
    return None


async def authenticate(client, device_name):
    creds = load_credentials()
    crypto = NinebotCrypto(device_name)
    # fw_data key is set by default in NinebotCrypto.__init__

    # Phase 1: PRE_COMM
    print("\n[Phase 1] PRE_COMM...")
    pre_comm = build_packet(HOST, BLE_BOARD, CMD_PRE_COMM, 0x00)
    resp = await send_and_receive(client, crypto, pre_comm)

    if not resp:
        print("  No response!")
        return None, None

    print(f"  Response ({len(resp)}b): {resp.hex()}")

    if len(resp) < 7:
        print("  Response too short!")
        return None, None

    resp_cmd = resp[5]
    resp_idx = resp[6]
    print(f"  cmd=0x{resp_cmd:02X}, idx={resp_idx}")

    if resp_cmd != CMD_PRE_COMM:
        print(f"  Unexpected command!")
        return None, None

    # Extract auth_param (16 bytes) and serial (14 bytes)
    auth_param = resp[7:23]
    serial_bytes = resp[23:37] if len(resp) >= 37 else b""
    serial = serial_bytes.decode('ascii', errors='ignore').rstrip('\x00')
    print(f"  Auth param: {auth_param.hex()}")
    print(f"  Serial: {serial}")
    print(f"  Has stored password: {resp_idx != 0}")

    detected = detect_model(serial)
    if detected:
        det_key, det_model = detected
        print(f"  Auto-detected model: {det_model['name']} ({det_key})")
        if det_key != SCOOTER_MODEL:
            print(f"  NOTE: config.ini has model={SCOOTER_MODEL}, but serial suggests {det_key}.")
            print(f"        Update config.ini [scooter] model = {det_key} if needed.")
    else:
        print(f"  Could not auto-detect model from serial '{serial}'.")

    has_stored_pwd = resp_idx != 0

    if has_stored_pwd and creds and creds.get("serial") == serial:
        # Reconnect flow: skip SET_PWD
        print("\n[Phase 2] SKIPPED - Using stored password")
        password = bytes.fromhex(creds["password"])

        # Set key for AUTH: SHA-1(password, auth_param)
        crypto._calc_sha1_key(password[:16].ljust(16, b'\x00'), auth_param)
        crypto.ble_data = auth_param
        # Counter should be at 1 (start_sn), next encrypt will use 2
        if crypto.msg_it == 0:
            crypto.msg_it = 1
    else:
        # Key for SET_PWD: SHA-1(device_name, auth_param)
        crypto._calc_sha1_key(crypto.name_data, auth_param)
        crypto.ble_data = auth_param

        # Phase 2: SET_PWD
        print("\n[Phase 2] SET_PWD...")
        if has_stored_pwd:
            print("  NOTE: Scooter already has a stored pairing.")
            print("  The display may NOT show a pairing prompt — press the button anyway!")
        print("  >>> PRESS THE POWER BUTTON ON YOUR SCOOTER NOW! <<<")

        password = generate_password(auth_param)
        set_pwd = build_packet(HOST, BLE_BOARD, CMD_SET_PWD, 0x00, password)
        crypto.set_app_data(password)

        accepted = False
        for attempt in range(30):
            resp = await send_and_receive(client, crypto, set_pwd, timeout=2.0)

            # Also check if a queued response (from packet splitting) is the acceptance
            if not resp or (len(resp) > 6 and resp[5] == CMD_SET_PWD and resp[6] != 0x01):
                if not response_queue.empty():
                    queued = response_queue.get_nowait()
                    decrypted = crypto.decrypt(queued)
                    print(f"    [QUEUED {len(decrypted)}b]: {decrypted.hex()}")
                    if len(decrypted) > 6 and decrypted[5] == CMD_SET_PWD and decrypted[6] == 0x01:
                        resp = decrypted

            if resp and len(resp) > 6 and resp[5] == CMD_SET_PWD:
                if resp[6] == 0x01:
                    print("  Password ACCEPTED!")
                    accepted = True
                    break
                else:
                    print(f"  Waiting for button... ({attempt + 1}/30)")
            else:
                if resp:
                    print(f"  Unexpected: {resp.hex()}")
                else:
                    print(f"  Polling... ({attempt + 1}/30)")

        if not accepted:
            print("  Timeout — button press was not detected.")
            if has_stored_pwd:
                print("  The scooter may need a Bluetooth reset first:")
                print("    - Use the Segway-Ninebot app to unpair, OR:")
                print("    - Hold the POWER BUTTON for 10+ seconds to reset Bluetooth")
                print("  Then run this setup again.")
            return None, None

        save_credentials(serial, password)

        # Key for AUTH: SHA-1(password, auth_param)
        crypto._calc_sha1_key(password[:16].ljust(16, b'\x00'), auth_param)

    # Phase 3: AUTH
    print("\n[Phase 3] AUTH...")
    serial_data = serial.encode('ascii').ljust(14, b'\x00')[:14]
    auth = build_packet(HOST, BLE_BOARD, CMD_AUTH, 0x00, serial_data)
    resp = await send_and_receive(client, crypto, auth)

    if resp and len(resp) > 6 and resp[5] == CMD_AUTH:
        if resp[6] == 0x01:
            print("  AUTHENTICATED!")
            return crypto, serial
        else:
            print(f"  Auth failed (idx={resp[6]})")
            if CREDENTIALS_FILE.exists():
                CREDENTIALS_FILE.unlink()
            return None, None
    else:
        print(f"  No auth response: {resp.hex() if resp else 'None'}")
        if CREDENTIALS_FILE.exists():
            print("  Stored credentials may be invalid — removing them.")
            CREDENTIALS_FILE.unlink()
        return None, None


async def read_register(client, crypto, board, register, size, timeout=5.0):
    """Read a register via Nordic UART."""
    pkt = build_packet(HOST, board, CMD_READ, register, bytes([size]))
    while not response_queue.empty():
        response_queue.get_nowait()
    encrypted = crypto.encrypt(pkt)
    print(f"    [SEND dst=0x{board:02X} reg=0x{register:02X} sz={size}]: {pkt.hex()}")
    await client.write_gatt_char(WRITE_UUID, encrypted, response=False)
    raw = await receive_response(timeout=timeout)
    if raw:
        decrypted = crypto.decrypt(raw)
        print(f"    [RECV {len(decrypted)}b] {decrypted.hex()}")
        if len(decrypted) > 7:
            return decrypted[7:]
        elif len(decrypted) > 6:
            print(f"    (response has no data, idx=0x{decrypted[6]:02X})")
    return None


async def main():
    print("Turn on scooter display NOW, then wait 2s...")
    await asyncio.sleep(2)

    print(f"Scanning for {SCOOTER_ADDRESS}...")
    device = await BleakScanner.find_device_by_address(SCOOTER_ADDRESS, timeout=10.0)
    if not device:
        print("Not found!")
        sys.exit(1)

    device_name = device.name or SCOOTER_ADDRESS.replace(":", "")
    print(f"Found: {device_name}")

    async with BleakClient(device, timeout=20.0) as client:
        print(f"Connected: {client.is_connected}")
        try:
            await client._backend._acquire_mtu()
        except Exception:
            pass
        print(f"MTU: {client.mtu_size}")

        for uuid in NOTIFY_UUIDS:
            await client.start_notify(uuid, notification_handler)
        await asyncio.sleep(0.5)

        crypto, serial = await authenticate(client, device_name)
        if not crypto:
            sys.exit(1)

        print(f"\n{'='*50}")
        print(f"Scooter: {serial} ({MODEL['name']})")
        print("=" * 50)

        for s in MODEL["sensors"][:6]:
            board_addr = BOARDS[s["board"]]
            data = await read_register(client, crypto, board_addr, s["reg"], s["size"])
            if data and len(data) >= struct.calcsize(s["fmt"]):
                value = struct.unpack(s["fmt"], data[:struct.calcsize(s["fmt"])])[0]
                value = value * s["scale"]
                if "round" in s:
                    value = round(value, s["round"])
                print(f"  {s['name']}: {value} {s.get('unit', '')}")

        for uuid in NOTIFY_UUIDS:
            await client.stop_notify(uuid)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
