import paho.mqtt.client as mqtt

import subprocess
import threading
import json
import os
import time

options_path = "/data/options.json"
if os.path.exists(options_path):
    with open(options_path, "r") as f:
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

process = None

client = mqtt.Client()

if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)


def on_message(client, userdata, msg):
    command = msg.payload.decode().strip()
    if DEBUG_LOG:
        print(f"Sending CEC command: {command}", flush=True)
    if process is None or process.poll() is not None:
        print(f"Cannot send command, cec-client is not running", flush=True)
        return
    try:
        process.stdin.write((command + "\n").encode())
        process.stdin.flush()
    except Exception as e:
        print(f"Failed to send command: {e}", flush=True)


def start_cec_client():
    return subprocess.Popen(
        ["cec-client", "-t", "p", "-d", "8"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
    )


def read_output(proc):
    for line in proc.stdout:
        decoded = line.decode("utf-8").strip()

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

client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe(MQTT_TOPIC_SEND)
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
