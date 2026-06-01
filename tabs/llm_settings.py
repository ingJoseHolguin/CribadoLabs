"""Pestaña: LLM — configuración de Ollama local y evaluación por criterio."""

import pandas as pd
import streamlit as st

from services.config import load_llm_config, save_llm_config
from services.criteria_manager import rebuild_criteria_columns, update_total_score
from services.llm_client import evaluate_row_criterion, fetch_ollama_models
from services.persistence import load_master_dataframe
from tabs import safe_save_master_dataframe


def llm_settings_tab():
    st.subheader("LLM local (Ollama)")
    st.write("Configura Ollama local para evaluar cada fila sin conservar contexto global.")

    llm_config = load_llm_config()
    st.session_state.setdefault("ollama_endpoint", llm_config["endpoint"])
    st.session_state.setdefault("ollama_model", llm_config["model"])

    col_endpoint, col_model = st.columns([2, 1])
    with col_endpoint:
        endpoint = st.text_input(
            "URL o IP con puerto (Ollama)",
            value=st.session_state["ollama_endpoint"],
            placeholder="http://localhost:11434",
        )

    available_models = fetch_ollama_models(endpoint.strip())

    with col_model:
        if available_models:
            current_model = st.session_state["ollama_model"]
            default_index = available_models.index(current_model) if current_model in available_models else 0
            model = st.selectbox("Modelo", options=available_models, index=default_index)
        else:
            model = st.text_input(
                "Modelo",
                value=st.session_state["ollama_model"],
                placeholder="llama3.1",
                help="Asegúrate de que Ollama esté ejecutándose para ver la lista de modelos.",
            )

    st.session_state["ollama_endpoint"] = endpoint.strip()
    st.session_state["ollama_model"] = model.strip()

    col_save_config, col_test = st.columns([1, 1])
    with col_save_config:
        if st.button("Guardar configuración", use_container_width=True):
            save_llm_config(st.session_state["ollama_endpoint"], st.session_state["ollama_model"])
            st.success("Configuración guardada.")

    with col_test:
        test_connection = st.button("Probar conexión", use_container_width=True)

    if test_connection:
        with st.spinner("Conectando con Ollama (esto puede tardar si el modelo se está cargando)..."):
            try:
                from services.llm_client import ollama_chat
                response = ollama_chat(
                    st.session_state["ollama_endpoint"],
                    st.session_state["ollama_model"],
                    'Responde solamente {"ok": true}',
                )
                st.success("Conexión recibida exitosamente.")
                st.code(response, language="json")
            except Exception as exc:
                st.error(f"No se pudo consultar el LLM: {exc}")

    st.divider()
    st.subheader("Evaluar criterios")

    df = st.session_state.get("master_df", load_master_dataframe())
    criteria = st.session_state.get("criteria", [])

    if df.empty:
        st.warning("Carga o procesa la tabla maestra antes de evaluar.")
        return

    if not criteria:
        st.warning("Añade al menos un criterio antes de evaluar.")
        return

    # Sincronizar columnas
    df = rebuild_criteria_columns(df, criteria, st.session_state.get("keywords", []))
    st.session_state["master_df"] = df
    update_total_score(df)

    criterion_options = {
        f"C{index} ({'Inclusión' if criterion.get('type') == 'inclusion' else 'Exclusión'}): {criterion.get('text', '')}": (index, criterion.get('text', ''))
        for index, criterion in enumerate(criteria, start=1)
    }
    selected_criteria = st.multiselect(
        "Criterios a evaluar",
        list(criterion_options.keys()),
        default=list(criterion_options.keys()),
    )

    col_start, col_limit = st.columns([1, 1])
    with col_start:
        start_row = st.number_input("Fila inicial", min_value=1, max_value=len(df), value=1)
    with col_limit:
        row_limit = st.number_input(
            "Cantidad de filas",
            min_value=1,
            max_value=len(df),
            value=min(5, len(df)),
        )
    save_each_row = st.checkbox("Guardar Excel al terminar cada fila", value=True)
    skip_evaluated = st.checkbox("Saltar criterios ya evaluados", value=True)

    col_run_llm, col_clear_llm = st.columns([2, 1])
    with col_run_llm:
        run_llm = st.button("Ejecutar evaluación LLM", type="primary", use_container_width=True)
    with col_clear_llm:
        with st.popover("Limpiar evaluaciones"):
            st.warning("Esto borrará las puntuaciones y respuestas actuales para reiniciar la evaluación.")
            if st.button("Confirmar borrado", type="primary", use_container_width=True):
                for index, criterion in enumerate(criteria, start=1):
                    col_response = f"C{index} Respuesta: {criterion.get('text', '')}"
                    if col_response in df.columns:
                        df[col_response] = ""
                    for sub in ["Semantic", "Context", "Centrality", "Evidence", "Penalty", "Total"]:
                        col_sub = f"C{index} {sub}"
                        if col_sub in df.columns:
                            df[col_sub] = 0
                update_total_score(df)
                st.session_state["master_df"] = df
                safe_save_master_dataframe(df)
                st.rerun()

    if run_llm:
        if not selected_criteria:
            st.warning("Selecciona al menos un criterio.")
            return

        start_index = int(start_row) - 1
        end_index = min(start_index + int(row_limit), len(df))
        total_tasks = (end_index - start_index) * len(selected_criteria)
        progress_text = f"Progreso: 0/{total_tasks} evaluaciones"
        progress = st.progress(0.0, text=progress_text)
        status = st.empty()

        st.markdown("### Logs en tiempo real")
        log_container = st.empty()
        log_text = ""

        completed = 0

        for row_position in range(start_index, end_index):
            title = str(df.at[row_position, "Titulo"]) if "Titulo" in df else ""
            abstract = str(df.at[row_position, "Abstract"]) if "Abstract" in df else ""

            for selected in selected_criteria:
                criterion_index, criterion = criterion_options[selected]
                criterion_id = f"C{criterion_index}"
                col_response = f"C{criterion_index} Respuesta: {criterion}"
                col_semantic = f"C{criterion_index} Semantic"
                col_context = f"C{criterion_index} Context"
                col_centrality = f"C{criterion_index} Centrality"
                col_evidence = f"C{criterion_index} Evidence"
                col_penalty = f"C{criterion_index} Penalty"
                col_final = f"C{criterion_index} Total"

                if skip_evaluated:
                    existing_response = df.at[row_position, col_response]
                    if pd.notna(existing_response) and str(existing_response).strip() != "":
                        completed += 1
                        progress_text = f"Progreso: {completed}/{total_tasks} evaluaciones"
                        progress.progress(completed / total_tasks, text=progress_text)
                        log_entry = f"⏭️ Fila {row_position + 1} | C{criterion_index} -> Ya evaluado (omitido)\n\n"
                        log_text = log_entry + log_text
                        log_container.text_area("Registro", value=log_text, height=300, disabled=True, label_visibility="collapsed")
                        continue

                status.write(f"Evaluando fila {row_position + 1}, C{criterion_index}...")

                try:
                    result = evaluate_row_criterion(
                        st.session_state["ollama_endpoint"],
                        st.session_state["ollama_model"],
                        title,
                        abstract,
                        criterion_id,
                        criterion,
                    )
                    df.at[row_position, col_response] = result["respuesta"]
                    df.at[row_position, col_semantic] = result["semantic_match"]
                    df.at[row_position, col_context] = result["context_alignment"]
                    df.at[row_position, col_centrality] = result["centrality"]
                    df.at[row_position, col_evidence] = result["evidence_strength"]
                    df.at[row_position, col_penalty] = result["exclusion_penalty"]
                    df.at[row_position, col_final] = result["final_score"]

                    log_entry = f"✅ Fila {row_position + 1} | C{criterion_index} -> Total: {result['final_score']} | {result['respuesta']}\n\n"
                    log_text = log_entry + log_text
                    log_container.text_area("Registro", value=log_text, height=300, disabled=True, label_visibility="collapsed")
                except Exception as exc:
                    df.at[row_position, col_response] = f"Error: {exc}"
                    df.at[row_position, col_final] = 0

                    log_entry = f"❌ Fila {row_position + 1} | {criterion_id} -> Error: {exc}\n\n"
                    log_text = log_entry + log_text
                    log_container.text_area("Registro", value=log_text, height=300, disabled=True, label_visibility="collapsed")

                completed += 1
                progress_text = f"Progreso: {completed}/{total_tasks} evaluaciones"
                progress.progress(completed / total_tasks, text=progress_text)

            update_total_score(df)
            if save_each_row:
                safe_save_master_dataframe(df)

        update_total_score(df)
        st.session_state["master_df"] = df
        output_file = safe_save_master_dataframe(df)
        st.success(f"Evaluación guardada en {output_file}.")

    st.session_state["master_df"] = df
