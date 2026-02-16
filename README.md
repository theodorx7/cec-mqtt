# CEC MQTT Add-on

This add-on listens to HDMI-CEC messages and publishes them to MQTT, and also allows sending commands from Home Assistant.

This was originally created to work around the Nintendo Switch's broken HDMI-CEC implementation, which broadcasts CEC messages but does not respond to CEC commands. A sample Home Assistant configuration for detecting Nintendo Switch power state is provided in [nintendo.yml](examples/nintendo.yml).

## MQTT Topics

- **Receive**: `cec/receive`
  All incoming CEC messages are published here.

- **Send**: `cec/send`
  Send CEC commands (like `on 0`, `standby 0`, `tx 10:6D`, etc.)

## Example Automations

### Sensor: Last CEC Message

```yaml
mqtt:
  sensor:
    - name: "CEC Last Message"
      state_topic: "cec/receive"
```

### Switch: Turn TV On/Off via MQTT

```yaml
mqtt:
  switch:
    - name: "TV Power"
      command_topic: "cec/send"
      payload_on: "on 0"
      payload_off: "standby 0"
```

### Automation: Turn on light when TV is powered on

```yaml
automation:
  - alias: "Light on TV On"
    trigger:
      platform: state
      entity_id: sensor.cec_last_message
    condition:
      condition: template
      value_template: "{{ '44:6d' in trigger.to_state.state }}"
    action:
      - service: light.turn_on
        target:
          entity_id: light.tv_backlight
```

## Sample Commands to Send via MQTT

| Command     | Description            |
|-------------|------------------------|
| `on 0`      | Power on TV (logical 0)|
| `standby 0` | Power off TV           |
| `tx 10:6D`  | Send raw frame         |
| `as`        | Set active source      |
