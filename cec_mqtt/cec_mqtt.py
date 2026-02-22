import paho.mqtt.client as mqtt
import subprocess
import threading
import json
import os
import time
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

    # Optional override: "/dev/cec0" or "/dev/cec1"
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

client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""


def autodetect_cec_adapter() -> str:
    """
    Priority:
      1) Use explicit CEC_ADAPTER if set (e.g. /dev/cec1).
      2) If only one /dev/cec* exists -> use it.
      3) If multiple /dev/cec* exist -> try to pick based on DRM connector status.
      4) Fallback -> /dev/cec0 if exists, else empty string (cec-client auto).
    """
    if CEC_ADAPTER:
        return CEC_ADAPTER

    cec_devs = sorted(glob.glob("/dev/cec[0-9]*"))
    if len(cec_devs) == 1:
        return cec_devs[0]

    if len(cec_devs) >= 2:
        # Common mapping on RPi KMS:
        # HDMI-A-1 -> /dev/cec0
        # HDMI-A-2 -> /dev/cec1
        drm_status_files = glob.glob("/sys/class/drm/*HDMI-A-*/status")
        connected = set()

        for st in drm_status_files:
            status = _read_text(st)
            connector = os.path.basename(os.path.dirname(st))  # e.g. card1-HDMI-A-1
            if status == "connected":
                connected.add(connector)

        if len(connected) == 1:
            conn = next(iter(connected))
            if conn.endswith("HDMI-A-1") and "/dev/cec0" in cec_devs:
                return "/dev/cec0"
            if conn.endswith("HDMI-A-2") and "/dev/cec1" in cec_devs:
                return "/dev/cec1"

        if "/dev/cec0" in cec_devs:
            return "/dev/cec0"
        return cec_devs[0]

    return ""


def publish_discovery(mqtt_client):
    """Publish MQTT discovery configs so HA auto-creates sensor entities."""
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


def start_cec_client():
    adapter = autodetect_cec_adapter()
    cmd = ["cec-client", "-t", "p", "-d", "8"]

    # cec-client supports optional [COM PORT] argument (e.g. /dev/cec1).
    # If not provided, it connects to the first detected device.
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

process = start_cec_client()
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
            time.sleep(5)
            process = start_cec_client()
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
