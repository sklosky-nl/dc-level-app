#!/usr/bin/env python3
"""
DC Level Poller - reads the dust collector level gauge over Modbus/TCP and
writes frontend/data/level.json for the display. Run once a minute from cron.

Gauge settings (from Gillian's FUXA config):
  Modbus/TCP 192.168.1.181:502, device 1, address 300101, Int16,
  4.00 mA = empty bag, 20.00 mA = full bag

Each result is also POSTed to Watto when WATTO_TOKEN is set. WATTO_URL
overrides the default endpoint.
"""

import json
import os
import socket
import struct
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

GAUGE_HOST = "192.168.1.181"
GAUGE_PORT = 502
UNIT_ID = 1
INPUT_REGISTER = 100    # 300101 in Modicon numbering = input register offset 100
RAW_PER_MA = 1000.0     # register reports microamps (12716 -> 12.716 mA)
EMPTY_MA = 4.0
FULL_MA = 20.0
TIMEOUT_S = 5

WATTO_URL = os.environ.get("WATTO_URL", "https://wautils.nova-labs.org/api/dust_collector")
WATTO_TOKEN = os.environ.get("WATTO_TOKEN")

OUTPUT_FILE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "data", "level.json"))


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("gauge closed the connection")
        data += chunk
    return data


def read_input_register(host, port, unit, address):
    """Read one signed 16-bit input register (Modbus function 0x04)."""
    request = struct.pack(">HHHBBHH", 1, 0, 6, unit, 0x04, address, 1)
    with socket.create_connection((host, port), timeout=TIMEOUT_S) as sock:
        sock.sendall(request)
        _, _, length, _ = struct.unpack(">HHHB", recv_exact(sock, 7))
        pdu = recv_exact(sock, length - 1)
    if pdu[0] & 0x80:
        raise ValueError(f"Modbus exception code {pdu[1]}")
    if pdu[0] != 0x04 or pdu[1] != 2:
        raise ValueError(f"unexpected Modbus response {pdu.hex()}")
    return struct.unpack(">h", pdu[2:4])[0]


def to_reading(raw, read_at):
    current_ma = raw / RAW_PER_MA
    fill = (current_ma - EMPTY_MA) / (FULL_MA - EMPTY_MA) * 100
    return {
        "read_at": read_at,
        "raw": raw,
        "current_ma": round(current_ma, 3),
        "fill_percent": round(min(max(fill, 0.0), 100.0), 1),
    }


def load_previous_reading():
    try:
        with open(OUTPUT_FILE) as f:
            return json.load(f).get("reading")
    except (OSError, ValueError):
        return None


def write_atomically(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
    os.chmod(tmp_path, 0o644)  # mkstemp creates 0600; Apache needs to read it
    os.replace(tmp_path, path)


def post_to_watto(payload):
    if not WATTO_TOKEN:
        print("Watto post skipped: WATTO_TOKEN is not set", file=sys.stderr)
        return
    request = urllib.request.Request(
        WATTO_URL, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {WATTO_TOKEN}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S):
            pass
    except OSError as e:  # URLError and HTTPError are OSErrors
        print(f"Watto post failed: {e}", file=sys.stderr)


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {"ok": True, "checked_at": now, "error": None, "reading": None}

    try:
        raw = read_input_register(GAUGE_HOST, GAUGE_PORT, UNIT_ID, INPUT_REGISTER)
        payload["reading"] = to_reading(raw, now)
    except (OSError, ValueError, struct.error) as e:
        # Keep the last good reading so the display can show it as stale
        payload.update(ok=False, error=str(e), reading=load_previous_reading())
        print(f"Gauge read failed: {e}", file=sys.stderr)

    write_atomically(OUTPUT_FILE, payload)
    post_to_watto(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
