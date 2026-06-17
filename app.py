import streamlit as st
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import BytesIO

BASE_URL = "http://197.189.218.35/utilidriver"

st.set_page_config(page_title="REM Meter Tool", page_icon="⚡", layout="wide")

st.title("⚡ Republic Metering - Meter Lookup Tool")
st.write("Search by normal meter serial number. The app will find the UtiliDriver meter ref and then pull the profile.")

serial_no = st.text_input("Enter meter serial number", value="")

def get_all_meters():
    """
    Reads the UtiliDriver meters XML list.
    Example endpoint:
    http://197.189.218.35/utilidriver/api/meters/
    """
    url = f"{BASE_URL}/api/meters/"
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    root = ET.fromstring(response.text)

    meters = []
    for meter in root.findall(".//Meter"):
        meters.append({
            "serialNumber": meter.attrib.get("serialNumber", ""),
            "state": meter.attrib.get("state", ""),
            "ref": meter.attrib.get("ref", "")
        })

    return pd.DataFrame(meters)

def find_meter_by_serial(serial):
    df_meters = get_all_meters()

    match = df_meters[df_meters["serialNumber"].astype(str) == str(serial)]

    if match.empty:
        return None, df_meters

    return match.iloc[0].to_dict(), df_meters

def get_profile_from_ref(meter_ref):
    """
    Uses the long UtiliDriver meter ref.
    Example:
    http://197.189.218.35/utilidriver/api/meters/4B414D0000000179382A/
    Then tries common profile/register endpoints from that ref.
    """
    possible_urls = [
        meter_ref,
        meter_ref.rstrip("/") + "/profiles/",
        meter_ref.rstrip("/") + "/profile/",
        meter_ref.rstrip("/") + "/registers/",
        meter_ref.rstrip("/") + "/readings/",
    ]

    results = []

    for url in possible_urls:
        try:
            response = requests.get(url, timeout=60)
            results.append({
                "url": url,
                "status_code": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "text": response.text
            })

            if response.status_code == 200:
                return response, results

        except Exception as e:
            results.append({
                "url": url,
                "status_code": "ERROR",
                "content_type": "",
                "text": str(e)
            })

    return None, results

if st.button("Search Meter"):
    if not serial_no.strip():
        st.warning("Please enter a meter serial number.")
    else:
        try:
            with st.spinner("Loading meter list from UtiliDriver..."):
                meter, df_meters = find_meter_by_serial(serial_no.strip())

            if meter is None:
                st.error("Meter serial number not found in UtiliDriver meter list.")
                st.write("First 50 meters from UtiliDriver:")
                st.dataframe(df_meters.head(50), use_container_width=True)
            else:
                st.success("Meter found.")
                st.write("### Meter Details")
                st.json(meter)

                meter_ref = meter["ref"]

                st.write("### UtiliDriver Meter Ref")
                st.code(meter_ref)

                with st.spinner("Trying to retrieve meter/profile/register data..."):
                    response, attempts = get_profile_from_ref(meter_ref)

                st.write("### Endpoint Attempts")
                st.dataframe(pd.DataFrame([
                    {
                        "url": item["url"],
                        "status_code": item["status_code"],
                        "content_type": item["content_type"],
                        "preview": item["text"][:120]
                    }
                    for item in attempts
                ]), use_container_width=True)

                if response is None:
                    st.error("Meter was found, but no working profile/register endpoint was found yet.")
                    st.info("Open one of the UtiliDriver meter screens and send the exact URL/API endpoint used for profiles or registers.")
                else:
                    st.success("Data retrieved from UtiliDriver.")
                    st.write("### Raw Response Preview")
                    st.text(response.text[:3000])

                    content_type = response.headers.get("Content-Type", "")

                    # Try JSON first
                    try:
                        data = response.json()
                        df = pd.json_normalize(data)
                        st.write("### Table")
                        st.dataframe(df, use_container_width=True)

                        output = BytesIO()
                        df.to_excel(output, index=False)
                        output.seek(0)

                        st.download_button(
                            label="📥 Download Excel",
                            data=output,
                            file_name=f"Meter_{serial_no}_data.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

                    except Exception:
                        # Try XML into a simple attribute table
                        try:
                            root = ET.fromstring(response.text)
                            rows = []
                            for elem in root.iter():
                                row = {"tag": elem.tag}
                                row.update(elem.attrib)
                                if elem.text and elem.text.strip():
                                    row["text"] = elem.text.strip()
                                rows.append(row)

                            df = pd.DataFrame(rows)
                            st.write("### XML Parsed Table")
                            st.dataframe(df, use_container_width=True)

                            output = BytesIO()
                            df.to_excel(output, index=False)
                            output.seek(0)

                            st.download_button(
                                label="📥 Download Excel",
                                data=output,
                                file_name=f"Meter_{serial_no}_xml_data.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )

                        except Exception:
                            st.warning("Response is not JSON or readable XML. Showing raw text only.")

        except Exception as e:
            st.error(f"Error: {e}")
