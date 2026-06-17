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
st.title("⚡ Republic Metering - Kamstrup OBIS Reader")

def serial_to_meter_id(serial_number: str) -> str:
    serial_number = str(serial_number).strip()
    if not serial_number.isdigit():
        raise ValueError("Serial number must only contain numbers.")
    serial_hex = format(int(serial_number), "X").upper()
    return f"{METER_PREFIX}{serial_hex}"

def parse_profile_registers(xml_text: str) -> pd.DataFrame:
    root = ET.fromstring(xml_text)
    rows = []
    for register in root.findall(".//Register"):
        rows.append({
            "Register ID": register.attrib.get("id", ""),
            "Name": register.attrib.get("name", ""),
            "Actions": register.attrib.get("actions", ""),
            "Command": register.attrib.get("command", ""),
        })
    return pd.DataFrame(rows).drop_duplicates()

def try_read_register(meter_id: str, obis: str):
    """
    We know the OBIS codes exist in the profile, but UtiliDriver still needs the correct
    read endpoint. This tries common API patterns and shows which one works.
    """
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
                return r, attempts
        except Exception as e:
            attempts.append({
                "OBIS": obis,
                "URL": url,
                "Status": "ERROR",
                "Content Type": "",
                "Preview": str(e),
            })
    return None, attempts

def response_to_value(response_text):
    """
    Generic value extractor. Once the exact endpoint is confirmed, this can be tightened.
    """
    # Try JSON
    try:
        data = requests.models.complexjson.loads(response_text)
        if isinstance(data, dict):
            for key in ["value", "Value", "result", "Result", "reading", "Reading"]:
                if key in data:
                    return data[key]
            return data
        return data
    except Exception:
        pass

    # Try XML
    try:
        root = ET.fromstring(response_text)
        for attr in ["value", "Value"]:
            if attr in root.attrib:
                return root.attrib[attr]
        for elem in root.iter():
            if elem.tag.lower().endswith("value") and elem.text:
                return elem.text.strip()
        return response_text[:500]
    except Exception:
        pass

    return response_text[:500]

serial_no = st.text_input("Meter serial number", value="24165632")
profile_id = st.text_input("Profile ID", value="2736303202")

try:
    meter_id = serial_to_meter_id(serial_no)
    st.write("### Converted UtiliDriver Meter ID")
    st.code(meter_id)
    st.write("### Meter URL")
    st.code(f"{BASE_URL}/api/meters/{meter_id}/")
except Exception as e:
    st.error(e)
    meter_id = ""

col1, col2 = st.columns(2)

with col1:
    if st.button("Check Profile OBIS Availability"):
        try:
            profile_url = f"{BASE_URL}/api/profiles/{profile_id}/"
            r = requests.get(profile_url, timeout=60)
            st.write("Profile Status:", r.status_code)

            if r.status_code == 200:
                df_profile = parse_profile_registers(r.text)
                df_target = pd.DataFrame([
                    {
                        "Register ID": obis,
                        "Required Description": desc,
                        "Expected Unit": unit,
                        "Expected Scale": scale,
                        "Available in Profile": "YES" if obis in set(df_profile["Register ID"]) else "NO",
                    }
                    for obis, (desc, unit, scale) in TARGET_OBIS.items()
                ])

                st.write("### Required OBIS Codes")
                st.dataframe(df_target, use_container_width=True)

                st.write("### All readable profile registers")
                st.dataframe(df_profile, use_container_width=True)
            else:
                st.error(r.text[:2000])
        except Exception as e:
            st.error(e)

with col2:
    if st.button("Try Read OBIS Values"):
        if not meter_id:
            st.warning("Enter a valid serial number first.")
        else:
            all_attempts = []
            result_rows = []

            for obis, (desc, unit, scale) in TARGET_OBIS.items():
                response, attempts = try_read_register(meter_id, obis)
                all_attempts.extend(attempts)

                value = ""
                status = "Not read"

                if response is not None:
                    value = response_to_value(response.text)
                    status = "Read OK"

                result_rows.append({
                    "Register ID": obis,
                    "Description": desc,
                    "Unit": unit,
                    "Scale": scale,
                    "Value": value,
                    "Status": status,
                })

            df_results = pd.DataFrame(result_rows)
            st.write("### OBIS Reading Results")
            st.dataframe(df_results, use_container_width=True)

            st.write("### Endpoint Attempts")
            st.dataframe(pd.DataFrame(all_attempts), use_container_width=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_results.to_excel(writer, index=False, sheet_name="OBIS Results")
                pd.DataFrame(all_attempts).to_excel(writer, index=False, sheet_name="Endpoint Attempts")
            output.seek(0)

            st.download_button(
                label="📥 Download Excel",
                data=output,
                file_name=f"Meter_{serial_no}_obis_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
