"""Pestaña: Tabla maestra — procesamiento, edición interactiva y métricas."""

import pandas as pd
import streamlit as st

from services.bibliographic import (
    INPUT_FOLDER,
    MASTER_FILENAME,
    NORMALIZED_COLUMNS,
    OUTPUT_FOLDER,
    process_folder,
)
from services.criteria_manager import update_total_score
from services.persistence import load_master_dataframe
from tabs import safe_save_master_dataframe


def metric_cards(df):
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Registros", len(df))
    if not df.empty and "Año" in df.columns:
        years = pd.to_numeric(df["Año"], errors="coerce").dropna()
        if not years.empty:
            col2.metric("Año mín", int(years.min()))
            col3.metric("Año máx", int(years.max()))
            col4.metric("Año med", round(years.median(), 1))


def processing_tab():
    st.subheader("Procesar y editar tabla maestra")

    col_run, col_load, col_save, col_refresh = st.columns([1, 1, 1, 1])
    with col_run:
        run_processing = st.button("Procesar fuentes", type="primary", use_container_width=True)
    with col_load:
        load_existing = st.button("Cargar Excel existente", use_container_width=True)
    with col_save:
        save_edits = st.button("Guardar edición", use_container_width=True)
    with col_refresh:
        if st.button("Actualizar vista", use_container_width=True):
            st.session_state["master_df"] = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
            st.rerun()

    if run_processing:
        with st.spinner("Leyendo fuentes y normalizando registros..."):
            df, errors = process_folder(INPUT_FOLDER)
            st.session_state["master_df"] = df
            st.session_state["processing_errors"] = errors
            output_file = safe_save_master_dataframe(df)
        st.success(f"Tabla generada en {output_file}.")

    if load_existing:
        st.session_state["master_df"] = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
        st.success("Excel cargado desde output.")

    if "master_df" not in st.session_state:
        st.session_state["master_df"] = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)

    df = st.session_state["master_df"]
    metric_cards(df)

    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Abstract": st.column_config.TextColumn("Abstract", width="large"),
            "URL": st.column_config.LinkColumn("URL"),
        },
    )
    update_total_score(edited_df)
    st.session_state["master_df"] = edited_df

    if save_edits:
        update_total_score(edited_df)
        output_file = safe_save_master_dataframe(edited_df)
        st.success(f"Cambios guardados en {output_file}.")

    with st.expander("Limpiar tabla maestra"):
        st.write("Esto vacía la tabla visible y guarda un Excel maestro sin registros.")
        confirm_clear_master = st.checkbox(
            "Confirmo que quiero limpiar la tabla maestra",
            key="confirm_clear_master",
        )
        if st.button("Limpiar tabla maestra", disabled=not confirm_clear_master, use_container_width=True):
            empty_df = pd.DataFrame(columns=NORMALIZED_COLUMNS)
            st.session_state["master_df"] = empty_df
            st.session_state["processing_errors"] = []
            output_file = safe_save_master_dataframe(empty_df)
            st.success(f"Tabla maestra limpia guardada en {output_file}.")
            st.rerun()

    errors = st.session_state.get("processing_errors", [])
    if errors:
        with st.expander("Errores de procesamiento"):
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
