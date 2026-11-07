# LuxPower Local

A Home Assistant integration for LuxPower inverters (tested on an SNA5000) that
talks straight to the inverter's Wi-Fi dongle on TCP port 8000. No MQTT broker
or bridge container is needed, and the LuxPower cloud keeps working alongside
it: the dongle only sends replies to the connection that asked.

## What you get

- **Sensors**: power (PV per string, battery, grid, EPS, inverter), today's and
  lifetime energy, voltages, frequencies, temperatures, status, fault and
  warning codes. The lifetime totals work with the energy dashboard.
- **Battery BMS data**, if your battery reports it: cell voltages and
  temperatures, charge and discharge current limits, capacity, cycle count.
- **Numbers** for the charge and discharge rates and SOC limits.
- **Switches** for AC charge, charge priority and forced discharge.
- **Times** for the start and end of each AC charge, charge priority, forced
  discharge and AC first time slot.

## Setup

Install with HACS as a custom repository, restart, then add **LuxPower Local**
under Settings → Devices & services. You need:

- the dongle's IP address (give it a fixed lease)
- the dongle's 10-character serial, from its label or the LuxPower app
  ("datalog")

The inverter's own serial is read from the dongle.

## Options

| Option | Default | |
| --- | --- | --- |
| Reading interval | 10 s | How often power, energy and temperatures are read (5–300 s). |
| Settings interval | 300 s | How often settings are re-read. They are also read after every change made from Home Assistant. |
| Read battery BMS data | on | Turn off if your battery does not report it. |

To read everything immediately, for example from an automation, call
`luxpower_local.refresh`.

A poll that fails keeps the last readings; entities only go unavailable after
three failures in a row. Lifetime counters never go backwards: the inverter
occasionally reports a bogus low value, which would otherwise count as a meter
reset in the energy dashboard.

## Moving from lxp-bridge

Ticking **Use lxp-bridge entity IDs** gives the readings and settings the IDs
lxp-bridge's MQTT entities had (`sensor.lxp_<datalog>_pv_generation_all_time`
and so on), so their history and the energy dashboard carry on. For that the
old IDs must be free:

1. Stop lxp-bridge and any automation that publishes to `lxp/cmd/...`.
2. Clear lxp-bridge's retained discovery messages, or MQTT recreates the
   entities on restart:
   `mosquitto_pub -h <broker> -t 'homeassistant/<component>/lxp_<datalog>/<name>/config' -r -n`
   for each one (`mosquitto_sub -t 'homeassistant/+/lxp_<datalog>/+/config' -v`
   lists them).
3. Delete the old `lxp_<datalog>_*` entities under Settings → Entities.
4. Add this integration with the option ticked. Setup refuses if any of the
   old IDs are still taken.

The time slots become `time` entities, so the old `text` timeslot entities have
no counterpart.

## Credits

The dongle protocol and register map come from
[lxp-bridge](https://github.com/celsworth/lxp-bridge) by Chris Elsworth (MIT).
