
# Kamstrup UtiliDriver - Safe Order Reader
#
# Flow:
# 1. POST one XML order to /utilidriver/api/orders/
# 2. Read the returned Location header
# 3. GET Location/status/
# 4. GET Location/completed/
# 5. Print voltages, currents, power factor, power and energy values
#
# IMPORTANT:
# - The POST is attempted ONCE only.
# - If the POST fails or times out, the script stops.
# - It does not retry the POST.
# - A local lock file is created before the POST attempt.

import argparse
import sys
import time
from pathlib import Path
import xml.etree.ElementTree as ET

import requests


API_BASE = "http://197.189.218.35/utilidriver/api"
ORDERS_URL = API_BASE + "/orders/"
METER_PREFIX = "4B414D000000"

LOCK_DIR = Path(".utilidriver_locks")
LOG_DIR = Path("utilidriver_logs")
RESULTS_DIR = Path("utilidriver_results")

LOCK_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


REGISTERS = [
    ("1.1.21.7.0.255", "Active Power P14 L1"),
    ("1.1.22.7.0.255", "Active Power P23 L1"),
    ("1.1.31.7.0.255", "Current L1"),
    ("1.1.32.7.0.255", "Voltage L1"),
    ("1.1.33.7.0.255", "Power Factor L1"),

    ("1.1.41.7.0.255", "Active Power P14 L2"),
    ("1.1.42.7.0.255", "Active Power P23 L2"),
    ("1.1.51.7.0.255", "Current L2"),
    ("1.1.52.7.0.255", "Voltage L2"),
    ("1.1.53.7.0.255", "Power Factor L2"),

    ("1.1.61.7.0.255", "Active Power P14 L3"),
    ("1.1.62.7.0.255", "Active Power P23 L3"),
    ("1.1.71.7.0.255", "Current L3"),
    ("1.1.72.7.0.255", "Voltage L3"),
    ("1.1.73.7.0.255", "Power Factor L3"),

    ("1.1.1.7.0.255", "Active Power P14 Total"),
    ("1.1.2.7.0.255", "Active Power P23 Total"),
    ("1.1.1.8.0.255", "Active Energy A14 / Import kWh"),
    ("1.1.2.8.0.255", "Active Energy A23 / Export kWh"),
    ("1.1.13.7.0.255", "Power Factor Total"),
    ("1.1.14.7.0.255", "Frequency"),
]


def make_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def decimal_to_hex_8(meter_dec):
    meter_dec = meter_dec.strip()
    if not meter_dec.isdigit() or len(meter_dec) != 8:
        raise ValueError("Meter number must be exactly 8 digits, for example 36793123.")
    return format(int(meter_dec), "08X")


def get_meter_id_and_ref(meter_dec):
    meter_hex = decimal_to_hex_8(meter_dec)
    meter_id = METER_PREFIX + meter_hex
    meter_ref = API_BASE + "/meters/" + meter_id + "/"
    return meter_hex, meter_id, meter_ref


def build_order_xml(meter_ref):
    commands = []
    for register_id, description in REGISTERS:
        commands.append(
            "    <RegisterCommand action='read'>\n"
            "      <Register id='" + register_id + "' />\n"
            "    </RegisterCommand>"
        )

    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<Order priority='High'>\n"
        "  <Subjects>\n"
        "    <Meters>\n"
        "      <Meter ref=\"" + meter_ref + "\" />\n"
        "    </Meters>\n"
        "  </Subjects>\n"
        "  <Commands>\n"
        + "\n".join(commands) + "\n"
        "  </Commands>\n"
        "</Order>"
    )


def build_status_url(order_url):
    return order_url.rstrip("/") + "/status/"


def build_completed_url(order_url):
    return order_url.rstrip("/") + "/completed/"


def lock_file_for_meter(meter_dec):
    return LOCK_DIR / (meter_dec + ".post.lock")


def create_post_lock(meter_dec, meter_ref):
    lock_file = lock_file_for_meter(meter_dec)

    if lock_file.exists():
        raise RuntimeError(
            "Safety lock already exists: " + str(lock_file) + "\n"
            "This means a POST was already attempted for this meter.\n"
            "Do NOT run again until the UtiliDriver server/orders were checked.\n"
            "Only delete this lock manually if it is safe to create a new order."
        )

    lock_file.write_text(
        "Meter: " + meter_dec + "\n"
        "MeterRef: " + meter_ref + "\n"
        "POST attempted at: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n",
        encoding="utf-8",
    )
    return lock_file


def post_order_once(session, xml_body, timeout):
    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
    }

    response = session.post(
        ORDERS_URL,
        data=xml_body.encode("utf-8"),
        headers=headers,
        timeout=timeout,
    )

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_text = (
        "URL: " + ORDERS_URL + "\n"
        "Status: " + str(response.status_code) + "\n"
        "Headers:\n" + str(dict(response.headers)) + "\n\n"
        "Body:\n" + response.text + "\n"
    )
    (LOG_DIR / ("post_response_" + timestamp + ".txt")).write_text(log_text, encoding="utf-8")

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            "POST failed with HTTP " + str(response.status_code) + ".\n"
            "Response body:\n" + response.text
        )

    location = response.headers.get("Location")
    if not location:
        raise RuntimeError(
            "POST succeeded but no Location header was returned. Cannot continue safely."
        )

    return location


def poll_order_status(session, status_url, poll_interval, timeout):
    end_time = time.time() + timeout

    while time.time() < end_time:
        response = session.get(status_url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.text.strip())

        waiting_text = root.findtext("WaitingCommandCount")
        failed_text = root.findtext("FailedCommandCount")
        completed_text = root.findtext("CompletedCommandCount")

        waiting_count = int(waiting_text) if waiting_text and waiting_text.strip().isdigit() else None
        failed_count = int(failed_text) if failed_text and failed_text.strip().isdigit() else 0
        completed_count = int(completed_text) if completed_text and completed_text.strip().isdigit() else 0

        print("Status: waiting=" + str(waiting_count) + ", completed=" + str(completed_count) + ", failed=" + str(failed_count))

        if waiting_count == 0:
            return True

        time.sleep(poll_interval)

    return False


def fetch_completed_xml(session, completed_url):
    response = session.get(completed_url, timeout=20)
    response.raise_for_status()
    return response.text


def parse_results(xml_text):
    root = ET.fromstring(xml_text)
    names = dict(REGISTERS)
    rows = []

    for register in root.findall(".//Register"):
        register_id = (register.get("id") or "").strip()
        if not register_id:
            continue

        unit = (register.findtext("Unit") or "").strip()
        scale = (register.findtext("Scale") or "").strip()
        value = (register.findtext("Value") or "").strip()
        description = names.get(register_id, "")

        rows.append((register_id, description, unit, scale, value))

    rows.sort(key=lambda row: row[0])
    return rows


def print_results_table(rows):
    if not rows:
        print("No register rows found in completed XML.")
        return

    headers = ("Register ID", "Description", "Unit", "Scale", "Value")
    table = [headers] + rows
    widths = [max(len(str(row[i])) for row in table) for i in range(len(headers))]

    def fmt(row):
        return " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))

    print()
    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(fmt(row))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("meter", help="8-digit decimal meter number, e.g. 36793123")
    parser.add_argument("--post-timeout", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--show-xml", action="store_true")
    args = parser.parse_args()

    meter_dec = args.meter.strip()
    session = make_session()

    try:
        meter_hex, meter_id, meter_ref = get_meter_id_and_ref(meter_dec)
        xml_body = build_order_xml(meter_ref)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        xml_order_file = LOG_DIR / ("order_xml_" + meter_dec + "_" + timestamp + ".xml")
        xml_order_file.write_text(xml_body, encoding="utf-8")

        print("Meter decimal : " + meter_dec)
        print("Meter hex     : " + meter_hex)
        print("Meter ID      : " + meter_id)
        print("Meter ref     : " + meter_ref)
        print("Order XML log : " + str(xml_order_file))

        lock_file = create_post_lock(meter_dec, meter_ref)
        print("Safety lock   : " + str(lock_file))

        print("\nPOSTING ORDER ONCE ONLY...")
        order_url = post_order_once(session, xml_body, timeout=args.post_timeout)

        status_url = build_status_url(order_url)
        completed_url = build_completed_url(order_url)

        print("Order URL     : " + order_url)
        print("Status URL    : " + status_url)
        print("Completed URL : " + completed_url)

        print("\nPolling order status with GET only...")
        completed = poll_order_status(
            session=session,
            status_url=status_url,
            poll_interval=args.poll_interval,
            timeout=args.poll_timeout,
        )

        if not completed:
            print("\nOrder did not complete within the polling timeout.")
            print("Do NOT post again automatically. Check the order manually.")
            return 2

        print("\nFetching completed result...")
        completed_xml = fetch_completed_xml(session, completed_url)

        result_file = RESULTS_DIR / ("completed_" + meter_dec + "_" + timestamp + ".xml")
        result_file.write_text(completed_xml, encoding="utf-8")

        rows = parse_results(completed_xml)
        print_results_table(rows)

        print("\nCompleted XML saved to: " + str(result_file))

        if args.show_xml:
            print("\nCompleted XML:")
            print(completed_xml)

        print("\nDone. POST was executed once only.")
        return 0

    except requests.exceptions.Timeout:
        print("\nERROR: Request timed out.")
        print("If this happened during POST, do NOT run again until checked manually.")
        return 1

    except requests.exceptions.RequestException as exc:
        print("\nERROR: Network/API error: " + str(exc))
        print("Do NOT run again until checked manually if POST may have been sent.")
        return 1

    except Exception as exc:
        print("\nERROR: " + str(exc))
        print("Do NOT run again until checked manually if POST may have been sent.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
