"""Constants for LuxPower Local."""

DOMAIN = "luxpower_local"
MANUFACTURER = "LuxPower"

DEFAULT_PORT = 8000

CONF_DATALOG = "datalog"
CONF_INVERTER = "inverter"
CONF_LEGACY_IDS = "legacy_entity_ids"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_HOLDING_INTERVAL = "holding_interval"
CONF_READ_BMS = "read_bms"
# PV strings whose sensors this integration has hidden as unused
CONF_HIDDEN_STRINGS = "hidden_pv_strings"

DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
DEFAULT_HOLDING_INTERVAL = 300
MIN_HOLDING_INTERVAL = 60
MAX_HOLDING_INTERVAL = 3600

# Polls that may fail in a row before entities go unavailable; the dongle's
# Wi-Fi drops the odd reply
FAILURES_BEFORE_UNAVAILABLE = 3

SERVICE_REFRESH = "refresh"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
