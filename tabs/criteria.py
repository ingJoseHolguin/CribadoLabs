"""Pestaña: Criterios — CRUD de criterios de inclusión/exclusión y palabras clave."""

import pandas as pd
import streamlit as st

from services.config import load_criteria, save_criteria, load_keywords, save_keywords
from services.criteria_manager import rebuild_criteria_columns
from services.persistence import load_master_dataframe
from tabs import safe_save_master_dataframe


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
    st.subheader("Criterios de selección")
    st.write("Aquí se preparará la iteración por fila. Cada criterio creará una nueva columna escalable.")

    def handle_add_criterion():
        val = st.session_state.get("new_criterion_input", "").strip()
        c_type = st.session_state.get("new_criterion_type", "inclusion")
        if val:
            st.session_state["criteria"].append({"text": val, "type": c_type})
            save_criteria(st.session_state["criteria"])
            _run_sync()
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

    col_add, col_apply = st.columns([1, 1])
    with col_add:
        st.button("Añadir criterio", use_container_width=True, on_click=handle_add_criterion)
    with col_apply:
        if st.button("Sincronizar columnas de criterios", use_container_width=True):
            _run_sync()
            st.success("Columnas de criterios sincronizadas.")

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
            _run_sync()
            st.success(f"Se eliminó {delete_id}: {removed.get('text', '')}. Los criterios fueron renumerados.")
            st.rerun()

    # --- PALABRAS CLAVE ---
    st.markdown("---")
    st.subheader("Búsqueda Rápida de Palabras Clave (por Código)")
    st.write(
        "Configura palabras clave u oraciones para buscar en el Titulo o Abstract de forma rápida. "
        "Para cada palabra clave se generarán dos columnas (`KW_Titulo: <palabra>` y `KW_Abstract: <palabra>`) "
        "con valor `1` si coincide (insensible a mayúsculas/minúsculas), `0` si no coincide y vacío si no se ha evaluado."
    )

    def handle_add_keyword():
        val = st.session_state.get("new_keyword_input", "").strip()
        if val:
            if val not in st.session_state["keywords"]:
                st.session_state["keywords"].append(val)
                save_keywords(st.session_state["keywords"])
                _run_sync()
            else:
                st.warning("Esa palabra clave ya existe.")
        st.session_state["new_keyword_input"] = ""

    if "new_keyword_input" not in st.session_state:
        st.session_state["new_keyword_input"] = ""

    col_kw_input, col_kw_btn = st.columns([3, 1])
    with col_kw_input:
        st.text_input("Nueva palabra clave u oración", placeholder="Ej. machine learning", key="new_keyword_input")
    with col_kw_btn:
        st.write("")
        st.button("Añadir palabra clave", use_container_width=True, on_click=handle_add_keyword)

    if st.session_state.get("keywords"):
        st.write("**Palabras clave configuradas:**")
        kw_df = pd.DataFrame({"Palabra Clave / Oración": st.session_state["keywords"]})
        st.dataframe(kw_df, use_container_width=True, hide_index=True)

        col_del_kw, col_del_btn = st.columns([3, 1])
        with col_del_kw:
            delete_kw = st.selectbox("Palabra clave a eliminar", st.session_state["keywords"], key="delete_kw_select")
            confirm_delete_kw = st.checkbox(
                f"Confirmo que quiero eliminar la palabra clave: '{delete_kw}'",
                key="confirm_delete_kw",
            )
        with col_del_btn:
            st.write("")
            st.write("")
            if st.button("Eliminar palabra clave", disabled=not confirm_delete_kw, use_container_width=True):
                st.session_state["keywords"].remove(delete_kw)
                save_keywords(st.session_state["keywords"])
                _run_sync()
                st.success(f"Palabra clave '{delete_kw}' eliminada.")
                st.rerun()

        st.markdown("### Ejecutar Búsqueda Rápida")
        overwrite_kw = st.checkbox(
            "Evaluar todas las filas (sobreescribir)",
            value=True,
            help="Si está desmarcado, solo buscará en las filas que tengan las columnas vacías (no evaluadas)."
        )

        if st.button("Ejecutar búsqueda por código", type="primary", use_container_width=True):
            df = st.session_state.get("master_df", load_master_dataframe())
            if df.empty:
                st.warning("Carga o procesa la tabla maestra antes de realizar la búsqueda.")
            else:
                _run_sync()
                df = st.session_state["master_df"]

                title_series = df["Titulo"].fillna("").astype(str)
                if "Titulo ES" in df.columns:
                    title_series = title_series + " " + df["Titulo ES"].fillna("").astype(str)

                abstract_series = df["Abstract"].fillna("").astype(str)
                if "Abstract ES" in df.columns:
                    abstract_series = abstract_series + " " + df["Abstract ES"].fillna("").astype(str)

                for keyword in st.session_state["keywords"]:
                    kw_clean = keyword.lower().strip()
                    col_title = f"KW_Titulo: {keyword}"
                    col_abstract = f"KW_Abstract: {keyword}"

                    if col_title not in df.columns:
                        df[col_title] = ""
                    if col_abstract not in df.columns:
                        df[col_abstract] = ""

                    if not overwrite_kw:
                        mask_title = df[col_title].isna() | (df[col_title].astype(str).str.strip() == "")
                        mask_abstract = df[col_abstract].isna() | (df[col_abstract].astype(str).str.strip() == "")
                    else:
                        mask_title = pd.Series(True, index=df.index)
                        mask_abstract = pd.Series(True, index=df.index)

                    match_title = title_series.str.lower().str.contains(kw_clean, regex=False, na=False)
                    match_abstract = abstract_series.str.lower().str.contains(kw_clean, regex=False, na=False)

                    df.loc[mask_title, col_title] = match_title[mask_title].map(lambda x: 1 if x else 0)
                    df.loc[mask_abstract, col_abstract] = match_abstract[mask_abstract].map(lambda x: 1 if x else 0)

                st.session_state["master_df"] = df
                safe_save_master_dataframe(df)
                st.success("Búsqueda de palabras clave completada. Las columnas en scoping_master.xlsx han sido actualizadas.")
                st.rerun()


def _run_sync():
    df = st.session_state.get("master_df", load_master_dataframe())
    criteria = st.session_state.get("criteria", [])
    keywords = st.session_state.get("keywords", [])
    df = rebuild_criteria_columns(df, criteria, keywords)
    st.session_state["master_df"] = df
    safe_save_master_dataframe(df)
