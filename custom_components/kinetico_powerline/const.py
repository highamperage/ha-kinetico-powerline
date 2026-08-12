"""Constants for the Kinetico Powerline integration."""

DOMAIN = "kinetico_powerline"

CONF_MAC = "mac"
CONF_NAME = "name"

DEFAULT_SCAN_INTERVAL = 60  # seconds

# Threshold for rejecting suspicious updates where most numeric fields are 0
SUSPICIOUS_ZERO_THRESHOLD = 3
