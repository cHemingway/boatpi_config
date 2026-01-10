#!/usr/bin/env python3
"""
Poll Wi-Fi and LTE signal strength and publish them as MAVLink NamedValueFloat messages
on a MAVLink UDP endpoint.

Requires:
- NetworkManager (nmcli)
- ModemManager (mmcli)
- pymavlink

Configuration is provided via command line arguments (see --help).
Intended to be run as a systemd service on Debian/Raspberry Pi OS.
"""

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from pymavlink import mavutil

@dataclass
class WifiSignal:
    ssid: str
    strength: float


class MavlinkSender:
    def __init__(self, endpoint: str, sys_id: int, comp_id: int):
        self.endpoint = endpoint
        self.sys_id = sys_id
        self.comp_id = comp_id
        self.conn: Optional[mavutil.mavudp] = None

    def _connect(self) -> None:
        logging.info(
            "Connecting to MAVLink endpoint %s (sys=%s, comp=%s)",
            self.endpoint,
            self.sys_id,
            self.comp_id,
        )
        self.conn = mavutil.mavlink_connection(
            self.endpoint,
            autoreconnect=True,
            source_system=self.sys_id,
            source_component=self.comp_id,
        )

    def ensure_connection(self) -> None:
        if self.conn is None:
            self._connect()

    def send_named_value(self, name: str, value: float, time_boot_ms: int) -> None:
        # NamedValueFloat name is limited to 10 chars in MAVLink
        safe_name = str(name)[:10]
        safe_bytes = safe_name.encode("ascii", errors="replace")
        try:
            self.ensure_connection()
            assert self.conn is not None
            self.conn.mav.named_value_float_send(time_boot_ms, safe_bytes, float(value))
        except Exception:
            logging.exception("Failed sending MAVLink value %s", name)
            # Force reconnect next loop
            self.conn = None


def run_command(cmd: list[str], timeout: float = 5.0) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        raise RuntimeError(f"Command {' '.join(cmd)} failed: {stderr or stdout}")
    return proc.stdout


def get_boot_ms() -> int:
    """Return milliseconds since system boot using /proc/uptime."""
    try:
        with open("/proc/uptime", "r", encoding="ascii") as f:
            first = f.read().split()[0]
            return int(float(first) * 1000)
    except Exception:
        # Fallback to monotonic if /proc/uptime is unavailable
        return int(time.monotonic() * 1000)


def parse_kv(lines: Iterable[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
        elif ":" in line:
            key, val = line.split(":", 1)
        else:
            continue
        data[key.strip()] = val.strip()
    return data

def get_wifi_signal() -> Optional[WifiSignal]:
    """Return the active Wi-Fi SSID and signal percentage (0-100)."""
    try:
        # Use terse output for easier parsing: IN-USE[*]:SSID:SIGNAL
        output = run_command(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi"], timeout=4)
    except Exception as exc:
        logging.warning("Failed to read Wi-Fi signal: %s", exc)
        return None

    for line in output.splitlines():
        # Format: "*:SSID:SIGNAL" (in-use marked by "*")
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        in_use, ssid, signal = parts
        if not in_use.startswith("*"):
            continue
        if not signal:
            continue
        try:
            return WifiSignal(ssid=ssid or "wifi", strength=float(signal))
        except ValueError:
            logging.debug("Could not parse Wi-Fi signal from line: %s", line)
            continue
    return None


def enable_modem_signal_monitoring(modem_selector: str) -> None:
    try:
        run_command(["mmcli", "-m", modem_selector, "--signal-setup=1", "--timeout", "10", "-K"], timeout=12)
    except Exception as exc:
        # Often harmless if already enabled or modem absent
        logging.info("mmcli signal setup skipped: %s", exc)


LTE_KEYS = {
    "modem.signal.lte.rssi": "rssi",
}


def get_lte_signals(modem_selector: str) -> Dict[str, float]:
    """Return LTE metrics from mmcli (rssi/rsrp/rsrq/snr)."""
    metrics: Dict[str, float] = {}
    try:
        output = run_command(["mmcli", "-m", modem_selector, "--signal-get", "--timeout", "6", "-K"], timeout=8)
    except Exception as exc:
        logging.warning("Failed to read LTE signal: %s", exc)
        return metrics

    kv = parse_kv(output.splitlines())
    for key, val in kv.items():
        if key in LTE_KEYS:
            if val == "--" or val == "":
                continue
            try:
                metrics[LTE_KEYS[key]] = float(val)
            except ValueError:
                continue
    return metrics


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish Wi-Fi/LTE signal metrics to MAVLink")
    parser.add_argument("--endpoint", default="udpout:127.0.0.1:14560", help="MAVLink endpoint (e.g. udpout:127.0.0.1:14560)")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between polls")
    parser.add_argument("--modem-id", default="any", help="ModemManager modem selector (e.g. 0 or path)")
    parser.add_argument("--mav-sys-id", type=int, default=1, help="MAVLink system id")
    parser.add_argument("--mav-comp-id", type=int, default=191, help="MAVLink component id")
    parser.add_argument(
        "--mav-comp-id-lte",
        type=int,
        default=192,
        help="MAVLink component id for LTE metrics",
    )
    parser.add_argument("--wifi-metric-name", default="wifi_sig", help="Metric name for Wi-Fi signal")
    parser.add_argument("--lte-prefix", default="lte_", help="Prefix for LTE metric names")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING...)")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    enable_modem_signal_monitoring(args.modem_id)
    sender_wifi = MavlinkSender(args.endpoint, args.mav_sys_id, args.mav_comp_id)
    sender_lte = MavlinkSender(args.endpoint, args.mav_sys_id, args.mav_comp_id_lte)

    logging.info("Starting signal monitor loop (interval=%.1fs)", args.poll_interval)
    try:
        while True:
            loop_start = time.monotonic()
            time_boot_ms = get_boot_ms()

            wifi = get_wifi_signal()
            if wifi:
                sender_wifi.send_named_value(args.wifi_metric_name, wifi.strength, time_boot_ms)
                logging.info("Wi-Fi '%s' signal=%.1f%%", wifi.ssid, wifi.strength)

            lte_metrics = get_lte_signals(args.modem_id)
            rssi = lte_metrics.get("rssi")
            if rssi is not None:
                sender_lte.send_named_value(f"{args.lte_prefix}rssi", rssi, time_boot_ms)
                logging.info("LTE metrics: rssi=%.2f dB", rssi)

            if not wifi and rssi is None:
                logging.info("No Wi-Fi or LTE metrics this cycle")

            elapsed = time.monotonic() - loop_start
            sleep_for = max(0.0, args.poll_interval - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        logging.info("Signal monitor interrupted, exiting")
        return 0
    except Exception:
        logging.exception("Fatal error in signal monitor")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
