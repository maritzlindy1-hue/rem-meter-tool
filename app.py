import streamlit as st
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import BytesIO

BASE_URL = "http://197.189.218.35/utilidriver"
METER_PREFIX = "4B414D00000000"

OBIS_CODES = {
    "1.1.21.7.0.255": "L1 kW Import",
    "1.1.22.7.0.255": "L1 kW Export",
    "1.1.31.7.0.255": "L1 Current",
    "1.1.32.7.0.255": "L1 Voltage",
    "1.1.33.7.0.255": "L1 PF",
    "1.1.41.7.0.255": "L2 kW Import",
    "1.1.42.7.0.255": "L2 kW Export",
    "1.1.51.7.0.255": "L2 Current",
    "1.1.52.7.0.255": "L2 Voltage",
    "1.1.53.7.0.255": "L2 PF",
    "1.1.61.7.0.255": "L3 kW Import",
    "1.1.62.7.0.255": "L3 kW Export",
    "1.1.71.7.0.255": "L3 Current",
    "1.1.72.7.0.255": "L3 Voltage",
    "1.1.73.7.0.255": "L3 PF",
}

st.set_page_config(page_title="REM Meter Tool", page_icon="⚡", layout="wide")
st.title("⚡ Republic Metering - Kamstrup OBIS Lookup")

def serial_to_meter_id(serial_number: str) -> str:
    """
    Converts normal decimal serial number to the UtiliDriver long meter reference.

    Example:
    Serial: 24165632
    Decimal to HEX: 170BD00
    Final: 4B414D00000000170BD00
    """
    serial_number = str(serial_number).strip()

    if not serial_number.isdigit():
        raise ValueError("Serial number must only contain numbers.")

    serial_hex = format(int(serial_number), "X").upper()

    return f"{METER_PREFIX}{serial_hex}"

def read_url(url):
    response = requests.get(url, timeout=60)
    return response

def xml_to_table(xml_text):
    root = ET.fromstring(xml_text)
    rows = []

    for elem in root.iter():
        row = {"tag": elem.tag}
        row.update(elem.attrib)
        text = (elem.text or "").strip()
        if text:
            row["text"] = text
        rows.append(row)

    return pd.DataFrame(rows)

def try_obis_endpoints(meter_id):
    """
    UtiliDriver installations differ, so this tests the common patterns.
    The page will show which endpoint works.
    """
    meter_url = f"{BASE_URL}/api/meters/{meter_id}/"

    endpoints = [
        meter_url,
        f"{meter_url}registers/",
        f"{meter_url}readings/",
        f"{meter_url}obis/",
        f"{meter_url}values/",
        f"{BASE_URL}/api/registers/{meter_id}/",
        f"{BASE_URL}/api/readings/{meter_id}/",
        f"{BASE_URL}/api/obis/{meter_id}/",
        f"{BASE_URL}/api/profiles/{meter_id}/",
    ]

    attempts = []

    for url in endpoints:
        try:
            r = read_url(url)
            attempts.append({
                "url": url,
                "status": r.status_code,
                "content_type": r.headers.get("Content-Type", ""),
                "preview": r.text[:250],
                "response": r
            })
        except Exception as e:
            attempts.append({
                "url": url,
                "status": "ERROR",
                "content_type": "",
                "preview": str(e),
                "response": None
            })

    return attempts

def extract_obis_rows_from_text(text):
    """
    Generic extractor. It looks for known OBIS codes in JSON/XML/text responses.
    Once we know the exact UtiliDriver response format, this can be made cleaner.
    """
    rows = []
    lower_text = text.lower()

    for obis, description in OBIS_CODES.items():
        if obis in text:
            rows.append({
                "Register ID": obis,
                "Description": description,
                "Found in response": "Yes",
                "Value": "",
                "Unit": "",
                "Scale": "",
            })

    return pd.DataFrame(rows)

serial_no = st.text_input("Enter normal meter serial number", value="24165632")

if serial_no:
    try:
        meter_id_preview = serial_to_meter_id(serial_no)
        meter_url_preview = f"{BASE_URL}/api/meters/{meter_id_preview}/"

        st.write("### Converted UtiliDriver Meter ID")
        st.code(meter_id_preview)

        st.write("### Meter API URL")
        st.code(meter_url_preview)

    except Exception as e:
        st.error(e)

if st.button("Get OBIS Readings"):
    try:
        meter_id = serial_to_meter_id(serial_no)
        meter_url = f"{BASE_URL}/api/meters/{meter_id}/"

        st.success("Serial converted successfully.")
        st.write("Meter ID:", meter_id)
        st.write("Meter URL:", meter_url)

        with st.spinner("Testing UtiliDriver endpoints..."):
            attempts = try_obis_endpoints(meter_id)

        attempts_table = pd.DataFrame([
            {
                "URL": a["url"],
                "Status": a["status"],
                "Content Type": a["content_type"],
                "Preview": a["preview"]
            }
            for a in attempts
        ])

        st.write("### Endpoint Test Results")
        st.dataframe(attempts_table, use_container_width=True)

        working = [a for a in attempts if a["status"] == 200 and a["response"] is not None]

        if not working:
            st.error("No endpoint returned status 200. The API path may need to be confirmed from UtiliDriver.")
        else:
            selected = working[0]
            response = selected["response"]

            st.write("### First Working Endpoint")
            st.code(selected["url"])

            st.write("### Raw Response Preview")
            st.text(response.text[:4000])

            # Try JSON
            try:
                data = response.json()
                df = pd.json_normalize(data)
                st.write("### Parsed JSON Table")
                st.dataframe(df, use_container_width=True)
            except Exception:
                # Try XML
                try:
                    df = xml_to_table(response.text)
                    st.write("### Parsed XML Table")
                    st.dataframe(df, use_container_width=True)
                except Exception:
                    df = extract_obis_rows_from_text(response.text)
                    st.write("### OBIS Codes Found")
                    st.dataframe(df, use_container_width=True)

            output = BytesIO()
            df.to_excel(output, index=False)
            output.seek(0)

            st.download_button(
                label="📥 Download Excel",
                data=output,
                file_name=f"Meter_{serial_no}_obis.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Error: {e}")
