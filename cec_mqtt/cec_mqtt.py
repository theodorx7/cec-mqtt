import paho.mqtt.client as mqtt
import subprocess
import threading
import json
import os
import time
import re
import glob

options_path = "/data/options.json"

# ----- Load config -----
if os.path.exists(options_path):
    with open(options_path, "r", encoding="utf-8") as f:
        opts = json.load(f)

    MQTT_BROKER = opts.get("mqtt_host", "mqtt.local")
    MQTT_PORT = int(opts.get("mqtt_port", 1883))
    MQTT_USER = opts.get("mqtt_user", "")
    MQTT_PASS = opts.get("mqtt_password", "")
    MQTT_TOPIC_SEND = opts.get("mqtt_topic_send", "cec/send")
    MQTT_TOPIC_RECEIVE = opts.get("mqtt_topic_receive", "cec/receive")
    MQTT_TOPIC_ALL = opts.get("mqtt_topic_all", "cec/all")
    MQTT_TOPIC_IN = opts.get("mqtt_topic_in", "cec/in")
    MQTT_TOPIC_OUT = opts.get("mqtt_topic_out", "cec/out")
    DEBUG_LOG = opts.get("debug_log", False)

    # Optional override: "/dev/cec0", "/dev/cec1", "RPI", etc.
    CEC_ADAPTER = (opts.get("cec_adapter", "") or "").strip()
else:
    MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.local")
    MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
    MQTT_USER = os.getenv("MQTT_USER", "")
    MQTT_PASS = os.getenv("MQTT_PASS", "")
    MQTT_TOPIC_SEND = os.getenv("MQTT_TOPIC_SEND", "cec/send")
    MQTT_TOPIC_RECEIVE = os.getenv("MQTT_TOPIC_RECEIVE", "cec/receive")
    MQTT_TOPIC_ALL = os.getenv("MQTT_TOPIC_ALL", "cec/all")
    MQTT_TOPIC_IN = os.getenv("MQTT_TOPIC_IN", "cec/in")
    MQTT_TOPIC_OUT = os.getenv("MQTT_TOPIC_OUT", "cec/out")
    DEBUG_LOG = os.getenv("DEBUG_LOG", "false").lower() == "true"
    CEC_ADAPTER = (os.getenv("CEC_ADAPTER", "") or "").strip()

DISCOVERY_PREFIX = "homeassistant"
ADDON_VERSION = "1.4"

DISCOVERY_SENSORS = [
    {"object_id": "cec_last_message", "name": "Last Message", "topic_var": "MQTT_TOPIC_ALL", "icon": "mdi:message-text"},
    {"object_id": "cec_last_incoming", "name": "Last Incoming", "topic_var": "MQTT_TOPIC_IN", "icon": "mdi:message-arrow-left"},
    {"object_id": "cec_last_outgoing", "name": "Last Outgoing", "topic_var": "MQTT_TOPIC_OUT", "icon": "mdi:message-arrow-right"},
]

process = None
selected_adapter = None

client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            out.append(x)
            seen.add(x)
    return out


def list_adapters_from_cec_client() -> list[str]:
    """
    cec-client -l обычно печатает строки вида:
      device: 1 com port: /dev/cec0 ...
      device: 2 com port: /dev/cec1 ...
    """
    try:
        r = subprocess.run(
            ["cec-client", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text_out = (r.stdout or "") + "\n" + (r.stderr or "")
    except Exception as err:
        print(f"[WARN] cec-client -l failed: {err}", flush=True)
        return []

    ports = []
    for line in text_out.splitlines():
        m = re.search(r"com port:\s*([^\s]+)", line)
        if m:
            port = m.group(1).strip()
            # иногда встречается "device: 3 com port:" (пусто) — пропускаем
            if port and port.lower() not in ("none", "null"):
                ports.append(port)
    return _dedupe_keep_order(ports)


def build_candidate_adapters() -> list[str]:
    # 1) explicit override
    if CEC_ADAPTER:
        return [CEC_ADAPTER]

    candidates: list[str] = []

    # 2) prefer libCEC/cec-client list
    candidates += list_adapters_from_cec_client()

    # 3) fallbacks (как у тебя в bridge-app)
    if os.path.exists("/dev/cec0"):
        candidates.append("/dev/cec0")
    if os.path.exists("/dev/cec1"):
        candidates.append("/dev/cec1")
    candidates.append("RPI")

    return _dedupe_keep_order(candidates)


def probe_adapter(adapter: str) -> bool:
    """
    Проверяем адаптер так же “мягко”, как bridge-app (Open()) — но через cec-client:
    запускаем single-command режим (-s) и отправляем 'scan', ждём вывод.
    """
    cmd = ["cec-client", "-s", "-t", "p", "-d", "1"]
    if adapter:
        cmd.append(adapter)

    try:
        r = subprocess.run(
            cmd,
            input="scan\n",
            text=True,
            capture_output=True,
            timeout=8,
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        low = out.lower()

        if "could not open a connection" in low or "error opening" in low:
            return False
        # типичный успешный вывод содержит это (или близкое)
        if "opening a connection" in low or "requesting cec bus information" in low:
            return True

        # если код 0 и нет явных ошибок — считаем успехом
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def select_adapter() -> str:
    candidates = build_candidate_adapters()
    print(f"[INFO] CEC candidates: {candidates}", flush=True)

    for cand in candidates:
        print(f"[INFO] Probing CEC adapter: {cand}", flush=True)
        if probe_adapter(cand):
            print(f"[INFO] Selected CEC adapter: {cand}", flush=True)
            return cand
        time.sleep(0.2)

    raise ConnectionError(f"Could not connect to CEC adapter (tried: {candidates})")


def publish_discovery(mqtt_client):
    topic_map = {
        "MQTT_TOPIC_ALL": MQTT_TOPIC_ALL,
        "MQTT_TOPIC_IN": MQTT_TOPIC_IN,
        "MQTT_TOPIC_OUT": MQTT_TOPIC_OUT,
    }

    device_info = {
        "identifiers": ["cec_mqtt_bridge"],
        "name": "CEC MQTT Bridge",
        "manufacturer": "cteachworth",
        "model": "CEC MQTT Bridge",
        "sw_version": ADDON_VERSION,
    }

    for sensor in DISCOVERY_SENSORS:
        config_topic = f"{DISCOVERY_PREFIX}/sensor/cec_mqtt/{sensor['object_id']}/config"
        payload = {
            "name": sensor["name"],
            "object_id": sensor["object_id"],
            "unique_id": f"cec_mqtt_{sensor['object_id']}",
            "state_topic": topic_map[sensor["topic_var"]],
            "icon": sensor["icon"],
            "device": device_info,
        }
        mqtt_client.publish(config_topic, json.dumps(payload), retain=True)
        if DEBUG_LOG:
            print(f"Published discovery: {config_topic}", flush=True)

    print("MQTT discovery configs published", flush=True)


def on_connect(mqtt_client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker", flush=True)
        mqtt_client.subscribe(MQTT_TOPIC_SEND)
        publish_discovery(mqtt_client)
    else:
        print(f"MQTT connection failed with code {rc}", flush=True)


def on_message(mqtt_client, userdata, msg):
    global process
    command = msg.payload.decode(errors="ignore").strip()

    if DEBUG_LOG:
        print(f"Sending CEC command: {command}", flush=True)

    if process is None or process.poll() is not None:
        print("Cannot send command, cec-client is not running", flush=True)
        return

    try:
        process.stdin.write((command + "\n").encode())
        process.stdin.flush()
    except Exception as e:
        print(f"Failed to send command: {e}", flush=True)


def start_cec_client(adapter: str | None):
    cmd = ["cec-client", "-t", "p", "-d", "8"]
    # cec-client принимает [COM PORT] как позиционный аргумент :contentReference[oaicite:2]{index=2}
    if adapter:
        cmd.append(adapter)

    print(f"[INFO] Starting cec-client with adapter: {adapter or 'AUTO'}", flush=True)

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
    )


def read_output(proc):
    for line in proc.stdout:
        decoded = line.decode("utf-8", errors="ignore").strip()
        if DEBUG_LOG:
            print(decoded, flush=True)

        if ">>" in decoded or "<<" in decoded:
            timestamp = time.time()
            direction = "in" if ">>" in decoded else "out"
            hex_part = decoded.split(">>" if direction == "in" else "<<")[-1].strip()

            if direction == "in":
                client.publish(MQTT_TOPIC_RECEIVE, decoded)

            client.publish(MQTT_TOPIC_ALL, f"{timestamp}|{direction}|{hex_part}")
            topic = MQTT_TOPIC_IN if direction == "in" else MQTT_TOPIC_OUT
            client.publish(topic, f"{timestamp}|{hex_part}")


print("Waiting for CEC adapter to settle...", flush=True)
time.sleep(10)

# ---- Select adapter like bridge-app ----
selected_adapter = select_adapter()

process = start_cec_client(selected_adapter)
print("CEC listener ready (RX + TX via MQTT)", flush=True)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

reader = threading.Thread(target=read_output, args=(process,), daemon=True)
reader.start()

try:
    while True:
        if process.poll() is not None:
            print("cec-client exited, restarting...", flush=True)
            time.sleep(3)

            # если устройство/порт поменялся — попробуем пере-выбрать
            try:
                selected_adapter = select_adapter()
            except Exception as err:
                print(f"[WARN] Re-select adapter failed: {err}", flush=True)

            process = start_cec_client(selected_adapter)
            reader = threading.Thread(target=read_output, args=(process,), daemon=True)
            reader.start()

        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.loop_stop()
    if process and process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
