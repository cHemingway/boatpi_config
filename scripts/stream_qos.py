#!/usr/bin/env python3
"""
Adaptive bitrate controller for MediaMTX on Raspberry Pi.
- Finds the active reader IP via the MediaMTX Control API
- Pings the reader every second and keeps a 5-second rolling RTT average
- Lowers bitrate toward a minimum when latency is high; raises toward default when healthy
- Restores the default bitrate when no reader is connected
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Deque, Optional

DEFAULT_TIMEOUT = 3.0


def parse_remote_ip(remote: Optional[str]) -> Optional[str]:
    if not remote:
        return None
    remote = remote.strip()
    if remote.startswith("[") and "]" in remote:
        # Format: [ipv6]:port
        return remote.split("]", 1)[0].lstrip("[")
    if remote.count(":") >= 2:
        # IPv6 without brackets, return raw
        return remote
    if ":" in remote:
        return remote.rsplit(":", 1)[0]
    return remote


def http_json(base_url: str, path: str, method: str = "GET", payload: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    url = f"{base_url.rstrip('/')}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            content = resp.read()
            if not content:
                return {}
            return json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logging.warning("HTTP %s %s failed: %s", method, path, exc)
    except urllib.error.URLError as exc:
        logging.warning("HTTP %s %s unreachable: %s", method, path, exc)
    except Exception:
        logging.exception("Unexpected error during HTTP %s %s", method, path)
    return None


def ping_once(host: str, timeout: float) -> Optional[float]:
    cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
    except Exception as exc:
        logging.warning("Ping failed for %s: %s", host, exc)
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"time=([0-9]+\.?[0-9]*)\s*ms", proc.stdout)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


class BitrateController:
    def __init__(self, base_url: str, path: str, target_ms: float, window: int, min_bitrate: int, max_bitrate: int, step_down: int, step_up: int, ping_timeout: float, loss_penalty_ms: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.path = path
        self.target_ms = target_ms
        self.window = window
        self.min_bitrate = min_bitrate
        self.max_bitrate = max_bitrate
        self.step_down = step_down
        self.step_up = step_up
        self.ping_timeout = ping_timeout
        self.loss_penalty_ms = loss_penalty_ms
        self.rtts: Deque[float] = deque(maxlen=window)
        self.default_bitrate = self._fetch_default_bitrate()
        self.current_bitrate = self._fetch_current_bitrate(self.default_bitrate)
        self.last_applied = self.current_bitrate
        logging.info(
            "Initial bitrate setpoint: default=%s current=%s max=%s",
            self.default_bitrate,
            self.current_bitrate,
            self.max_bitrate,
        )

    def _fetch_default_bitrate(self) -> int:
        data = http_json(self.base_url, "/v3/config/pathdefaults/get") or {}
        return int(data.get("rpiCameraBitrate", self.min_bitrate))

    def _fetch_current_bitrate(self, fallback: int) -> int:
        data = http_json(self.base_url, f"/v3/config/paths/get/{self.path}") or {}
        return int(data.get("rpiCameraBitrate", fallback))

    def _set_bitrate(self, bitrate: int) -> None:
        bitrate = max(self.min_bitrate, min(bitrate, self.max_bitrate))
        if bitrate == self.last_applied:
            return
        payload = {"rpiCameraBitrate": bitrate}
        if http_json(self.base_url, f"/v3/config/paths/patch/{self.path}", method="PATCH", payload=payload) is not None:
            self.last_applied = bitrate
            logging.info("Applied bitrate=%s", bitrate)

    def _fraction_of_max(self, bitrate: int) -> float:
        if self.max_bitrate <= 0:
            return 0.0
        return round(bitrate / self.max_bitrate, 3)

    def _reader_ip(self) -> Optional[str]:
        # Ordered by likely use: RTSP/RTSPS, RTMP, SRT, WebRTC, HLS
        endpoints = [
            "/v3/rtspsessions/list",
            "/v3/rtmpconns/list",
            "/v3/srtconns/list",
            "/v3/webrtcsessions/list",
            "/v3/hlssessions/list",
        ]
        for ep in endpoints:
            data = http_json(self.base_url, ep)
            if not data:
                continue
            for item in data.get("items", []):
                if item.get("path") != self.path:
                    continue
                if "state" in item and item.get("state") != "read":
                    continue
                ip = parse_remote_ip(item.get("remoteAddr"))
                if ip:
                    return ip

        return None

    def _avg_rtt(self) -> Optional[float]:
        if not self.rtts:
            return None
        return sum(self.rtts) / len(self.rtts)

    def _record_rtt(self, rtt: Optional[float]) -> None:
        if rtt is None:
            self.rtts.append(self.loss_penalty_ms)
        else:
            self.rtts.append(rtt)

    def tick(self) -> None:
        reader_ip = self._reader_ip()
        if not reader_ip:
            if self.last_applied != self.default_bitrate:
                self._set_bitrate(self.default_bitrate)
            self.rtts.clear()
            logging.info(
                "No reader connected; bitrate=%s (%.3f of max)",
                self.last_applied,
                self._fraction_of_max(self.last_applied),
            )
            return

        rtt = ping_once(reader_ip, self.ping_timeout)
        self._record_rtt(rtt)
        avg = self._avg_rtt()
        logging.info(
            "Reader %s rtt=%s avg=%.1fms bitrate=%s (%.3f of max)",
            reader_ip,
            f"{rtt:.1f}ms" if rtt else "timeout",
            avg or 0.0,
            self.last_applied,
            self._fraction_of_max(self.last_applied),
        )

        if avg is None:
            return

        new_bitrate = self.last_applied
        if avg > self.target_ms:
            new_bitrate = max(self.min_bitrate, self.last_applied - self.step_down)
        elif avg < max(50.0, self.target_ms * 0.6) and self.last_applied < self.max_bitrate:
            new_bitrate = min(self.max_bitrate, self.last_applied + self.step_up)

        self._set_bitrate(new_bitrate)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive bitrate controller for MediaMTX")
    parser.add_argument("--base-url", default="http://127.0.0.1:9997", help="MediaMTX Control API base URL")
    parser.add_argument("--path", default="cam", help="MediaMTX path to manage")
    parser.add_argument("--target-avg-ms", type=float, default=150.0, help="Target average RTT over window")
    parser.add_argument("--window", type=int, default=5, help="Number of seconds to average")
    parser.add_argument("--min-bitrate", type=int, default=500_000, help="Minimum bitrate (bps)")
    parser.add_argument("--max-bitrate", type=int, default=2_500_000, help="Maximum bitrate (bps)")
    parser.add_argument("--step-down", type=int, default=500_000, help="Bitrate decrement when above target (bps)")
    parser.add_argument("--step-up", type=int, default=250_000, help="Bitrate increment when below target (bps)")
    parser.add_argument("--ping-timeout", type=float, default=1.0, help="Ping timeout (seconds)")
    parser.add_argument("--loss-penalty-ms", type=float, default=1000.0, help="RTT value to record on packet loss")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    controller = BitrateController(
        base_url=args.base_url,
        path=args.path,
        target_ms=args.target_avg_ms,
        window=args.window,
        min_bitrate=args.min_bitrate,
        max_bitrate=args.max_bitrate,
        step_down=args.step_down,
        step_up=args.step_up,
        ping_timeout=args.ping_timeout,
        loss_penalty_ms=args.loss_penalty_ms,
    )

    logging.info(
        "Starting adaptive bitrate loop (target=%.0fms window=%ds min=%d max=%d)",
        args.target_avg_ms,
        args.window,
        args.min_bitrate,
        args.max_bitrate,
    )

    try:
        while True:
            loop_start = time.monotonic()
            controller.tick()
            elapsed = time.monotonic() - loop_start
            sleep_for = max(0.0, 1.0 - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        logging.info("Bitrate controller interrupted, exiting")
        return 0
    except Exception:
        logging.exception("Fatal error in bitrate controller")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
