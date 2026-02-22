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

## Sensors

The add-on automatically registers three sensor entities in Home Assistant via [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery):

| Entity | Description | MQTT topic |
|---|---|---|
| `sensor.cec_last_message` | All CEC traffic (in + out) | `cec/all` |
| `sensor.cec_last_incoming` | Incoming CEC frames only | `cec/in` |
| `sensor.cec_last_outgoing` | Outgoing CEC frames only | `cec/out` |

These sensors appear under the **CEC MQTT Bridge** device in Home Assistant. No manual YAML configuration is required.

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
| `tx 10:8F` | Request TV power status |

## CEC adapter

The add-on expects a USB CEC adapter at `/dev/ttyACM0`. If your adapter uses a different device path, you may need to update the add-on configuration.
