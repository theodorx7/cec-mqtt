# Changelog

## 1.4

- Add repository URL link to add-on details page
- Add changelog
- Fix sample commands in documentation
- Remove misleading `as` command from examples

## 1.3

- Shorten auto-discovered sensor entity names
- Set explicit entity IDs via MQTT discovery `object_id`

## 1.2

- Add MQTT auto-discovery for sensor entities (no manual YAML needed)
- Sensors grouped under a CEC MQTT Bridge device in Home Assistant
- Re-subscribe and re-publish discovery on MQTT reconnect

## 1.1

- All MQTT topics configurable from add-on settings
- Fix race condition: CEC subprocess starts before MQTT connects
- Crash recovery: auto-restart cec-client on exit
- Replace busy-wait with sleep loop and process health monitoring
- Guard against sending commands when cec-client is not running
- Mask MQTT password in add-on UI
- Add DOCS.md for add-on documentation tab
- Add icon and logo

## 1.0

- Initial release
- Bridge HDMI-CEC to MQTT via cec-client
- Publish incoming CEC messages to configurable MQTT topics
- Send CEC commands by publishing to MQTT
