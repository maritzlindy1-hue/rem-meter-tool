import streamlit as st
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import BytesIO

BASE_URL = "http://197.189.218.35/utilidriver"
METER_PREFIX = "4B414D00000000"

TARGET_OBIS = {
    "1.1.21.7.0.255": ("L1 Import Power", "watt", 3),
    "1.1.22.7.0.255": ("L1 Export Power", "watt", 3),
    "1.1.31.7.0.255": ("L1 Current", "ampere", 0),
    "1.1.32.7.0.255": ("L1 Voltage", "volt", 0),
    "1.1.33.7.0.255": ("L1 PF", "noUnit", 0),
    "1.1.41.7.0.255": ("L2 Import Power", "watt", 3),
    "1.1.42.7.0.255": ("L2 Export Power", "watt", 3),
    "1.1.51.7.0.255": ("L2 Current", "ampere", 0),
    "1.1.52.7.0.255": ("L2 Voltage", "volt", 0),
    "1.1.53.7.0.255": ("L2 PF", "noUnit", 0),
    "1.1.61.7.0.255": ("L3 Import Power", "watt", 3),
    "1.1.62.7.0.255": ("L3 Export Power", "watt", 3),
    "1.1.71.7.0.255": ("L3 Current", "ampere", 0),
    "1.1.72.7.0.255": ("L3 Voltage", "volt", 0),
    "1.1.73.7.0.255": ("L3 PF", "noUnit", 0),
    "1.1.0.4.2.255": ("Current Transformer Ratio", "ratio", 0),
}

st.set_page_config(page_title="REM Meter Tool", page_icon="⚡", layout="wide")
st.title("⚡ Republic Metering - Kamstrup Meter/Profile/OBIS Tool")

def serial_to_meter_id(serial_number: str) -> str:
    serial_number = str(serial_number).strip()
    if not serial_number.isdigit():
        raise ValueError("Serial number must only contain numbers.")
    serial_hex = format(int(serial_number), "X").upper()
    return f"{METER_PREFIX}{serial_hex}"

def get_meter_xml(meter_id: str):
    meter_url = f"{BASE_URL}/api/meters/{meter_id}/"
    r = requests.get(meter_url, timeout=60)
    r.raise_for_status()
    return meter_url, r.text

def parse_meter_details(meter_xml: str):
    root = ET.fromstring(meter_xml)

    details = {
        "Meter API Ref": root.attrib.get("ref", ""),
        "Profile Ref": "",
        "Routes Ref": "",
        "Meter Number": "",
        "Serial Number": "",
        "State": "",
        "Type Description": "",
        "Firmware": "",
        "Location ID": "",
    }

    profile = root.find(".//Profile")
    if profile is not None:
        details["Profile Ref"] = profile.attrib.get("ref", "")

    routes = root.find(".//Routes")
    if routes is not None:
        details["Routes Ref"] = routes.attrib.get("ref", "")

    fields = {
        "MeterNumber": "Meter Number",
        "SerialNumber": "Serial Number",
        "State": "State",
        "TypeDescription": "Type Description",
        "Firmware": "Firmware",
        "LocationId": "Location ID",
    }

    for xml_tag, label in fields.items():
        elem = root.find(f".//{xml_tag}")
        if elem is not None and elem.text:
            details[label] = elem.text.strip()

    return details

def parse_profile_registers(profile_xml: str):
    root = ET.fromstring(profile_xml)
    rows = []
    for reg in root.findall(".//Register"):
        rows.append({
            "Register ID": reg.attrib.get("id", ""),
            "Name": reg.attrib.get("name", ""),
            "Actions": reg.attrib.get("actions", ""),
            "Command": reg.attrib.get("command", ""),
        })
    return pd.DataFrame(rows).drop_duplicates()

def try_read_register(meter_id: str, obis: str):
    safe_obis = obis.replace(".", "%2E")
    urls = [
        f"{BASE_URL}/api/meters/{meter_id}/registers/{obis}/",
        f"{BASE_URL}/api/meters/{meter_id}/registers/{safe_obis}/",
        f"{BASE_URL}/api/meters/{meter_id}/read/{obis}/",
        f"{BASE_URL}/api/meters/{meter_id}/read/{safe_obis}/",
        f"{BASE_URL}/api/meters/{meter_id}/commands/RegisterCommand/{obis}/",
        f"{BASE_URL}/api/meters/{meter_id}/commands/RegisterCommand/{safe_obis}/",
        f"{BASE_URL}/api/registers/{meter_id}/{obis}/",
        f"{BASE_URL}/api/registers/{meter_id}/{safe_obis}/",
        f"{BASE_URL}/api/values/{meter_id}/{obis}/",
        f"{BASE_URL}/api/values/{meter_id}/{safe_obis}/",
    ]

    attempts = []
    for url in urls:
        try:
            r = requests.get(url, timeout=60)
            attempts.append({
                "OBIS": obis,
                "URL": url,
                "Status": r.status_code,
                "Content Type": r.headers.get("Content-Type", ""),
                "Preview": r.text[:300],
            })
            if r.status_code == 200:
                return r.text, attempts
        except Exception as e:
            attempts.append({
                "OBIS": obis,
                "URL": url,
                "Status": "ERROR",
                "Content Type": "",
                "Preview": str(e),
            })
    return "", attempts

def extract_value(text):
    if not text:
        return ""
    try:
        root = ET.fromstring(text)
        for attr in ["value", "Value"]:
            if attr in root.attrib:
                return root.attrib[attr]
        for elem in root.iter():
            if elem.tag.lower().endswith("value") and elem.text:
                return elem.text.strip()
        return text[:500]
    except Exception:
        return text[:500]

serial_no = st.text_input("Enter normal meter serial number", value="34977788")

if serial_no:
    try:
        meter_id = serial_to_meter_id(serial_no)
        st.write("### Converted Meter ID")
        st.code(meter_id)
        st.write("### Meter Endpoint")
        st.code(f"{BASE_URL}/api/meters/{meter_id}/")
    except Exception as e:
        st.error(e)
        meter_id = ""

if st.button("Get Meter + Profile + OBIS"):
    try:
        meter_id = serial_to_meter_id(serial_no)

        meter_url, meter_xml = get_meter_xml(meter_id)
        details = parse_meter_details(meter_xml)

        st.success("Meter opened successfully.")
        st.write("### Meter Details")
        st.json(details)

        profile_ref = details.get("Profile Ref", "")

        if not profile_ref:
            st.error("No Profile Ref found inside the meter XML.")
        else:
            st.write("### Profile Ref Found Automatically")
            st.code(profile_ref)

            profile_response = requests.get(profile_ref, timeout=60)
            st.write("Profile Status:", profile_response.status_code)

            if profile_response.status_code == 200:
                df_profile = parse_profile_registers(profile_response.text)

                df_required = pd.DataFrame([
                    {
                        "Register ID": obis,
                        "Description": desc,
                        "Unit": unit,
                        "Scale": scale,
                        "Available in Profile": "YES" if obis in set(df_profile["Register ID"]) else "NO",
                    }
                    for obis, (desc, unit, scale) in TARGET_OBIS.items()
                ])

                st.write("### Required OBIS Availability")
                st.dataframe(df_required, use_container_width=True)

                st.write("### All Readable Registers From This Meter Profile")
                st.dataframe(df_profile, use_container_width=True)

                all_attempts = []
                result_rows = []

                for obis, (desc, unit, scale) in TARGET_OBIS.items():
                    value_text, attempts = try_read_register(meter_id, obis)
                    all_attempts.extend(attempts)

                    result_rows.append({
                        "Register ID": obis,
                        "Description": desc,
                        "Unit": unit,
                        "Scale": scale,
                        "Value": extract_value(value_text),
                        "Status": "Read OK" if value_text else "Endpoint not confirmed",
                    })

                df_results = pd.DataFrame(result_rows)

                st.write("### OBIS Read Results")
                st.dataframe(df_results, use_container_width=True)

                st.write("### Endpoint Attempts")
                st.dataframe(pd.DataFrame(all_attempts), use_container_width=True)

                output = BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    pd.DataFrame([details]).to_excel(writer, index=False, sheet_name="Meter Details")
                    df_required.to_excel(writer, index=False, sheet_name="OBIS Availability")
                    df_results.to_excel(writer, index=False, sheet_name="OBIS Results")
                    pd.DataFrame(all_attempts).to_excel(writer, index=False, sheet_name="Endpoint Attempts")
                    df_profile.to_excel(writer, index=False, sheet_name="Profile Registers")
                output.seek(0)

                st.download_button(
                    label="📥 Download Excel",
                    data=output,
                    file_name=f"Meter_{serial_no}_profile_obis.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            else:
                st.error(profile_response.text[:2000])

    except Exception as e:
        st.error(f"Error: {e}")
