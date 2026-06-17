import streamlit as st
import requests
import pandas as pd

BASE_URL = "http://197.189.218.35/utilidriver"

st.set_page_config(
    page_title="REM Meter Tool",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Republic Metering - Meter Lookup Tool")

st.write(
    "Enter a meter number below and retrieve information from UtiliDriver."
)

meter_no = st.text_input(
    "Meter Number",
    value=""
)

if st.button("Get Meter Data"):

    if meter_no == "":
        st.warning("Please enter a meter number.")
    else:

        try:

            url = f"{BASE_URL}/api/profiles/{meter_no}/"

            response = requests.get(
                url,
                timeout=30
            )

            st.write(f"Status Code: {response.status_code}")

            if response.status_code == 200:

                try:

                    data = response.json()

                    df = pd.json_normalize(data)

                    st.success("Meter data successfully retrieved.")

                    st.dataframe(
                        df,
                        use_container_width=True
                    )

                    excel_file = f"Meter_{meter_no}.xlsx"

                    df.to_excel(
                        excel_file,
                        index=False
                    )

                    with open(excel_file, "rb") as file:

                        st.download_button(
                            label="📥 Download Excel",
                            data=file,
                            file_name=excel_file,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

                except Exception as json_error:

                    st.error(
                        f"Response received but could not convert JSON.\n\n{json_error}"
                    )

                    st.text(response.text)

            else:

                st.error(
                    f"Server returned status code {response.status_code}"
                )

                st.text(response.text)

        except Exception as e:

            st.error(f"Connection Error: {e}")
