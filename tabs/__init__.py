"""Utilidades compartidas entre pestañas de Streamlit."""

import streamlit as st

from services.persistence import save_master_dataframe, OUTPUT_FOLDER, MASTER_FILENAME


def safe_save_master_dataframe(df_to_save):
    try:
        return save_master_dataframe(df_to_save)
    except PermissionError:
        st.toast("⚠️ No se pudo guardar en Excel. Por favor, cierra el archivo master si lo tienes abierto.", icon="⚠️")
        return OUTPUT_FOLDER / MASTER_FILENAME
