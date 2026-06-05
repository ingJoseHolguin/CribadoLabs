"""Pestaña: LLM — configuración de Ollama local."""

import streamlit as st

from services.config import load_llm_config, save_llm_config
from services.llm_client import fetch_ollama_models


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

    st.caption(
        "La evaluación de criterios se realiza desde la pestaña **Cribado Progresivo** → Fase 1."
    )
