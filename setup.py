#!/usr/bin/env python3
"""Interactive setup for Ninebot Max G3 BLE-MQTT Bridge."""

import configparser
import json
import os
import subprocess
import sys
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.ini"
SAMPLE_CONFIG = BASE_DIR / "config.sample.ini"
CREDENTIALS_FILE = BASE_DIR / "ninebot_credentials.json"
VENV_DIR = BASE_DIR / "venv"
SERVICE_FILE = BASE_DIR / "ninebot-mqtt.service"
SERVICE_NAME = "ninebot-mqtt"
SERVICE_DEST = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")

REQUIRED_PACKAGES = ["bleak", "paho-mqtt", "cryptography"]

BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def banner():
    print(f"""
{BLUE}{BOLD}╔══════════════════════════════════════════════════╗
║       Ninebot Max G3 — BLE-MQTT Bridge Setup     ║
╚══════════════════════════════════════════════════╝{RESET}
""")


def step(text):
    print(f"\n{BLUE}{BOLD}──{RESET} {BOLD}{text}{RESET}")
    print(f"{BLUE}{'─' * 50}{RESET}")


def ok(text):
    print(f"  {GREEN}✔{RESET} {text}")


def warn(text):
    print(f"  {YELLOW}⚠{RESET} {text}")


def fail(text):
    print(f"  {RED}✘{RESET} {text}")


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"  → {prompt}{suffix}: ").strip()
    return val if val else default


def ask_choice(prompt, options):
    print(f"\n  {prompt}")
    for i, (label, _) in enumerate(options, 1):
        print(f"    {BOLD}{i}{RESET}) {label}")
    while True:
        try:
            choice = int(input(f"\n  → Choice (1-{len(options)}): ").strip())
            if 1 <= choice <= len(options):
                return options[choice - 1][1]
        except (ValueError, EOFError):
            pass
        print(f"  {RED}Please enter a number between 1 and {len(options)}.{RESET}")


def ask_yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    val = input(f"  → {prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "j", "ja")


def pause():
    input(f"\n  {BLUE}Press Enter to return to menu...{RESET}")


def run_cmd(cmd, check=False):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        return None
    return result


def run_sudo(cmd):
    result = subprocess.run(["sudo"] + cmd, capture_output=True, text=True)
    return result.returncode == 0


# ─── Python & venv ──────────────────────────────────────────────────

def get_python_bin():
    return VENV_DIR / "bin" / "python" if os.name != "nt" else VENV_DIR / "Scripts" / "python.exe"


def check_python():
    step("Check Python environment")

    v = sys.version_info
    if v >= (3, 9):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor} — at least 3.9 required.")
        return False

    if VENV_DIR.exists():
        ok(f"Virtualenv found: {VENV_DIR}")
    else:
        print(f"  Creating virtualenv in {VENV_DIR}...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        ok("Virtualenv created")

    return True


# ─── Dependencies ───────────────────────────────────────────────────

def check_dependencies():
    step("Check dependencies")
    python_bin = get_python_bin()

    pip_cmd = [str(python_bin), "-m", "pip"]
    result = subprocess.run(
        pip_cmd + ["list", "--format=columns"],
        capture_output=True, text=True
    )
    installed = result.stdout.lower()

    missing = []
    for pkg in REQUIRED_PACKAGES:
        check_name = pkg.replace("-", "").replace("_", "")
        if check_name in installed.replace("-", "").replace("_", ""):
            ok(f"{pkg} installed")
        else:
            warn(f"{pkg} missing")
            missing.append(pkg)

    if missing:
        print(f"\n  Missing packages: {', '.join(missing)}")
        if ask_yes_no("Install now?"):
            subprocess.check_call(pip_cmd + ["install", "--upgrade"] + missing)
            ok("All packages installed")
        else:
            fail("Aborted — packages are required.")
    else:
        ok("All dependencies satisfied")


# ─── BLE-Scan ───────────────────────────────────────────────────────

def scan_for_scooter():
    step("Find scooter")
    python_bin = get_python_bin()

    choice = ask_choice("How do you want to specify the scooter?", [
        ("Start BLE scan (scooter must be turned on)", "scan"),
        ("Enter MAC address manually", "manual"),
        ("Back to main menu", "back"),
    ])

    if choice == "back":
        return None

    if choice == "manual":
        addr = ask("MAC address (e.g. D5:A1:FB:35:12:80)")
        if not addr:
            fail("No address entered.")
            return None
        return addr

    print("\n  Scanning for BLE devices... (turn on the scooter display!)")

    scan_script = """
import asyncio, json
from bleak import BleakScanner

async def scan():
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    results = []
    sorted_items = sorted(devices.values(), key=lambda x: x[1].rssi or -999, reverse=True)
    for d, adv in sorted_items:
        name = d.name or adv.local_name or "Unknown"
        if any(k in name.lower() for k in ["ninebot", "segway", "scooter", "nb-"]):
            results.append({"addr": d.address, "name": name, "rssi": adv.rssi, "match": True})
        else:
            results.append({"addr": d.address, "name": name, "rssi": adv.rssi, "match": False})
    print(json.dumps(results))

asyncio.run(scan())
"""
    try:
        result = subprocess.run(
            [str(python_bin), "-c", scan_script],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        fail("Scan timed out.")
        warn("Tip: On Linux you may need to run 'sudo setcap cap_net_raw+eip $(which python3)'")
        addr = ask("Enter MAC address manually")
        return addr or None

    if result.returncode != 0:
        fail(f"Scan failed: {result.stderr.strip()}")
        warn("Tip: On Linux you may need to run 'sudo setcap cap_net_raw+eip $(which python3)'")
        addr = ask("Enter MAC address manually")
        return addr or None

    try:
        devices = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        fail("Scan returned no results.")
        addr = ask("Enter MAC address manually")
        return addr or None

    if not devices:
        warn("No BLE devices found.")
        addr = ask("Enter MAC address manually")
        return addr or None

    matches = [d for d in devices if d["match"]]
    others = [d for d in devices if not d["match"]]

    print(f"\n  {GREEN}Devices found:{RESET}")

    options = []
    idx = 0

    if matches:
        print(f"\n  {BOLD}── Ninebot / Segway ──{RESET}")
        for d in matches:
            idx += 1
            rssi = f"{d['rssi']} dBm" if d['rssi'] else "?"
            print(f"    {BOLD}{idx}{RESET}) {GREEN}{d['name']}{RESET}  {d['addr']}  ({rssi})")
            options.append(d["addr"])

    if others:
        show_others = len(matches) == 0 or ask_yes_no("Also show other BLE devices?", default=False)
        if show_others:
            print(f"\n  {BOLD}── Other devices ──{RESET}")
            for d in others[:20]:
                idx += 1
                rssi = f"{d['rssi']} dBm" if d['rssi'] else "?"
                print(f"    {BOLD}{idx}{RESET}) {d['name']}  {d['addr']}  ({rssi})")
                options.append(d["addr"])

    idx += 1
    print(f"    {BOLD}{idx}{RESET}) Enter MAC address manually")
    options.append("manual")

    while True:
        try:
            choice = int(input(f"\n  → Select scooter (1-{idx}): ").strip())
            if 1 <= choice <= idx:
                selected = options[choice - 1]
                if selected == "manual":
                    addr = ask("MAC address")
                    return addr or None
                ok(f"Selected: {selected}")
                return selected
        except (ValueError, EOFError):
            pass
        print(f"  {RED}Please enter a number between 1 and {idx}.{RESET}")


# ─── MQTT ───────────────────────────────────────────────────────────

def configure_mqtt():
    step("Configure MQTT")

    broker = ask("MQTT broker IP/hostname", "192.168.1.100")
    port = ask("MQTT port", "1883")

    use_auth = ask_yes_no("Use MQTT authentication?", default=True)
    user = ""
    password = ""
    if use_auth:
        user = ask("MQTT username")
        password = ask("MQTT password")

    return {
        "broker": broker,
        "port": port,
        "user": user,
        "password": password,
    }


# ─── Model / BLE config ────────────────────────────────────────────

def choose_model():
    step("Select scooter model")

    try:
        from models import list_models
        available = list_models()
    except ImportError:
        warn("models.py not found — using 'g3' as default.")
        return "g3"

    options = [(f"{name} ({key})", key) for key, name in available]
    return ask_choice("Which scooter model do you have?", options)


def configure_ble():
    step("Configure BLE connection")

    keep_alive = ask_yes_no(
        "Keep BLE connection open between polls?\n"
        "    Yes = faster polling, but drains scooter battery\n"
        "    No  = connects only when polling (recommended for long intervals)\n"
        "  Stay permanently connected?", default=False)

    reconnect = ask("Seconds until reconnect after connection loss", "30")

    return {
        "keep_alive": str(keep_alive).lower(),
        "reconnect_delay": reconnect,
    }


# ─── Write config ──────────────────────────────────────────────────

def write_config(scooter_addr, mqtt_settings, model_key, ble_settings):
    step("Save configuration")

    name = ask("HA entity name (for sensor IDs)", "ninebot_max_g3")
    poll = ask("Poll interval in seconds", "1200")

    config = configparser.ConfigParser()
    config["scooter"] = {
        "address": scooter_addr,
        "model": model_key,
        "name": name,
    }
    config["mqtt"] = mqtt_settings
    config["timing"] = {
        "poll_interval": poll,
        "scan_interval": "60",
        "scan_timeout": "5.0",
        "connect_timeout": "20.0",
    }
    config["ble"] = ble_settings

    if CONFIG_FILE.exists():
        if not ask_yes_no(f"config.ini already exists. Overwrite?", default=False):
            existing = configparser.ConfigParser()
            existing.read(CONFIG_FILE)
            for section in config.sections():
                if not existing.has_section(section):
                    existing.add_section(section)
                for key, value in config.items(section):
                    existing.set(section, key, value)
            config = existing
            ok("Merged new values into existing config.ini.")
    with open(CONFIG_FILE, "w") as f:
        f.write("# Ninebot BLE-MQTT Bridge Configuration\n")
        f.write("# Created by setup.py\n\n")
        config.write(f)
    ok(f"Saved: {CONFIG_FILE}")


# ─── Pairing ────────────────────────────────────────────────────────

def pair_scooter():
    step("Pair with scooter")
    python_bin = get_python_bin()

    if CREDENTIALS_FILE.exists():
        creds = json.loads(CREDENTIALS_FILE.read_text())
        ok(f"Already paired (Serial: {creds.get('serial', '?')})")
        if not ask_yes_no("Re-pair anyway?", default=False):
            return True

    print(f"""
  {YELLOW}{BOLD}Preparation:{RESET}
  1. Turn on the scooter (display must be lit)
  2. When prompted, {BOLD}press the power button on the scooter{RESET}
""")

    if not ask_yes_no("Ready? Start pairing?"):
        warn("Skipped — you can run 'python ninebot.py' later.")
        return False

    print(f"\n  Starting pairing...\n")
    result = subprocess.run(
        [str(python_bin), str(BASE_DIR / "ninebot.py")],
        cwd=str(BASE_DIR)
    )

    if result.returncode == 0 and CREDENTIALS_FILE.exists():
        ok("Pairing successful!")
        return True
    else:
        fail("Pairing failed.")
        warn("Make sure the scooter is turned on and try again.")
        return False


# ─── Systemd Service ────────────────────────────────────────────────

def is_service_installed():
    return SERVICE_DEST.exists()


def get_service_status():
    if os.name == "nt" or not is_service_installed():
        return None
    result = run_cmd(["systemctl", "is-active", SERVICE_NAME])
    return result.stdout.strip() if result else None


def create_service_file():
    python_bin = get_python_bin()
    user = ask("Linux user for the service", os.environ.get("USER", "pi"))
    work_dir = str(BASE_DIR.resolve())
    python_path = str(python_bin.resolve()) if python_bin.exists() else str(python_bin)
    mqtt_script = str((BASE_DIR / "ninebot_mqtt.py").resolve())

    service_content = f"""[Unit]
Description=Ninebot Max G3 BLE to MQTT Bridge
After=network-online.target bluetooth.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={work_dir}
ExecStart={python_path} {mqtt_script}
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_FILE, "w") as f:
        f.write(service_content)
    ok(f"Service file written: {SERVICE_FILE}")
    return True


def service_menu():
    if os.name == "nt":
        warn("Systemd is only available on Linux.")
        return

    while True:
        installed = is_service_installed()
        status = get_service_status()

        status_text = f"{GREEN}active{RESET}" if status == "active" else \
                      f"{RED}{status}{RESET}" if status else f"{DIM}not installed{RESET}"

        step(f"Service management  [{status_text}]")

        options = []
        if not installed:
            options.append(("Install service", "install"))
        else:
            if status == "active":
                options.append(("Restart service", "restart"))
                options.append(("Stop service", "stop"))
            else:
                options.append(("Start service", "start"))
                options.append(("Restart service", "restart"))
            options.append(("View logs (last 30 lines)", "logs"))
            options.append(("Uninstall service", "uninstall"))
        options.append(("Back to main menu", "back"))

        choice = ask_choice("Service options:", options)

        if choice == "back":
            return

        if choice == "install":
            if not create_service_file():
                continue
            print(f"\n  Installing service...")
            if run_sudo(["cp", str(SERVICE_FILE), str(SERVICE_DEST)]) and \
               run_sudo(["systemctl", "daemon-reload"]) and \
               run_sudo(["systemctl", "enable", SERVICE_NAME]):
                ok("Service installed and enabled")
                if ask_yes_no("Start service now?"):
                    if run_sudo(["systemctl", "start", SERVICE_NAME]):
                        ok("Service started")
                    else:
                        fail("Failed to start service")
            else:
                fail("Failed to install service (sudo required)")

        elif choice == "start":
            if run_sudo(["systemctl", "start", SERVICE_NAME]):
                ok("Service started")
            else:
                fail("Failed to start service")

        elif choice == "stop":
            if run_sudo(["systemctl", "stop", SERVICE_NAME]):
                ok("Service stopped")
            else:
                fail("Failed to stop service")

        elif choice == "restart":
            if run_sudo(["systemctl", "restart", SERVICE_NAME]):
                ok("Service restarted")
            else:
                fail("Failed to restart service")

        elif choice == "logs":
            print()
            result = subprocess.run(
                ["sudo", "journalctl", "-u", SERVICE_NAME, "-n", "30", "--no-pager"],
                text=True
            )

        elif choice == "uninstall":
            if not ask_yes_no("Really uninstall the service?", default=False):
                continue
            run_sudo(["systemctl", "stop", SERVICE_NAME])
            run_sudo(["systemctl", "disable", SERVICE_NAME])
            if run_sudo(["rm", str(SERVICE_DEST)]) and \
               run_sudo(["systemctl", "daemon-reload"]):
                ok("Service uninstalled")
            else:
                fail("Failed to uninstall service")

        pause()


# ─── MQTT connection test ───────────────────────────────────────────

def test_mqtt_connection():
    if not CONFIG_FILE.exists():
        return None, "no config"

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    broker = config.get("mqtt", "broker", fallback=None)
    port = config.getint("mqtt", "port", fallback=1883)
    user = config.get("mqtt", "user", fallback="")
    password = config.get("mqtt", "password", fallback="")

    if not broker:
        return None, "no broker configured"

    python_bin = get_python_bin()
    test_script = f"""
import sys
try:
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ninebot_test")
    if {repr(user)}:
        c.username_pw_set({repr(user)}, {repr(password)})
    c.connect({repr(broker)}, {port}, keepalive=5)
    c.disconnect()
    print("ok")
except Exception as e:
    print(f"error:{{e}}")
"""
    try:
        result = subprocess.run(
            [str(python_bin), "-c", test_script],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if output == "ok":
            return True, f"{broker}:{port}"
        elif output.startswith("error:"):
            return False, output[6:]
        else:
            return False, result.stderr.strip() or "unknown error"
    except subprocess.TimeoutExpired:
        return False, "connection timed out"
    except Exception as e:
        return None, str(e)


# ─── Status ─────────────────────────────────────────────────────────

def show_status():
    step("Current status")

    # Config
    print(f"\n  {BOLD}Configuration{RESET}")
    if CONFIG_FILE.exists():
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        addr = config.get("scooter", "address", fallback="not set")
        model = config.get("scooter", "model", fallback="not set")
        name = config.get("scooter", "name", fallback="not set")
        broker = config.get("mqtt", "broker", fallback="not set")
        port = config.get("mqtt", "port", fallback="not set")
        poll = config.get("timing", "poll_interval", fallback="not set")
        ok(f"config.ini found")
        print(f"    Scooter:  {addr} ({model})")
        print(f"    Name:     {name}")
        print(f"    MQTT:     {broker}:{port}")
        print(f"    Poll:     {poll}s")
    else:
        warn("No config.ini found")

    # Pairing
    print(f"\n  {BOLD}Pairing{RESET}")
    if CREDENTIALS_FILE.exists():
        creds = json.loads(CREDENTIALS_FILE.read_text())
        ok(f"Paired (Serial: {creds.get('serial', '?')})")
    else:
        warn("Not paired — no credentials file")

    # Virtualenv
    print(f"\n  {BOLD}Environment{RESET}")
    if VENV_DIR.exists():
        ok(f"Virtualenv: {VENV_DIR}")
    else:
        warn("No virtualenv")

    # MQTT connection
    print(f"\n  {BOLD}MQTT broker{RESET}")
    mqtt_ok, mqtt_info = test_mqtt_connection()
    if mqtt_ok is True:
        ok(f"Connected to {mqtt_info}")
    elif mqtt_ok is False:
        fail(f"Cannot connect: {mqtt_info}")
    else:
        warn(f"Not tested: {mqtt_info}")

    # Service
    print(f"\n  {BOLD}Systemd service{RESET}")
    if os.name == "nt":
        warn("Not available on Windows")
    elif not is_service_installed():
        warn("Not installed")
    else:
        status = get_service_status()
        if status == "active":
            ok(f"Service: {GREEN}running{RESET}")
            result = run_cmd(["systemctl", "show", SERVICE_NAME,
                              "--property=ActiveEnterTimestamp", "--value"])
            if result and result.stdout.strip():
                print(f"    Since: {result.stdout.strip()}")
        elif status == "inactive":
            warn("Service: stopped")
        elif status == "failed":
            fail("Service: failed")
            result = subprocess.run(
                ["journalctl", "-u", SERVICE_NAME, "-n", "3", "--no-pager", "-q"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"    {DIM}{line}{RESET}")
        else:
            warn(f"Service: {status}")

        enabled = run_cmd(["systemctl", "is-enabled", SERVICE_NAME])
        if enabled and enabled.stdout.strip() == "enabled":
            ok("Auto-start: enabled")
        else:
            warn("Auto-start: disabled")


# ─── Full setup ─────────────────────────────────────────────────────

def full_setup():
    if not check_python():
        return
    check_dependencies()
    scooter_addr = scan_for_scooter()
    if not scooter_addr:
        fail("No scooter address — aborting full setup.")
        return
    model_key = choose_model()
    mqtt_settings = configure_mqtt()
    ble_settings = configure_ble()
    write_config(scooter_addr, mqtt_settings, model_key, ble_settings)
    pair_scooter()
    service_menu()


# ─── Find & pair ────────────────────────────────────────────────────

def find_and_pair():
    scooter_addr = scan_for_scooter()
    if not scooter_addr:
        return
    model_key = choose_model()

    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    elif SAMPLE_CONFIG.exists():
        config.read(SAMPLE_CONFIG)
    if not config.has_section("scooter"):
        config.add_section("scooter")
    config.set("scooter", "address", scooter_addr)
    config.set("scooter", "model", model_key)
    if not config.has_option("scooter", "name"):
        config.set("scooter", "name", f"ninebot_{model_key}")
    with open(CONFIG_FILE, "w") as f:
        config.write(f)
    ok(f"Scooter address saved to {CONFIG_FILE}")

    pair_scooter()


# ─── Configure MQTT ─────────────────────────────────────────────────

def mqtt_setup():
    if CONFIG_FILE.exists():
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        scooter_addr = config.get("scooter", "address", fallback="XX:XX:XX:XX:XX:XX")
        model_key = config.get("scooter", "model", fallback="g3")
    else:
        scooter_addr = "XX:XX:XX:XX:XX:XX"
        model_key = choose_model()
    mqtt_settings = configure_mqtt()
    ble_settings = configure_ble()
    write_config(scooter_addr, mqtt_settings, model_key, ble_settings)


# ─── Main menu ──────────────────────────────────────────────────────

def main():
    banner()

    if not check_python():
        print(f"\n{RED}Python 3.9+ is required. Exiting.{RESET}")
        sys.exit(1)

    while True:
        choice = ask_choice("What would you like to do?", [
            ("Full initial setup", "full"),
            ("Install dependencies", "deps"),
            ("Find & pair scooter", "pair"),
            ("Configure MQTT", "mqtt"),
            ("Manage systemd service", "service"),
            ("Show current status", "status"),
            ("Quit", "quit"),
        ])

        if choice == "quit":
            print(f"\n{BLUE}Goodbye!{RESET}\n")
            break
        elif choice == "full":
            full_setup()
            pause()
        elif choice == "deps":
            check_dependencies()
            pause()
        elif choice == "pair":
            find_and_pair()
            pause()
        elif choice == "mqtt":
            mqtt_setup()
            pause()
        elif choice == "service":
            service_menu()
        elif choice == "status":
            show_status()
            pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Cancelled.{RESET}")
        sys.exit(0)
