"""
Kamstrup UtiliDriver - Single-shot Register Order Reader

- Creates ONE UtiliDriver order via POST.
- Never retries the POST automatically.
- Polls the returned status URL using GET only.
- Fetches completed results using GET only.
- Saves the raw XML result.
"""

import argparse
import sys
import time
from pathlib import Path
import xml.etree.ElementTree as ET

import requests


BASE_URL = "http://197.189.218.35/utilidriver/api"
ORDERS_URL = f"{BASE_URL}/orders/"
METER_PREFIX = "4B414D000000"

LOCK_DIR = Path(".utilidriver_locks")
LOCK_DIR.mkdir(exist_ok=True)


REGISTERS = [
    ("1.1.21.7.0.255", "Active power P14 - L1"),
    ("1.1.22.7.0.255", "Active power P23 - L1"),
    ("1.1.31.7.0.255", "Current L1"),
    ("1.1.32.7.0.255", "Voltage L1"),
    ("1.1.33.7.0.255", "Power factor L1"),
    ("1.1.41.7.0.255", "Active power P14 - L2"),
    ("1.1.42.7.0.255", "Active power P23 - L2"),
    ("1.1.51.7.0.255", "Current L2"),
    ("1.1.52.7.0.255", "Voltage L2"),
    ("1.1.53.7.0.255", "Power factor L2"),
    ("1.1.61.7.0.255", "Active power P14 - L3"),
    ("1.1.62.7.0.255", "Active power P23 - L3"),
    ("1.1.71.7.0.255", "Current L3"),
    ("1.1.72.7.0.255", "Voltage L3"),
    ("1.1.73.7.0.255", "Power factor L3"),
    ("1.1.1.7.0.255", "Active Power P14 Total"),
    ("1.1.2.7.0.255", "Active Power P23 Total"),
    ("1.1.1.8.0.255", "Import kWh / A14"),
    ("1.1.2.8.0.255", "Export kWh / A23"),
    ("1.1.13.7.0.255", "Power factor total"),
    ("1.1.14.7.0.255", "Frequency"),
]


def decimal_to_hex_8(meter_dec: str) -> str:
    meter_dec = meter_dec.strip()
    if not (len(meter_dec) == 8 and meter_dec.isdigit()):
        raise ValueError("Meter number must be exactly 8 decimal digits.")
    return format(int(meter_dec), "08X")


def meter_ref_from_decimal(meter_dec: str):
    meter_hex = decimal_to_hex_8(meter_dec)
    meter_id = f"{METER_PREFIX}{meter_hex}"
    meter_ref = f"{BASE_URL}/meters/{meter_id}/"
    return meter_id, meter_ref


def build_xml_body(meter_ref: str) -> str:
    register_xml = "\n".join(
        f"""    <RegisterCommand action="read">
      <Register id="{obis}" />
    </RegisterCommand>"""
        for obis, _name in REGISTERS
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Order priority="High">
  <Subjects>
    <Meters>
      <Meter ref="{meter_ref}" />
    </Meters>
  </Subjects>
  <Commands>
{register_xml}
  </Commands>
</Order>"""


def lock_file_for_meter(meter_dec: str) -> Path:
    return LOCK_DIR / f"order_post_{meter_dec}.lock"


def create_lock_or_stop(meter_dec: str) -> Path:
    lock_file = lock_file_for_meter(meter_dec)
    if lock_file.exists():
        raise RuntimeError(
            f"Safety lock exists: {lock_file}\n"
            "The script will NOT post again. Delete this lock only after confirming it is safe."
        )

    lock_file.write_text(
        f"POST attempted for meter {meter_dec} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )
    return lock_file


def send_order_once(xml_body: str, timeout: int = 15) -> str:
    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
    }

    print("Posting order ONCE to UtiliDriver...")

    try:
        response = requests.post(
            ORDERS_URL,
            data=xml_body.encode("utf-8"),
            headers=headers,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("POST timed out. Do NOT retry automatically.") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"POST failed. Do NOT retry automatically. {exc}") from exc

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"POST returned HTTP {response.status_code}. Do NOT retry automatically.\n"
            f"Response:\n{response.text}"
        )

    order_url = response.headers.get("Location")
    if not order_url:
        raise RuntimeError(
            "POST succeeded but no Location header was returned. "
            "Do NOT post again until this is checked manually."
        )

    print(f"Order created: {order_url}")
    return order_url


def poll_status(status_url: str, poll_interval: float = 2.0, timeout: float = 120.0) -> bool:
    end_time = time.time() + timeout

    print(f"Polling status with GET only: {status_url}")

    while time.time() < end_time:
        try:
            response = requests.get(status_url, timeout=10)
            response.raise_for_status()
            root = ET.fromstring(response.text.strip())

            waiting_elem = root.find("WaitingCommandCount")
            if waiting_elem is None or waiting_elem.text is None:
                print("WaitingCommandCount not found yet.")
            else:
                waiting_count = int(waiting_elem.text.strip())
                print(f"WaitingCommandCount: {waiting_count}")
                if waiting_count == 0:
                    return True

        except Exception as exc:
            print(f"Status GET failed, will continue polling: {exc}")

        time.sleep(poll_interval)

    return False


def fetch_completed_results(completed_url: str) -> str:
    print(f"Fetching completed results with GET: {completed_url}")
    response = requests.get(completed_url, timeout=20)
    response.raise_for_status()
    return response.text


def parse_register_results(xml_text: str):
    obis_to_name = dict(REGISTERS)
    root = ET.fromstring(xml_text)
    rows = []

    for reg in root.findall(".//Register"):
        reg_id = (reg.get("id") or "").strip()
        if not reg_id:
            continue

        unit = (reg.findtext("Unit") or "").strip()
        scale = (reg.findtext("Scale") or "").strip()
        value = (reg.findtext("Value") or "").strip()
        name = obis_to_name.get(reg_id, "")

        rows.append((reg_id, name, unit, scale, value))

    rows.sort(key=lambda r: r[0])
    return rows


def print_table(rows) -> None:
    if not rows:
        print("No register results found.")
        return

    headers = ("Register ID", "Description", "Unit", "Scale", "Value")
    all_rows = [headers] + rows
    widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]

    def fmt(row):
        return " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))

    print()
    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


def save_results(meter_dec: str, xml_text: str) -> Path:
    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"utilidriver_{meter_dec}_{timestamp}.xml"
    output_file.write_text(xml_text, encoding="utf-8")
    return output_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Kamstrup UtiliDriver register values safely.")
    parser.add_argument("meter", help="8-digit decimal meter number, e.g. 36793123")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--print-xml", action="store_true")
    args = parser.parse_args()

    meter_dec = args.meter.strip()

    try:
        meter_id, meter_ref = meter_ref_from_decimal(meter_dec)
        lock_file = create_lock_or_stop(meter_dec)

        print(f"Meter decimal : {meter_dec}")
        print(f"Meter ID      : {meter_id}")
        print(f"Meter ref     : {meter_ref}")
        print(f"Lock file     : {lock_file}")

        xml_body = build_xml_body(meter_ref)

        order_url = send_order_once(xml_body)
        status_url = f"{order_url}status/"
        completed_url = f"{order_url}completed/"

        order_done = poll_status(
            status_url,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )

        if not order_done:
            print("Order did not complete before timeout.")
            print("Do NOT post again automatically. Check UtiliDriver manually.")
            return 2

        completed_xml = fetch_completed_results(completed_url)
        output_file = save_results(meter_dec, completed_xml)

        rows = parse_register_results(completed_xml)
        print_table(rows)

        print(f"\nRaw XML saved to: {output_file}")

        if args.print_xml:
            print("\nRaw XML:")
            print(completed_xml)

        print("\nDone. The POST was performed once only.")
        return 0

    except Exception as exc:
        print(f"\nERROR: {exc}")
        print("Safety rule: do NOT run again until you confirm whether an order was created.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
