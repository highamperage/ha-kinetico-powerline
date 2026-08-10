"""
Kinetico Powerline BLE Protocol Module

Reverse-engineered from the Kinetico Powerline PRO Android app (v3.1.21)
by Chandler Systems Inc.

This module provides constants, command builders, and response parsers for
communicating with Kinetico Powerline series water treatment devices over BLE.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# BLE Service & Characteristic UUIDs
# ---------------------------------------------------------------------------
# The device supports three possible GATT service/characteristic sets.
# We try them in order until one is found.

UART_SERVICES = [
    {
        "name": "Nordic UART (NUS)",
        "service": "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
        "rx_char": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",  # Notify
        "tx_char": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",  # Write
    },
    {
        "name": "SIG UART",
        "service": "00001000-0000-1000-8000-00805f9b34fb",
        "rx_char": "00001002-0000-1000-8000-00805f9b34fb",
        "tx_char": "00001001-0000-1000-8000-00805f9b34fb",
    },
    {
        "name": "Chandler Custom",
        "service": "a725458c-bee1-4d2e-9555-edf5a8082303",
        "rx_char": "a725458c-bee2-4d2e-9555-edf5a8082303",
        "tx_char": "a725458c-bee3-4d2e-9555-edf5a8082303",
    },
]

# Device name prefixes used during BLE scanning
DEVICE_NAME_PREFIXES = ("CS_", "C2_")

# Known full device names
KNOWN_DEVICE_NAMES = {
    "CS_C_Meter_Soft": "Commercial Metered Softener",
    "CS_Meter_Soft": "Metered Softener",
    "CS_Meter_Soft_db": "Metered Softener (Debug)",
}

PACKET_SIZE = 20


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DeviceType(enum.IntEnum):
    """Device type reported in the handshake response (byte[3])."""
    UNKNOWN = -1
    METERED_SOFTENER = 0
    TIMECLOCK_SOFTENER = 1
    BACKWASHING_FILTER = 2
    ULTRA_FILTER = 3
    CENTURION_NITRO = 4
    CENTURION_NITRO_SIDEKICK = 5
    CENTURION_NITRO_SIDEKICK_V3 = 6
    NITRO_PRO = 7
    NITRO_PRO_SIDEKICK = 8
    COMMERCIAL_METERED_SOFTENER = 9
    COMMERCIAL_BACKWASHING_FILTER = 10

    @classmethod
    def from_byte(cls, b: int) -> "DeviceType":
        """Map the raw handshake valve-type byte to a DeviceType."""
        _MAP = {
            1: cls.METERED_SOFTENER,
            2: cls.TIMECLOCK_SOFTENER,
            3: cls.METERED_SOFTENER,  # alias
            4: cls.BACKWASHING_FILTER,
            5: cls.BACKWASHING_FILTER,
            6: cls.BACKWASHING_FILTER,
            7: cls.BACKWASHING_FILTER,
            8: cls.ULTRA_FILTER,
            9: cls.CENTURION_NITRO,
            10: cls.CENTURION_NITRO_SIDEKICK,
            11: cls.CENTURION_NITRO,
            12: cls.CENTURION_NITRO_SIDEKICK,
            13: cls.NITRO_PRO,
            14: cls.NITRO_PRO_SIDEKICK,
            15: cls.NITRO_PRO_SIDEKICK,
            16: cls.CENTURION_NITRO_SIDEKICK_V3,
            17: cls.COMMERCIAL_METERED_SOFTENER,
            18: cls.COMMERCIAL_BACKWASHING_FILTER,
        }
        return _MAP.get(b, cls.UNKNOWN)

    def friendly_name(self) -> str:
        _NAMES = {
            self.UNKNOWN: "Unknown",
            self.METERED_SOFTENER: "Metered Softener",
            self.TIMECLOCK_SOFTENER: "Timeclock Softener",
            self.BACKWASHING_FILTER: "Backwashing Filter",
            self.ULTRA_FILTER: "Ultra Filter",
            self.CENTURION_NITRO: "Centurion Nitro",
            self.CENTURION_NITRO_SIDEKICK: "Centurion Nitro Sidekick",
            self.CENTURION_NITRO_SIDEKICK_V3: "Centurion Nitro Sidekick V3",
            self.NITRO_PRO: "Nitro Pro",
            self.NITRO_PRO_SIDEKICK: "Nitro Pro Sidekick",
            self.COMMERCIAL_METERED_SOFTENER: "Commercial Metered Softener",
            self.COMMERCIAL_BACKWASHING_FILTER: "Commercial Backwashing Filter",
        }
        return _NAMES.get(self, "Unknown")


class SaltStatus(enum.IntEnum):
    UNKNOWN = -1
    OK = 0
    LOW = 1

    @classmethod
    def from_int(cls, v: int) -> "SaltStatus":
        try:
            return cls(v)
        except ValueError:
            return cls.UNKNOWN


class SignatureVersion(enum.IntEnum):
    UNKNOWN = 0
    VERSION_2 = 2
    VERSION_3 = 3
    VERSION_4 = 4
    VERSION_5 = 5

    @classmethod
    def from_int(cls, v: int) -> "SignatureVersion":
        try:
            return cls(v)
        except ValueError:
            return cls.UNKNOWN

    def friendly_name(self) -> str:
        _NAMES = {
            0: "Unknown",
            2: "Series 2",
            3: "Series 3",
            4: "Series CS125",
            5: "Series CS150",
        }
        return _NAMES.get(self.value, "Unknown")


class CommandScreen(enum.Enum):
    """The 'screen' context for a command — determines the fill byte."""
    RESET = 0x72           # 'r'
    DEVICE_LIST = 0x74     # 't'
    DASHBOARD = 0x75       # 'u'
    ADVANCED_SETTINGS = 0x76  # 'v'
    STATUS_HISTORY = 0x77  # 'w'
    HANDSHAKE = 0x82       # 130
    DEALER_INFO = 0x78     # 'x'


class AuthStatus(enum.IntEnum):
    NOT_AUTHENTICATED = 0
    AUTHENTICATED = 1
    UNKNOWN = 255

    @classmethod
    def from_byte(cls, b: int) -> "AuthStatus":
        if b & 0x80:
            return cls.AUTHENTICATED
        return cls.NOT_AUTHENTICATED


# ---------------------------------------------------------------------------
# Byte Utility Functions (ported from AbstractC1759b / AbstractC1766i)
# ---------------------------------------------------------------------------

def unsigned_byte(b: int) -> int:
    """Convert a signed byte to unsigned (Java's `byte & 0xFF`)."""
    return b & 0xFF


def is_negative_byte(b: int) -> bool:
    """Check if high bit is set (Java: `(b & 128) == 128`)."""
    return (b & 0x80) == 0x80


def bytes_to_uint16_le(low: int, high: int) -> int:
    """Little-endian two-byte unsigned integer (Java: m9335d)."""
    return unsigned_byte(high) * 256 + unsigned_byte(low)


def bcd_byte(b: int) -> int:
    """
    Convert a BCD-encoded byte to an integer.
    E.g. 0x41 → 41, 0x10 → 10.
    Java impl: format as %02X hex string, then parseInt as decimal.
    Equivalent: ((b / 16) * 10) + (b % 16), treating b as unsigned.
    """
    u = unsigned_byte(b)
    return ((u >> 4) * 10) + (u & 0x0F)


def firmware_version_from_bytes(major_byte: int, minor_byte: int) -> int:
    """
    Combine two BCD-encoded bytes into a firmware version integer.
    E.g. 0x04, 0x12 → 412.
    Java: m9422l → m9438l → bcd(b7) * 100 + min(bcd(b8), 99)
    """
    major = bcd_byte(major_byte)
    minor = bcd_byte(minor_byte)
    if minor >= 250:
        minor = 99
    return major * 100 + minor


def firmware_version_from_raw(major_byte: int, minor_byte: int) -> int:
    """
    Combine two raw bytes into a firmware version (non-BCD path).
    Java: m9421k → m9437k → b7 * 100 + min(b8 & 0xFF, 99)
    Used in the handshake response parser.
    """
    major = major_byte
    minor = unsigned_byte(minor_byte)
    if minor >= 250:
        minor = 99
    return major * 100 + minor


def check_bit(value: int, bit_pos: int) -> bool:
    """Check if bit at 1-based position is set. Java: m9337f."""
    return (value & (1 << (bit_pos - 1))) != 0


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class AdvertisementData:
    """Parsed manufacturer-specific advertisement data (from C2281y)."""
    is_valid: bool = False
    auth_required: bool = False
    salt_status: SaltStatus = SaltStatus.UNKNOWN
    time_hours: int = 0
    time_minutes: int = 0
    connection_counter: int = 0
    bootloader_version: int = 0
    signature_version: SignatureVersion = SignatureVersion.UNKNOWN
    valve_type_raw: int = 0
    firmware_version: int = 0
    is_400_series: bool = False
    is_commercial: bool = False


@dataclass
class HandshakeResponse:
    """Parsed initial connection response (from C0653d)."""
    is_valid: bool = False
    device_type: DeviceType = DeviceType.UNKNOWN
    supports_advanced: bool = False
    firmware_version: int = 0
    firmware_string: str = ""
    firmware_major: int = 0
    firmware_minor: int = 0
    auth_status: AuthStatus = AuthStatus.UNKNOWN
    serial_number: str = ""
    pin_required: bool = False
    valve_status_bits: list[bool] = field(default_factory=list)
    connection_counter: int = 0
    radio_protocol: int = 0


@dataclass
class DashboardData:
    """Parsed dashboard state (from C0650a, packet type B)."""
    is_valid: bool = False
    days_until_regen: int = 0
    days_since_regen: int = 0
    hardness_gpg: int = 0
    capacity_remaining: int = 0       # × 1000 grains
    is_regenerating: bool = False
    has_error: bool = False
    salt_sensor: int = 0
    config_byte_1: int = 0
    config_byte_2: int = 0
    interval: int = 0
    feature_flags: int = 0
    # Feature flag booleans (firmware >= 410)
    feature_a_active: bool = False
    feature_b_active: bool = False
    feature_c_active: bool = False
    feature_d_active: bool = False
    feature_e_active: bool = False


@dataclass
class TankLevelsData:
    """Parsed tank level percentages (from C0650a, packet type 1)."""
    is_valid: bool = False
    levels: list[int] = field(default_factory=lambda: [0] * 8)
    level_negative: list[bool] = field(default_factory=lambda: [False] * 8)


# ---------------------------------------------------------------------------
# Advertisement Data Parser
# ---------------------------------------------------------------------------

def parse_advertisement(mfr_data: bytes) -> AdvertisementData:
    """
    Parse manufacturer-specific data from BLE advertisements.
    Ported from C2281y constructor.
    """
    result = AdvertisementData()

    if len(mfr_data) < 11:
        return result

    # Firmware version from the last 2 bytes
    fw = firmware_version_from_bytes(mfr_data[-2], mfr_data[-1])
    result.firmware_version = fw
    result.is_400_series = True  # If we get here with enough bytes

    is_400_series = fw >= 412

    # Byte offsets shift based on firmware version
    if is_400_series and len(mfr_data) < 14:
        return result

    # Offsets for different fields
    bootloader_idx = 8 if is_400_series else 6
    sig_version_idx = 9 if is_400_series else 7
    valve_type_idx = 11 if is_400_series else (9 if len(mfr_data) == 12 else 8)
    radio_proto_idx = 10 if is_400_series else 8

    result.is_valid = True

    # Valve status bitfield (bytes 2-3 → 16 booleans)
    status_bits = parse_valve_status(mfr_data[2], mfr_data[3])
    if len(status_bits) > 0:
        result.auth_required = status_bits[0]
    if len(status_bits) > 1:
        result.salt_status = SaltStatus.LOW if status_bits[1] else SaltStatus.OK

    result.time_hours = unsigned_byte(mfr_data[4])
    result.time_minutes = unsigned_byte(mfr_data[5])
    result.connection_counter = unsigned_byte(mfr_data[6]) if is_400_series else 0
    result.bootloader_version = unsigned_byte(mfr_data[bootloader_idx])
    result.signature_version = SignatureVersion.from_int(
        unsigned_byte(mfr_data[sig_version_idx])
    )
    result.valve_type_raw = unsigned_byte(mfr_data[valve_type_idx])

    return result


def parse_valve_status(byte1: int, byte2: int) -> list[bool]:
    """Parse 2 bytes into a list of 16 boolean status flags."""
    bits = []
    combined = (unsigned_byte(byte1) << 8) | unsigned_byte(byte2)
    for i in range(16):
        bits.append(bool(combined & (1 << (15 - i))))
    return bits


# ---------------------------------------------------------------------------
# Handshake Response Parser
# ---------------------------------------------------------------------------

def is_valid_handshake(data: bytes) -> bool:
    """Check if bytes are a valid handshake response. From C0653d.m5422p."""
    if len(data) < 14:
        return False
    return data[0] == 0x74 and data[1] == 0x74


def parse_handshake(data: bytes, length: int = 0) -> HandshakeResponse:
    """
    Parse the initial handshake response received after BLE connection.
    Ported from C0653d.m5435s.
    """
    result = HandshakeResponse()

    if not is_valid_handshake(data):
        return result

    result.is_valid = True
    is_classic = data[2] == 0x74  # Classic/SPP mode vs BLE mode

    # Device type from byte[3]
    result.device_type = DeviceType.from_byte(data[3])

    # Supports advanced features (byte[4] == 0xCA)
    result.supports_advanced = (data[4] == 0xCA)

    # PIN required
    if not is_classic:
        result.pin_required = (data[12] == 1)

    # Firmware version
    result.firmware_major = data[5]
    result.firmware_minor = (
        99 if (unsigned_byte(data[6]) >= 250) else bcd_byte(data[6])
    ) if not is_classic else 10
    result.firmware_version = firmware_version_from_raw(data[5], data[6])
    result.firmware_string = format_firmware_version(result.firmware_version)

    # Firmware >= 420 has additional auth fields
    if result.firmware_version >= 420:
        result.auth_status = AuthStatus.from_byte(unsigned_byte(data[7]))
        result.radio_protocol = unsigned_byte(data[8])
        result.valve_status_bits = parse_valve_status(data[9], data[10])
        result.connection_counter = unsigned_byte(data[11])

    # Serial number (bytes 13-16 as hex)
    if not is_classic and length >= 18:
        serial_hex = (
            f"{data[13] & 0xFF:02X}"
            f"{data[14] & 0xFF:02X}"
            f"{data[15] & 0xFF:02X}"
            f"{data[16] & 0xFF:02X}"
        )
        if serial_hex != "FFFFFFFF" and serial_hex.strip():
            result.serial_number = serial_hex

    return result


# ---------------------------------------------------------------------------
# Dashboard Response Parsers
# ---------------------------------------------------------------------------

def parse_dashboard(
    data: bytes,
    length: int,
    firmware_version: int,
    device_type: DeviceType = DeviceType.METERED_SOFTENER,
) -> Optional[DashboardData]:
    """
    Parse a dashboard data response (packet type B).
    Ported from C0650a.m5324A.

    Expects: data[0:3] == [0x76, 0x76, 0x00] and data[19] == 0x42 ('B')
    """
    if len(data) < 20 or length != 20:
        return None

    if data[0] != 0x76 or data[1] != 0x76:
        return None

    if data[2] == 0x00 and data[19] == 0x42:  # 'B' → settings packet
        result = DashboardData(is_valid=True)
        result.days_until_regen = unsigned_byte(data[3])
        result.days_since_regen = unsigned_byte(data[4])
        result.hardness_gpg = unsigned_byte(data[5])
        result.capacity_remaining = bytes_to_uint16_le(data[6], data[7])
        result.is_regenerating = (data[8] == 11)  # 0x0B
        result.has_error = (data[9] != 0)
        result.salt_sensor = data[10]
        result.config_byte_1 = data[11]
        result.config_byte_2 = data[15]

        if firmware_version >= 210:
            result.config_byte_2 = data[12]
            result.interval = max(1, unsigned_byte(data[13]))
            # bit 3 of byte 14
            result.feature_flags = data[14]

        if firmware_version >= 410:
            flags = unsigned_byte(data[16])
            result.feature_a_active = check_bit(flags, 1)
            result.feature_b_active = check_bit(flags, 2)
            result.feature_c_active = check_bit(flags, 3)
            result.feature_d_active = check_bit(flags, 4)
            result.feature_e_active = check_bit(flags, 5)

        return result

    if data[2] == 0x01:  # Tank levels packet
        return None  # Handled by parse_tank_levels

    return None


def parse_tank_levels(
    data: bytes,
    length: int,
    device_type: DeviceType = DeviceType.METERED_SOFTENER,
) -> Optional[TankLevelsData]:
    """
    Parse tank level percentage data (packet type 1).
    Ported from C0650a.m5324A (the second branch).

    Expects: data[0:3] == [0x76, 0x76, 0x01]
    """
    if len(data) < 11:
        return None
    if data[0] != 0x76 or data[1] != 0x76 or data[2] != 0x01:
        return None
    if length != 20:
        return None

    result = TankLevelsData(is_valid=True)
    for i in range(8):
        raw = data[3 + i]
        is_neg = is_negative_byte(raw)
        is_commercial_tank4 = (
            device_type == DeviceType.COMMERCIAL_METERED_SOFTENER and i == 4
        )
        result.level_negative[i] = not is_commercial_tank4 and is_neg
        if is_commercial_tank4:
            result.levels[i] = unsigned_byte(raw)
        elif is_neg:
            # Signed byte + 128 offset
            result.levels[i] = (raw & 0xFF) - 128 + 128  # effectively unsigned
            result.levels[i] = raw + 128 if raw < 0 else unsigned_byte(raw)
        else:
            result.levels[i] = raw if raw >= 0 else raw + 256

    return result


# ---------------------------------------------------------------------------
# Command Builders
# ---------------------------------------------------------------------------

class CryptoLFSR:
    def __init__(self, poly: int, seed: int):
        self.poly = poly & 0xFF
        self.state = seed & 0xFF

    def hash_byte(self, b: int) -> int:
        """Translates AbstractC1760c.m9362c."""
        b = b & 0xFF
        for _ in range(8):
            z6 = (self.state & 0x80) != 0
            self.state = (self.state << 1) & 0xFF
            if (b & 0x80) != 0:
                self.state = (self.state | 1) & 0xFF
            b = (b << 1) & 0xFF
            if z6:
                self.state = (self.state ^ self.poly) & 0xFF
        return self.state


def _format_bcd(value: int) -> bytes:
    """Helper to format a 4 digit integer as 4 BCD bytes. E.g. 1234 -> [0x04, 0x03, 0x02, 0x01]"""
    # Max 9999
    value = max(0, min(9999, value))
    return bytes([
        value % 10,
        (value // 10) % 10,
        (value // 100) % 10,
        (value // 1000) % 10
    ])

def _make_packet(screen: CommandScreen) -> bytearray:
    """Create a 20-byte packet filled with the screen's fill byte."""
    return bytearray([screen.value] * PACKET_SIZE)


def cmd_reset() -> bytes:
    """Send a reset/disconnect command."""
    return bytes(_make_packet(CommandScreen.RESET))

def cmd_handshake() -> bytes:
    """Request handshake/device info."""
    return bytes(_make_packet(CommandScreen.DEVICE_LIST))

def cmd_auth(counter: int = 0, pin: int = 1234, fw_420_plus: bool = True) -> bytes:
    """
    Constructs the authentication packet.
    fw_420_plus: True for firmware >= 4.20 which uses LFSR encryption.
    """
    import random
    pkt = _make_packet(CommandScreen.DEVICE_LIST)
    pkt[2] = 0x50  # 'P'
    pkt[3] = 0x57  # 'W'
    pin_bcd = _format_bcd(pin)
    pin_bcd_1 = _format_bcd(pin)  # In Java, f14439J1 is also the PIN!
    
    if not fw_420_plus:
        pkt[4] = pin_bcd[3]
        pkt[5] = pin_bcd[2]
        pkt[6] = pin_bcd[1]
        pkt[7] = pin_bcd[0]
        return bytes(pkt)
        
    # Generate random poly (must have 4 or 5 bits set)
    valid_polys = [i for i in range(1, 256) if 4 <= bin(i).count('1') <= 5]
    poly = random.choice(valid_polys)
    
    seed = random.randint(1, 255)
    lfsr = CryptoLFSR(poly, seed)
    
    salt2 = (random.randint(1, 255) ^ seed) & 0xFF
    bM9356i = (counter ^ lfsr.hash_byte(salt2)) & 0xFF
    
    pkt[4] = poly & 0xFF
    pkt[5] = seed & 0xFF
    pkt[6] = salt2 & 0xFF
    
    pkt[7] = (pin_bcd_1[3] ^ lfsr.hash_byte(bM9356i)) & 0xFF
    pkt[8] = (pin_bcd_1[2] ^ lfsr.hash_byte(pkt[7])) & 0xFF
    pkt[9] = (pin_bcd_1[1] ^ lfsr.hash_byte(pkt[8])) & 0xFF
    pkt[10] = (pin_bcd_1[0] ^ lfsr.hash_byte(pkt[9])) & 0xFF
    
    pkt[11] = (pin_bcd[3] ^ lfsr.hash_byte(pkt[10])) & 0xFF
    pkt[12] = (pin_bcd[2] ^ lfsr.hash_byte(pkt[11])) & 0xFF
    pkt[13] = (pin_bcd[1] ^ lfsr.hash_byte(pkt[12])) & 0xFF
    pkt[14] = (pin_bcd[0] ^ lfsr.hash_byte(pkt[13])) & 0xFF
    pkt[15] = lfsr.hash_byte(pkt[13]) & 0xFF
    
    for i in range(16, 20):
        pkt[i] = random.randint(1, 255)
        
    return bytes(pkt)

def cmd_auth_pa(counter: int, pin: int = 1234) -> bytes:
    """
    Builds the Password Auth (PA) command. This is used when pin_required is False.
    The PA packet encrypts a single 4-byte PIN (default 1234) and uses 11 bytes of payload.
    """
    import random
    pkt = bytearray(20)
    pkt[0:2] = b"\x74\x74"
    pkt[2:4] = b"PA"
    
    poly = random.randint(1, 255)
    seed = random.randint(1, 255)
    lfsr = CryptoLFSR(poly, seed)
    
    salt2 = (random.randint(1, 255) ^ seed) & 0xFF
    bM9356i = (counter ^ lfsr.hash_byte(salt2)) & 0xFF
    
    pkt[4] = poly & 0xFF
    pkt[5] = seed & 0xFF
    pkt[6] = salt2 & 0xFF
    
    pin_bcd = _format_bcd(pin)
    
    pkt[7] = (pin_bcd[3] ^ lfsr.hash_byte(bM9356i)) & 0xFF
    pkt[8] = (pin_bcd[2] ^ lfsr.hash_byte(pkt[7])) & 0xFF
    pkt[9] = (pin_bcd[1] ^ lfsr.hash_byte(pkt[8])) & 0xFF
    pkt[10] = (pin_bcd[0] ^ lfsr.hash_byte(pkt[9])) & 0xFF
    
    for i in range(11, 20):
        pkt[i] = random.randint(1, 255)
        
    return bytes(pkt)

def cmd_dashboard() -> bytes:
    """Request dashboard data. Just the fill pattern for Dashboard screen."""
    return bytes(_make_packet(CommandScreen.DASHBOARD))


def cmd_advanced_settings() -> bytes:
    """Request advanced settings page data."""
    return bytes(_make_packet(CommandScreen.ADVANCED_SETTINGS))


def cmd_status_history_a() -> bytes:
    """Request status/history page A."""
    pkt = _make_packet(CommandScreen.STATUS_HISTORY)
    pkt[13] = 0x41  # 'A'
    return bytes(pkt)


def cmd_status_history_b() -> bytes:
    """Request status/history page B."""
    pkt = _make_packet(CommandScreen.STATUS_HISTORY)
    pkt[13] = 0x42  # 'B'
    return bytes(pkt)


def cmd_set_time(hour: int, minute: int, second: int, is_pm: bool) -> bytes:
    """
    Set the device clock.
    hour: 1-12, minute: 0-59, second: 0-59
    """
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x54  # 'T'
    pkt[14] = max(1, min(12, hour))
    pkt[15] = max(0, min(59, minute))
    pkt[16] = 1 if is_pm else 0
    pkt[17] = max(0, min(59, second))
    return bytes(pkt)


def cmd_set_salt_level(level: int) -> bytes:
    """Set the brine tank salt level (0-99)."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x48  # 'H'
    pkt[14] = max(0, min(99, level))
    return bytes(pkt)


def cmd_regen_now() -> bytes:
    """Trigger an immediate regeneration cycle."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x52  # 'R'
    pkt[14] = 0x54  # 'T' — trigger now
    return bytes(pkt)


def cmd_regen_next() -> bytes:
    """Schedule regeneration for the next scheduled time."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x52  # 'R'
    pkt[14] = 0x4E  # 'N' — next scheduled
    return bytes(pkt)


def cmd_regen_bypass(active: bool) -> bytes:
    """Enable/disable regeneration bypass."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x52  # 'R'
    pkt[14] = 0x4F  # 'O'
    pkt[15] = 1 if active else 0
    return bytes(pkt)


def cmd_set_regen_time(hour: int, is_pm: bool) -> bytes:
    """Set the scheduled regeneration time (hour 1-12)."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x74  # 't'
    pkt[14] = max(1, min(12, hour))
    pkt[15] = 1 if is_pm else 0
    return bytes(pkt)


def cmd_set_regen_days(days: int) -> bytes:
    """Set regeneration frequency in days (0-29)."""
    pkt = _make_packet(CommandScreen.DASHBOARD)
    pkt[13] = 0x46  # 'F'
    pkt[14] = max(0, min(29, days))
    return bytes(pkt)


def cmd_set_capacity(value: int) -> bytes:
    """Set softener capacity (0-399)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    value = max(0, min(399, value))
    pkt[13] = 0x43  # 'C'
    pkt[14] = value // 256
    pkt[15] = value % 256
    return bytes(pkt)


def cmd_set_hardness(hardness_type: int, value: int, is_commercial: bool = False) -> bytes:
    """Set water hardness. Type is the position enum, value 0-199."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x50  # 'P'
    pkt[14] = hardness_type
    pkt[15] = max(0, min(199 if is_commercial else 99, value))
    return bytes(pkt)


def cmd_set_efficiency(value: int) -> bytes:
    """Set efficiency setting (0-9)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x45  # 'E'
    pkt[14] = max(0, min(9, value))
    return bytes(pkt)


def cmd_set_blending(value: int) -> bytes:
    """Set blending target (0-49)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x42  # 'B'
    pkt[14] = max(0, min(49, value))
    return bytes(pkt)


def cmd_set_day_override(days: int) -> bytes:
    """Set advanced day override (0-29)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x41  # 'A'
    pkt[14] = max(0, min(29, days))
    return bytes(pkt)


def cmd_set_direction(direction: int) -> bytes:
    """Set flow direction (0 or 1)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x44  # 'D'
    pkt[14] = max(0, min(1, direction))
    return bytes(pkt)


def cmd_set_filter(filter_type: int) -> bytes:
    """Set filter type (0-4)."""
    pkt = _make_packet(CommandScreen.ADVANCED_SETTINGS)
    pkt[13] = 0x46  # 'F'
    pkt[14] = max(0, min(4, filter_type))
    return bytes(pkt)


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def format_firmware_version(version: int) -> str:
    """Format a firmware version integer like 412 → '4.12'."""
    major = version // 100
    minor = version % 100
    return f"{major}.{minor:02d}"


def format_bytes_hex(data: bytes) -> str:
    """Format bytes as a hex dump string."""
    return " ".join(f"{b:02X}" for b in data)
