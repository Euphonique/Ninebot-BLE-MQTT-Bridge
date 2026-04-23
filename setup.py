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

REQUIRED_PACKAGES = ["bleak", "paho-mqtt", "cryptography"]

BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def banner():
    print(f"""
{BLUE}{BOLD}╔══════════════════════════════════════════════════╗
║       Ninebot Max G3 — BLE-MQTT Bridge Setup     ║
╚══════════════════════════════════════════════════╝{RESET}
""")


def step(num, text):
    print(f"\n{BLUE}{BOLD}[Step {num}]{RESET} {BOLD}{text}{RESET}")
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
            choice = int(input(f"\n  → Auswahl (1-{len(options)}): ").strip())
            if 1 <= choice <= len(options):
                return options[choice - 1][1]
        except (ValueError, EOFError):
            pass
        print(f"  {RED}Bitte eine Zahl zwischen 1 und {len(options)} eingeben.{RESET}")


def ask_yes_no(prompt, default=True):
    hint = "J/n" if default else "j/N"
    val = input(f"  → {prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("j", "ja", "y", "yes")


# ─── Step 1: Python & venv ───────────────────────────────────────────

def check_python():
    step(1, "Python-Umgebung prüfen")

    v = sys.version_info
    if v >= (3, 9):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor} — mindestens 3.9 erforderlich.")
        sys.exit(1)

    if VENV_DIR.exists():
        ok(f"Virtualenv vorhanden: {VENV_DIR}")
    else:
        print(f"  Erstelle virtualenv in {VENV_DIR}...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        ok("Virtualenv erstellt")

    return VENV_DIR / "bin" / "python" if os.name != "nt" else VENV_DIR / "Scripts" / "python.exe"


# ─── Step 2: Dependencies ────────────────────────────────────────────

def check_dependencies(python_bin):
    step(2, "Abhängigkeiten prüfen")

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
            ok(f"{pkg} installiert")
        else:
            warn(f"{pkg} fehlt")
            missing.append(pkg)

    if missing:
        print(f"\n  Fehlende Pakete: {', '.join(missing)}")
        if ask_yes_no("Jetzt installieren?"):
            subprocess.check_call(pip_cmd + ["install", "--upgrade"] + missing)
            ok("Alle Pakete installiert")
        else:
            fail("Abbruch — Pakete werden benötigt.")
            sys.exit(1)
    else:
        ok("Alle Abhängigkeiten erfüllt")


# ─── Step 3: BLE-Scan ────────────────────────────────────────────────

def scan_for_scooter(python_bin):
    step(3, "Scooter suchen")

    choice = ask_choice("Wie möchtest du den Scooter angeben?", [
        ("BLE-Scan starten (Scooter muss eingeschaltet sein)", "scan"),
        ("MAC-Adresse manuell eingeben", "manual"),
    ])

    if choice == "manual":
        addr = ask("MAC-Adresse (z.B. D5:A1:FB:35:12:80)")
        if not addr:
            fail("Keine Adresse eingegeben.")
            sys.exit(1)
        return addr

    print("\n  Scanne nach BLE-Geräten... (Scooter-Display einschalten!)")

    scan_script = """
import asyncio, json
from bleak import BleakScanner

async def scan():
    devices = await BleakScanner.discover(timeout=10.0)
    results = []
    for d in sorted(devices, key=lambda x: x.rssi or -999, reverse=True):
        name = d.name or "Unknown"
        if any(k in name.lower() for k in ["ninebot", "segway", "scooter", "nb-"]):
            results.append({"addr": d.address, "name": name, "rssi": d.rssi, "match": True})
        else:
            results.append({"addr": d.address, "name": name, "rssi": d.rssi, "match": False})
    print(json.dumps(results))

asyncio.run(scan())
"""
    result = subprocess.run(
        [str(python_bin), "-c", scan_script],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        fail(f"Scan fehlgeschlagen: {result.stderr.strip()}")
        warn("Tipp: Auf Linux ggf. 'sudo setcap cap_net_raw+eip $(which python3)' ausführen")
        addr = ask("MAC-Adresse manuell eingeben")
        return addr

    try:
        devices = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        fail("Scan lieferte keine Ergebnisse.")
        addr = ask("MAC-Adresse manuell eingeben")
        return addr

    if not devices:
        warn("Keine BLE-Geräte gefunden.")
        addr = ask("MAC-Adresse manuell eingeben")
        return addr

    matches = [d for d in devices if d["match"]]
    others = [d for d in devices if not d["match"]]

    print(f"\n  {GREEN}Gefundene Geräte:{RESET}")

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
        show_others = len(matches) == 0 or ask_yes_no("Auch andere BLE-Geräte anzeigen?", default=False)
        if show_others:
            print(f"\n  {BOLD}── Andere Geräte ──{RESET}")
            for d in others[:20]:
                idx += 1
                rssi = f"{d['rssi']} dBm" if d['rssi'] else "?"
                print(f"    {BOLD}{idx}{RESET}) {d['name']}  {d['addr']}  ({rssi})")
                options.append(d["addr"])

    idx += 1
    print(f"    {BOLD}{idx}{RESET}) MAC-Adresse manuell eingeben")
    options.append("manual")

    while True:
        try:
            choice = int(input(f"\n  → Scooter auswählen (1-{idx}): ").strip())
            if 1 <= choice <= idx:
                selected = options[choice - 1]
                if selected == "manual":
                    return ask("MAC-Adresse")
                ok(f"Ausgewählt: {selected}")
                return selected
        except (ValueError, EOFError):
            pass
        print(f"  {RED}Bitte eine Zahl zwischen 1 und {idx} eingeben.{RESET}")


# ─── Step 4: MQTT ────────────────────────────────────────────────────

def configure_mqtt():
    step(4, "MQTT konfigurieren")

    broker = ask("MQTT Broker IP/Hostname", "192.168.1.100")
    port = ask("MQTT Port", "1883")

    use_auth = ask_yes_no("MQTT Authentifizierung verwenden?", default=True)
    user = ""
    password = ""
    if use_auth:
        user = ask("MQTT Benutzername")
        password = ask("MQTT Passwort")

    return {
        "broker": broker,
        "port": port,
        "user": user,
        "password": password,
    }


# ─── Step 5: Config schreiben ────────────────────────────────────────

def choose_model():
    step("4b", "Scooter-Modell auswählen")

    try:
        from models import list_models
        available = list_models()
    except ImportError:
        warn("models.py nicht gefunden — verwende 'g3' als Standard.")
        return "g3"

    options = [(f"{name} ({key})", key) for key, name in available]
    return ask_choice("Welches Scooter-Modell hast du?", options)


def configure_ble():
    step("4c", "BLE-Verbindung konfigurieren")

    keep_alive = ask_yes_no(
        "BLE-Verbindung zwischen Abfragen offen halten?\n"
        "    Ja  = schnellere Abfragen, verbraucht aber Scooter-Akku\n"
        "    Nein = verbindet sich nur zum Abfragen (empfohlen bei langen Intervallen)\n"
        "  Dauerhaft verbunden bleiben?", default=False)

    reconnect = ask("Sekunden bis Reconnect nach Verbindungsverlust", "30")

    return {
        "keep_alive": str(keep_alive).lower(),
        "reconnect_delay": reconnect,
    }


def write_config(scooter_addr, mqtt_settings, model_key, ble_settings):
    step(5, "Konfiguration speichern")

    name = ask("HA Entity-Name (für Sensor-IDs)", "ninebot_max_g3")
    poll = ask("Abfrageintervall in Sekunden", "1200")

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
        if not ask_yes_no(f"config.ini existiert bereits. Überschreiben?", default=False):
            warn("Übersprungen — bestehende config.ini wird beibehalten.")
            return
    with open(CONFIG_FILE, "w") as f:
        f.write("# Ninebot BLE-MQTT Bridge Konfiguration\n")
        f.write("# Erstellt durch setup.py\n\n")
        config.write(f)
    ok(f"Gespeichert: {CONFIG_FILE}")


# ─── Step 6: Pairing ─────────────────────────────────────────────────

def pair_scooter(python_bin):
    step(6, "Mit Scooter koppeln")

    if CREDENTIALS_FILE.exists():
        creds = json.loads(CREDENTIALS_FILE.read_text())
        ok(f"Bereits gekoppelt (Serial: {creds.get('serial', '?')})")
        if not ask_yes_no("Trotzdem neu koppeln?", default=False):
            return True

    print(f"""
  {YELLOW}{BOLD}Vorbereitung:{RESET}
  1. Scooter einschalten (Display muss leuchten)
  2. Beim Koppeln die {BOLD}Power-Taste am Scooter drücken{RESET} wenn aufgefordert
""")

    if not ask_yes_no("Bereit? Pairing starten?"):
        warn("Übersprungen — du kannst später 'python ninebot.py' ausführen.")
        return False

    print(f"\n  Starte Pairing...\n")
    result = subprocess.run(
        [str(python_bin), str(BASE_DIR / "ninebot.py")],
        cwd=str(BASE_DIR)
    )

    if result.returncode == 0 and CREDENTIALS_FILE.exists():
        ok("Pairing erfolgreich!")
        return True
    else:
        fail("Pairing fehlgeschlagen.")
        warn("Stelle sicher, dass der Scooter eingeschaltet ist und versuche es erneut.")
        return False


# ─── Step 7: Systemd Service ─────────────────────────────────────────

def setup_service(python_bin):
    step(7, "Systemd-Service einrichten (optional)")

    if os.name == "nt":
        warn("Systemd ist nur auf Linux verfügbar — übersprungen.")
        return

    if not ask_yes_no("Soll der MQTT-Bridge als systemd-Service installiert werden?"):
        warn("Übersprungen — du kannst den Service später manuell einrichten.")
        return

    user = ask("Linux-Benutzer für den Service", os.environ.get("USER", "pi"))
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
    ok(f"Service-Datei geschrieben: {SERVICE_FILE}")

    service_dest = Path("/etc/systemd/system/ninebot-mqtt.service")
    print(f"\n  Zum Aktivieren ausführen:")
    print(f"    {BOLD}sudo cp {SERVICE_FILE} {service_dest}{RESET}")
    print(f"    {BOLD}sudo systemctl daemon-reload{RESET}")
    print(f"    {BOLD}sudo systemctl enable --now ninebot-mqtt{RESET}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    banner()

    choice = ask_choice("Was möchtest du tun?", [
        ("Komplette Ersteinrichtung", "full"),
        ("Nur Abhängigkeiten installieren", "deps"),
        ("Nur Scooter suchen & koppeln", "pair"),
        ("Nur MQTT konfigurieren", "mqtt"),
        ("Nur systemd-Service einrichten", "service"),
    ])

    python_bin = check_python()

    if choice in ("full", "deps"):
        check_dependencies(python_bin)
        if choice == "deps":
            print(f"\n{GREEN}{BOLD}Fertig!{RESET}")
            return

    model_key = "g3"

    if choice in ("full", "pair"):
        scooter_addr = scan_for_scooter(python_bin)
        model_key = choose_model()
    else:
        scooter_addr = None

    if choice in ("full", "mqtt"):
        mqtt_settings = configure_mqtt()
    else:
        mqtt_settings = None

    if choice == "full":
        ble_settings = configure_ble()
        write_config(scooter_addr, mqtt_settings, model_key, ble_settings)
        pair_scooter(python_bin)
        setup_service(python_bin)
    elif choice == "pair":
        if not CONFIG_FILE.exists():
            warn("Keine config.ini gefunden — schreibe Scooter-Adresse...")
            config = configparser.ConfigParser()
            if SAMPLE_CONFIG.exists():
                config.read(SAMPLE_CONFIG)
            config.setdefault("scooter", {})["address"] = scooter_addr
            config.setdefault("scooter", {})["model"] = model_key
            with open(CONFIG_FILE, "w") as f:
                config.write(f)
        pair_scooter(python_bin)
    elif choice == "mqtt":
        if CONFIG_FILE.exists():
            config = configparser.ConfigParser()
            config.read(CONFIG_FILE)
            scooter_addr = config.get("scooter", "address", fallback="XX:XX:XX:XX:XX:XX")
            model_key = config.get("scooter", "model", fallback="g3")
        else:
            scooter_addr = "XX:XX:XX:XX:XX:XX"
            model_key = choose_model()
        ble_settings = configure_ble()
        write_config(scooter_addr, mqtt_settings, model_key, ble_settings)
    elif choice == "service":
        setup_service(python_bin)

    print(f"""
{GREEN}{BOLD}╔══════════════════════════════════════════════════╗
║                  Setup abgeschlossen!            ║
╚══════════════════════════════════════════════════╝{RESET}

  Konfiguration:  {CONFIG_FILE}
  Credentials:    {CREDENTIALS_FILE}

  {BOLD}Manuell starten:{RESET}
    {VENV_DIR / 'bin' / 'python'} ninebot_mqtt.py

  {BOLD}Logs ansehen:{RESET}
    sudo journalctl -u ninebot-mqtt -f
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Abgebrochen.{RESET}")
        sys.exit(0)
