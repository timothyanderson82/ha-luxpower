"""What the inverter's input and holding registers mean.

Input registers are read in blocks of 40: 0-39 live readings and today's
energy, 40-79 lifetime energy, faults and temperatures, 80-119 what the
battery's BMS reports. Holding registers are the settings.

Ported from lxp-bridge (https://github.com/celsworth/lxp-bridge, MIT); scales
for the BMS block were checked against an SNA5000 with a Lux-compatible battery.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import time

BLOCK_SIZE = 40
INPUT_BLOCKS = (0, 40)
BMS_BLOCK = 80
# Holding blocks covering every setting below
HOLDING_BLOCKS = (0, 40, 80, 120, 160)

Registers = Mapping[int, int]


def _u16(regs: Registers, r: int) -> int:
    return regs[r]


def _s16(regs: Registers, r: int) -> int:
    value = regs[r]
    return value - 0x10000 if value & 0x8000 else value


def _u32(regs: Registers, r: int) -> int:
    # Low word first
    return regs[r] | regs[r + 1] << 16


@dataclass(frozen=True)
class Field:
    register: int
    read: Callable[[Registers, int], int] = _u16
    scale: float = 1

    def decode(self, regs: Registers) -> float | int:
        value = self.read(regs, self.register)
        return round(value / self.scale, 3) if self.scale != 1 else value


def _low_byte(regs: Registers, r: int) -> int:
    return regs[r] & 0xFF


def _high_byte(regs: Registers, r: int) -> int:
    return regs[r] >> 8


INPUT_FIELDS: dict[str, Field] = {
    # 0-39
    "status": Field(0),
    "v_pv_1": Field(1, scale=10),
    "v_pv_2": Field(2, scale=10),
    "v_pv_3": Field(3, scale=10),
    "v_bat": Field(4, scale=10),
    "soc": Field(5, _low_byte),
    "soh": Field(5, _high_byte),
    "p_pv_1": Field(7),
    "p_pv_2": Field(8),
    "p_pv_3": Field(9),
    "p_charge": Field(10),
    "p_discharge": Field(11),
    "v_ac_r": Field(12, scale=10),
    "f_ac": Field(15, scale=100),
    "p_inv": Field(16),
    "p_rec": Field(17),
    "pf": Field(19, scale=1000),
    "v_eps_r": Field(20, scale=10),
    "f_eps": Field(23, scale=100),
    "p_eps": Field(24),
    "s_eps": Field(25),
    "p_to_grid": Field(26),
    "p_to_user": Field(27),
    "e_pv_day_1": Field(28, scale=10),
    "e_pv_day_2": Field(29, scale=10),
    "e_pv_day_3": Field(30, scale=10),
    "e_inv_day": Field(31, scale=10),
    "e_rec_day": Field(32, scale=10),
    "e_chg_day": Field(33, scale=10),
    "e_dischg_day": Field(34, scale=10),
    "e_eps_day": Field(35, scale=10),
    "e_to_grid_day": Field(36, scale=10),
    "e_to_user_day": Field(37, scale=10),
    "v_bus_1": Field(38, scale=10),
    "v_bus_2": Field(39, scale=10),
    # 40-79
    "e_pv_all_1": Field(40, _u32, 10),
    "e_pv_all_2": Field(42, _u32, 10),
    "e_pv_all_3": Field(44, _u32, 10),
    "e_inv_all": Field(46, _u32, 10),
    "e_rec_all": Field(48, _u32, 10),
    "e_chg_all": Field(50, _u32, 10),
    "e_dischg_all": Field(52, _u32, 10),
    "e_eps_all": Field(54, _u32, 10),
    "e_to_grid_all": Field(56, _u32, 10),
    "e_to_user_all": Field(58, _u32, 10),
    "fault_code": Field(60, _u32),
    "warning_code": Field(62, _u32),
    "t_inner": Field(64, _s16),
    "t_rad_1": Field(65, _s16),
    "t_rad_2": Field(66, _s16),
    "t_bat": Field(67, _s16),
    "runtime": Field(69, _u32),
    # 80-119, from the battery's BMS
    "max_chg_curr": Field(81, scale=10),
    "max_dischg_curr": Field(82, scale=10),
    "charge_volt_ref": Field(83, scale=10),
    "dischg_cut_volt": Field(84, scale=10),
    "bat_count": Field(96),
    "bat_capacity": Field(97),
    "bat_current": Field(98, _s16, 10),
    "bms_fault": Field(99),
    "bms_warning": Field(100),
    "max_cell_voltage": Field(101, scale=1000),
    "min_cell_voltage": Field(102, scale=1000),
    "max_cell_temp": Field(103, _s16, 10),
    "min_cell_temp": Field(104, _s16, 10),
    "cycle_count": Field(106),
    "vbat_inv": Field(107, scale=10),
}

# Lifetime counters only ever grow; the inverter now and then reports a bogus
# lower value, which would otherwise look like a meter reset to the recorder.
LIFETIME_KEYS = frozenset(k for k in INPUT_FIELDS if k.endswith("_all") or "_all_" in k) | {
    "e_pv_all",
    "runtime",
}

STATUS = {
    0x00: "Standby",
    0x02: "FW updating",
    0x04: "PV on-grid",
    0x08: "PV charge",
    0x0C: "PV charge on-grid",
    0x10: "Battery on-grid",
    0x11: "Bypass",
    0x14: "PV & battery on-grid",
    0x19: "PV charge + bypass",
    0x20: "AC charge",
    0x28: "PV & AC charge",
    0x40: "Battery off-grid",
    0x80: "PV off-grid",
    0xC0: "PV & battery off-grid",
    0x88: "PV charge off-grid",
}

WARNINGS = {
    0: "W000: Battery communication failure",
    1: "W001: AFCI communication failure",
    2: "W002: AFCI high",
    3: "W003: Meter communication failure",
    4: "W004: Both charge and discharge forbidden by battery",
    5: "W005: Auto test failed",
    7: "W007: LCD communication failure",
    8: "W008: FW version mismatch",
    9: "W009: Fan stuck",
    11: "W011: Parallel number out of range",
    12: "W012: Bat On Mos",
    13: "W013: Overtemperature (NTC reading is too high)",
    15: "W015: Battery reverse connection",
    16: "W016: Grid power outage",
    17: "W017: Grid voltage out of range",
    18: "W018: Grid frequency out of range",
    20: "W020: PV insulation low",
    21: "W021: Leakage current high",
    22: "W022: DCI high",
    23: "W023: PV short",
    25: "W025: Battery voltage high",
    26: "W026: Battery voltage low",
    27: "W027: Battery open circuit",
    28: "W028: EPS overload",
    29: "W029: EPS voltage high",
    30: "W030: Meter reverse connection",
    31: "W031: DCV high",
}

FAULTS = {
    0: "E000: Internal communication fault 1",
    1: "E001: Model fault",
    2: "E002: BatOnMosFail",
    3: "E003: CT Fail",
    8: "E008: CAN communication error in parallel system",
    9: "E009: Master lost in parallel system",
    10: "E010: Multiple master units in parallel system",
    11: "E011: AC input inconsistent in parallel system",
    12: "E012: UPS short",
    13: "E013: Reverse current on UPS output",
    14: "E014: Bus short",
    15: "E015: Phase error in three phase system",
    16: "E016: Relay check fault",
    17: "E017: Internal communication fault 2",
    18: "E018: Internal communication fault 3",
    19: "E019: Bus voltage high",
    20: "E020: EPS connection fault",
    21: "E021: PV voltage high",
    22: "E022: Over current protection",
    23: "E023: Neutral fault",
    24: "E024: PV short",
    25: "E025: Radiator temperature over range",
    26: "E026: Internal fault",
    27: "E027: Sample inconsistent between Main CPU and redundant CPU",
    31: "E031: Internal communication fault 4",
}


def status_text(value: int) -> str:
    return STATUS.get(value, f"Unknown ({value:#04x})")


def code_text(value: int, names: Mapping[int, str], prefix: str) -> str:
    """Every code set in a fault or warning bitfield, or "OK"."""
    if not value:
        return "OK"
    codes = [names.get(bit, f"{prefix}{bit:03}") for bit in range(32) if value >> bit & 1]
    return "; ".join(codes)[:255]


def decode_inputs(regs: Registers) -> dict[str, float | int]:
    """Every field whose registers have been read, plus the derived totals."""
    values: dict[str, float | int] = {}
    for key, field in INPUT_FIELDS.items():
        width = 2 if field.read is _u32 else 1
        if all(field.register + i in regs for i in range(width)):
            values[key] = field.decode(regs)

    if {"p_pv_1", "p_pv_2", "p_pv_3"} <= values.keys():
        values["p_pv"] = values["p_pv_1"] + values["p_pv_2"] + values["p_pv_3"]
    if {"p_charge", "p_discharge"} <= values.keys():
        values["p_battery"] = values["p_charge"] - values["p_discharge"]
    if {"p_to_user", "p_to_grid"} <= values.keys():
        values["p_grid"] = values["p_to_user"] - values["p_to_grid"]
    if {"e_pv_day_1", "e_pv_day_2", "e_pv_day_3"} <= values.keys():
        values["e_pv_day"] = round(
            values["e_pv_day_1"] + values["e_pv_day_2"] + values["e_pv_day_3"], 1
        )
    if {"e_pv_all_1", "e_pv_all_2", "e_pv_all_3"} <= values.keys():
        values["e_pv_all"] = round(
            values["e_pv_all_1"] + values["e_pv_all_2"] + values["e_pv_all_3"], 1
        )
    return values


# Holding registers

REG_FUNCTIONS = 21
AC_CHARGE_BIT = 1 << 7
FORCED_DISCHARGE_BIT = 1 << 10
CHARGE_PRIORITY_BIT = 1 << 11

# Each time slot is two registers, start then end, each hour | minute << 8
TIME_SLOTS = {
    "ac_charge": (68, 70, 72),
    "charge_priority": (76, 78, 80),
    "forced_discharge": (84, 86, 88),
    "ac_first": (152, 154, 156),
}


def decode_time(value: int) -> time | None:
    hour, minute = value & 0xFF, value >> 8
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def encode_time(value: time) -> int:
    return value.hour | value.minute << 8
