# CEC MQTT Bridge

This add-on bridges HDMI-CEC and MQTT, enabling Home Assistant to send and receive CEC messages through any MQTT-based automation.

## How it works

The add-on runs `cec-client` as a subprocess and connects to your MQTT broker. Incoming CEC messages are parsed and published to MQTT topics. Commands received on the send topic are forwarded to the CEC bus.

## Configuration

| Option | Description | Default |
|---|---|---|
| `mqtt_host` | MQTT broker hostname | `core-mosquitto` |
| `mqtt_port` | MQTT broker port | `1883` |
| `mqtt_user` | MQTT username | (empty) |
| `mqtt_password` | MQTT password | (empty) |
| `mqtt_topic_send` | Topic to receive commands on | `cec/send` |
| `mqtt_topic_receive` | Topic for incoming CEC messages | `cec/receive` |
| `mqtt_topic_all` | Topic for all messages with timestamps | `cec/all` |
| `mqtt_topic_in` | Topic for incoming messages with timestamps | `cec/in` |
| `mqtt_topic_out` | Topic for outgoing messages with timestamps | `cec/out` |
| `debug_log` | Enable verbose logging | `false` |

## MQTT message formats

### Receiving (`cec/receive`)

Raw `cec-client` output line for incoming messages, e.g.:

```
TRAFFIC: [           12345]	>> 0f:36
```

### Timestamped topics (`cec/all`, `cec/in`, `cec/out`)

Pipe-delimited format:

```
1707000000.123|in|0f:36
1707000000.456|out|10:04
```

### Sending (`cec/send`)

Publish any valid `cec-client` command:

| Command | Description |
|---|---|
| `on 0` | Power on TV (device 0) |
| `standby 0` | Power off TV |
| `tx 10:6D` | Send raw CEC frame |
| `as` | Set active source |

## CEC adapter

The add-on expects a USB CEC adapter at `/dev/ttyACM0`. If your adapter uses a different device path, you may need to update the add-on configuration.
