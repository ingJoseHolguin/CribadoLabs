"""Pestaña: Criterios — CRUD de criterios de inclusión/exclusión y palabras clave."""

import pandas as pd
import streamlit as st

from services.config import load_criteria, save_criteria, load_keywords, save_keywords


def criteria_dataframe():
    criteria = st.session_state.get("criteria", [])
    return pd.DataFrame(
        [
            {
                "ID": f"C{index}",
                "Tipo": "Inclusión" if criterion.get("type", "inclusion") == "inclusion" else "Exclusión",
                "Criterio": criterion.get("text", "")
            }
            for index, criterion in enumerate(criteria, start=1)
        ]
    )


def criteria_tab():
    st.subheader("Criterios de inclusión / exclusión")
    st.write(
        "Define aquí los criterios que se evaluarán en la pestaña **Cribado Progresivo → Fase 1**. "
        "Los cambios se guardan automáticamente en `config/criteria.json`."
    )

    def handle_add_criterion():
        val = st.session_state.get("new_criterion_input", "").strip()
        c_type = st.session_state.get("new_criterion_type", "inclusion")
        if val:
            st.session_state["criteria"].append({"text": val, "type": c_type})
            save_criteria(st.session_state["criteria"])
            st.success(f"Criterio de {c_type} añadido.")
        st.session_state["new_criterion_input"] = ""

    if "new_criterion_input" not in st.session_state:
        st.session_state["new_criterion_input"] = ""

    col_text, col_type = st.columns([3, 1])
    with col_text:
        st.text_input("Nuevo criterio", placeholder="Ej. Incluye población adulta", key="new_criterion_input")
    with col_type:
        st.selectbox(
            "Tipo",
            options=["inclusion", "exclusion"],
            format_func=lambda x: "Inclusión" if x == "inclusion" else "Exclusión",
            key="new_criterion_type"
        )

    if st.button("Añadir criterio", use_container_width=True):
        handle_add_criterion()

    if st.session_state["criteria"]:
        st.dataframe(criteria_dataframe(), use_container_width=True, hide_index=True)

        criterion_ids = [f"C{index}" for index in range(1, len(st.session_state["criteria"]) + 1)]
        delete_id = st.selectbox("Criterio a eliminar", criterion_ids)
        confirm_delete = st.checkbox(
            f"Confirmo que quiero eliminar {delete_id}",
            key="confirm_delete_criterion",
        )
        if st.button("Eliminar criterio", disabled=not confirm_delete, use_container_width=True):
            delete_index = int(delete_id.replace("C", "")) - 1
            removed = st.session_state["criteria"].pop(delete_index)
            save_criteria(st.session_state["criteria"])
            st.success(f"Se eliminó {delete_id}: {removed.get('text', '')}. Los criterios fueron renumerados.")
            st.rerun()

    st.caption(
        "Nota: La búsqueda de palabras clave se centralizó en la pestaña Cribado Progresivo (Fase 0). "
        "La evaluación con LLM se realiza desde Cribado Progresivo (Fase 1)."
    )
