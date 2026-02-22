import paho.mqtt.client as mqtt
import subprocess
import threading
import json
import os
import time
import re
import glob
import select

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
    DEBUG_LOG = bool(opts.get("debug_log", False))

    # Optional override: "/dev/cec0", "/dev/cec1", "Linux", "RPI", etc.
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
ADDON_VERSION = "1.5"

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


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            out.append(x)
            seen.add(x)
    return out


def list_adapters_from_cec_client():
    """
    cec-client -l часто печатает:
      device: 1 com port: /dev/cec0 ...
      device: 2 com port: /dev/cec1 ...
    На RPi/Kernel CEC иногда com port: Linux
    """
    try:
        r = subprocess.run(
            ["cec-client", "-l"],
            capture_output=True,
            text=True,
            timeout=6,
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
            if port and port.lower() not in ("none", "null"):
                ports.append(port)
    return _dedupe_keep_order(ports)


def build_candidate_adapters():
    # 1) explicit override
    if CEC_ADAPTER:
        return [CEC_ADAPTER]

    candidates = []

    # 2) prefer what libcec reports (best signal)
    candidates += list_adapters_from_cec_client()

    # 3) fallbacks (как в твоём bridge-app)
    if os.path.exists("/dev/cec0"):
        candidates.append("/dev/cec0")
    if os.path.exists("/dev/cec1"):
        candidates.append("/dev/cec1")
    candidates.append("RPI")

    return _dedupe_keep_order(candidates)


def _readline_timeout(pipe, timeout=0.5):
    """Read one line from proc stdout with timeout. Returns str|None."""
    try:
        r, _, _ = select.select([pipe], [], [], timeout)
    except Exception:
        return None
    if not r:
        return None
    try:
        line = pipe.readline()
    except Exception:
        return None
    if not line:
        return None
    return line.decode("utf-8", errors="ignore").strip()


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
            print(f"[DEBUG] Published discovery: {config_topic}", flush=True)

    print("[INFO] MQTT discovery configs published", flush=True)


def on_connect(mqtt_client, userdata, flags, rc):
    if rc == 0:
        print("[INFO] Connected to MQTT broker", flush=True)
        mqtt_client.subscribe(MQTT_TOPIC_SEND)
        publish_discovery(mqtt_client)
    else:
        print(f"[ERROR] MQTT connection failed with code {rc}", flush=True)


def on_message(mqtt_client, userdata, msg):
    global process
    command = msg.payload.decode(errors="ignore").strip()
    if not command:
        return

    if DEBUG_LOG:
        print(f"[DEBUG] Sending CEC command: {command}", flush=True)

    if process is None or process.poll() is not None:
        print("[WARN] Cannot send command, cec-client is not running", flush=True)
        return

    try:
        process.stdin.write((command + "\n").encode("utf-8", errors="ignore"))
        process.stdin.flush()
    except Exception as e:
        print(f"[ERROR] Failed to send command: {e}", flush=True)


def start_cec_client(adapter):
    """
    Запускаем интерактивный cec-client (НЕ -s), чтобы он:
      - слушал шину
      - принимал команды в stdin
    """
    cmd = ["cec-client", "-t", "p", "-d", "8"]
    # cec-client принимает [COM PORT] как позиционный аргумент: /dev/cec1, Linux, RPI, ...
    if adapter:
        cmd.append(adapter)

    print(f"[INFO] Starting cec-client with adapter: {adapter or 'AUTO'}", flush=True)

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
    )


def start_cec_client_with_fallbacks():
    """
    Автоопределение “как в bridge-app”:
      - строим список кандидатов
      - для каждого реально запускаем cec-client
      - отправляем 'scan' и читаем вывод
      - если процесс сразу умирает/пишет явную ошибку — следующий кандидат
      - первый “живой” считаем успешным
    """
    candidates = build_candidate_adapters()
    print(f"[INFO] CEC candidates: {candidates}", flush=True)

    last_preview = None

    for cand in candidates:
        print(f"[INFO] Trying CEC adapter: {cand}", flush=True)
        proc = start_cec_client(cand)

        # Попросим bus scan, чтобы быстрее увидеть успех/ошибку
        try:
            proc.stdin.write(b"scan\n")
            proc.stdin.flush()
        except Exception:
            pass

        captured = []
        deadline = time.time() + 12  # HAOS/libcec иногда стартует не мгновенно
        failed = False

        while time.time() < deadline:
            if proc.poll() is not None:
                failed = True
                break

            line = _readline_timeout(proc.stdout, timeout=0.5)
            if line is None:
                continue

            captured.append(line)
            low = line.lower()

            # явные признаки фейла
            if any(x in low for x in (
                "could not open a connection",
                "failed to open",
                "error opening",
                "unable to open",
                "no cec adapters found",
            )):
                failed = True
                break

            # мягкие признаки, что соединение открылось и процесс жив
            if any(x in low for x in (
                "opening a connection",
                "connection opened",
                "waiting for input",
                "press q to exit",
            )):
                # уже хорошо — можно выходить
                break

        if not failed and proc.poll() is None:
            if DEBUG_LOG and captured:
                print("[DEBUG] cec-client startup output (last lines):", flush=True)
                for l in captured[-12:]:
                    print(f"[DEBUG] {l}", flush=True)

            print(f"[INFO] Selected CEC adapter: {cand}", flush=True)
            return proc, cand

        # cleanup
        last_preview = "\n".join(captured[-12:])
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        if last_preview:
            print(f"[WARN] Adapter {cand} failed. Last output:\n{last_preview}", flush=True)
        else:
            print(f"[WARN] Adapter {cand} failed with no output.", flush=True)

        time.sleep(0.2)

    raise ConnectionError(f"Could not connect to CEC adapter (tried: {candidates})")


def read_output(proc):
    """
    Разбор вывода cec-client.
    Логи вида '>>'/'<<' мы публикуем как раньше (с timestamp).
    """
    for line in proc.stdout:
        decoded = line.decode("utf-8", errors="ignore").strip()
        if not decoded:
            continue

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


# ---- Main ----
print("Waiting for CEC adapter to settle...", flush=True)
time.sleep(10)

process, selected_adapter = start_cec_client_with_fallbacks()
print("[INFO] CEC listener ready (RX + TX via MQTT)", flush=True)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

reader = threading.Thread(target=read_output, args=(process,), daemon=True)
reader.start()

try:
    while True:
        if process.poll() is not None:
            print("[WARN] cec-client exited, restarting...", flush=True)
            time.sleep(3)

            # пере-выбираем адаптер (если что-то поменялось)
            process, selected_adapter = start_cec_client_with_fallbacks()

            reader = threading.Thread(target=read_output, args=(process,), daemon=True)
            reader.start()

        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.loop_stop()
    if process and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
