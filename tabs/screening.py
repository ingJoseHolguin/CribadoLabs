"""Pestaña: Cribado Progresivo — Pipeline F0→F3 con reportes PRISMA."""

from pathlib import Path

import pandas as pd
import streamlit as st

from services.persistence import OUTPUT_FOLDER, load_master_dataframe
from services.reporting import (
    exportar_excel_por_etapa,
    exportar_resumen_excel,
    generar_figura_prisma,
    generar_reporte_md,
    generar_reporte_prisma_por_criterio,
)
from services.screening import (
    cargar_keywords_screening,
    fase0_prefiltrado,
    fase1_cribado_por_criterio,
    fase2_revision_dudosos,
    fase3_extraccion_pis,
    guardar_keywords_screening,
)
from tabs import safe_save_master_dataframe


def progressive_screening_tab():
    st.subheader("Cribado por Criterio Individual (PCC)")
    st.write("Flujo de 4 fases: Keywords → 13 criterios independientes → Revisión dudosos → Extracción PIs")

    df_master = st.session_state.get("master_df", load_master_dataframe())
    if df_master.empty:
        st.warning("Carga o procesa la tabla maestra antes de iniciar.")
        return

    st.success(f"Tabla maestra cargada: **{len(df_master)}** registros.")

    # Configuración
    with st.expander("Configuración de ejecución", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            delay = st.number_input(
                "Delay entre llamadas (s)",
                min_value=0.0, max_value=5.0, value=1.0, step=0.5, key="scr_delay"
            )
        with c2:
            skip_evaluated = st.checkbox("Saltar filas ya evaluadas", value=True, key="scr_skip")

    # Keywords editables
    with st.expander("Configuración de Keywords (Fase 0)", expanded=True):
        kw = cargar_keywords_screening()
        st.session_state.setdefault("kw_colaboracion", "\n".join(kw.get("keywords_colaboracion", [])))
        st.session_state.setdefault("kw_contexto", "\n".join(kw.get("keywords_contexto", [])))
        st.session_state.setdefault("kw_sinonimos", "\n".join(kw.get("sinonimos_calidad", [])))

        col1, col2, col3 = st.columns(3)
        with col1:
            txt_col = st.text_area(
                "Keywords colaboración",
                value=st.session_state["kw_colaboracion"],
                height=200, key="kw_colaboracion"
            )
        with col2:
            txt_ctx = st.text_area(
                "Keywords contexto",
                value=st.session_state["kw_contexto"],
                height=200, key="kw_contexto"
            )
        with col3:
            txt_sin = st.text_area(
                "Sinónimos calidad",
                value=st.session_state["kw_sinonimos"],
                height=200, key="kw_sinonimos"
            )

        if st.button("Guardar keywords", key="btn_save_kw"):
            nuevo_kw = {
                "keywords_colaboracion": [l.strip() for l in txt_col.split("\n") if l.strip()],
                "keywords_contexto": [l.strip() for l in txt_ctx.split("\n") if l.strip()],
                "sinonimos_calidad": [l.strip() for l in txt_sin.split("\n") if l.strip()],
            }
            guardar_keywords_screening(nuevo_kw)
            st.success(f"Keywords guardadas en {OUTPUT_DIR / 'config/screening_keywords.json'}")

    llm_config = {
        "endpoint": st.session_state.get("ollama_endpoint", "http://localhost:11434"),
        "model": st.session_state.get("ollama_model", "llama3.1"),
    }

    # Test de conexión rápido
    with st.expander("Diagnóstico LLM", expanded=False):
        col_test, col_test_info = st.columns([1, 3])
        with col_test:
            if st.button("Probar conexión LLM", key="btn_test_llm_cribado"):
                with st.spinner("Conectando..."):
                    try:
                        from services.llm_client import ollama_chat
                        resp = ollama_chat(
                            llm_config["endpoint"],
                            llm_config["model"],
                            'Responde solamente {"ok": true}',
                        )
                        st.success(f"Conexión OK. Respuesta: {resp}")
                    except Exception as exc:
                        st.error(f"Error de conexión: {exc}")
        with col_test_info:
            st.caption(
                "Si obtienes 401 Unauthorized, verifica que Ollama esté ejecutándose "
                "sin autenticación (comando: ollama serve) y que el endpoint sea correcto."
            )

    # Pipeline automático
    st.divider()
    col_pipe, col_pipe_info = st.columns([1, 3])
    with col_pipe:
        run_pipeline = st.button(
            "Ejecutar Pipeline Automático (F0→F3)",
            type="primary", key="btn_pipeline", use_container_width=True,
        )
    with col_pipe_info:
        st.caption("Ejecuta F0 (keywords) → F1 (13 criterios) → F2 (dudosos) → F3 (extracción) → Reporte PRISMA")

    if run_pipeline:
        kw_config = cargar_keywords_screening()
        with st.spinner("Pipeline: F0 (pre-filtrado por keywords)..."):
            df_f0, rep_f0 = fase0_prefiltrado(df_master, kw_config)
            st.session_state["screening_f0_df"] = df_f0
            st.session_state["screening_f0_reporte"] = rep_f0
            exportar_excel_por_etapa(df_f0, "fase0", OUTPUT_FOLDER)
            exportar_resumen_excel(rep_f0, "fase0", OUTPUT_FOLDER)
        st.success(f"✅ F0 completado — Pasan={rep_f0['pasan']}, Dudoso={rep_f0['dudosos']}, Excluidos={rep_f0['excluidos']}")

        progress_f1 = st.progress(0.0, text="F1: Iniciando...")
        log_container_f1 = st.empty()
        log_lines_f1 = []

        def _callback_f1(current, total):
            progress_f1.progress(current / total, text=f"F1: {current}/{total} criterios evaluados")

        def _log_f1(msg):
            log_lines_f1.append(msg)
            log_container_f1.text_area("Log F1", value="\n".join(log_lines_f1[-50:]), height=250, disabled=True, label_visibility="collapsed")

        st.info("⏳ La primera llamada al LLM puede tardar varios minutos mientras Ollama carga el modelo en memoria.")
        with st.spinner("Pipeline: F1 (13 criterios independientes)..."):
            df_f1, rep_f1 = fase1_cribado_por_criterio(
                df_f0, llm_config, delay=delay, progress_callback=_callback_f1, log_callback=_log_f1, skip_evaluated=skip_evaluated
            )
            st.session_state["screening_f1_df"] = df_f1
            st.session_state["screening_f1_reporte"] = rep_f1
            exportar_excel_por_etapa(df_f1, "fase1", OUTPUT_FOLDER)
            exportar_resumen_excel(rep_f1, "fase1", OUTPUT_FOLDER)
        st.success(f"✅ F1 completado — Incluir={rep_f1['incluir']}, Excluir={rep_f1['excluir']}, Dudoso={rep_f1['dudoso']}")
        progress_f1.empty()

        progress_f2 = st.progress(0.0, text="F2: Iniciando...")
        log_container_f2 = st.empty()
        log_lines_f2 = []

        def _callback_f2(current, total):
            progress_f2.progress(current / total, text=f"F2: {current}/{total} dudosos revisados")

        def _log_f2(msg):
            log_lines_f2.append(msg)
            log_container_f2.text_area("Log F2", value="\n".join(log_lines_f2[-50:]), height=200, disabled=True, label_visibility="collapsed")

        with st.spinner("Pipeline: F2 (revisión de dudosos)..."):
            df_f2, rep_f2 = fase2_revision_dudosos(
                df_f1, llm_config, delay=delay, progress_callback=_callback_f2, log_callback=_log_f2, skip_evaluated=skip_evaluated
            )
            st.session_state["screening_f2_df"] = df_f2
            st.session_state["screening_f2_reporte"] = rep_f2
            exportar_excel_por_etapa(df_f2, "fase2", OUTPUT_FOLDER)
            exportar_resumen_excel(rep_f2, "fase2", OUTPUT_FOLDER)
        st.success(f"✅ F2 completado — Include={rep_f2['decisiones_f2']['INCLUDE']}, Exclude={rep_f2['decisiones_f2']['EXCLUDE']}")
        progress_f2.empty()

        progress_f3 = st.progress(0.0, text="F3: Iniciando...")
        log_container_f3 = st.empty()
        log_lines_f3 = []

        def _callback_f3(current, total):
            progress_f3.progress(current / total, text=f"F3: {current}/{total} extracciones")

        def _log_f3(msg):
            log_lines_f3.append(msg)
            log_container_f3.text_area("Log F3", value="\n".join(log_lines_f3[-50:]), height=200, disabled=True, label_visibility="collapsed")

        with st.spinner("Pipeline: F3 (extracción de datos PIs)..."):
            df_f3, rep_f3 = fase3_extraccion_pis(
                df_f2, llm_config, delay=delay, progress_callback=_callback_f3, log_callback=_log_f3, skip_evaluated=skip_evaluated
            )
            st.session_state["screening_f3_df"] = df_f3
            st.session_state["screening_f3_reporte"] = rep_f3
            exportar_excel_por_etapa(df_f3, "fase3", OUTPUT_FOLDER)
            exportar_resumen_excel(rep_f3, "fase3", OUTPUT_FOLDER)
        st.success(f"✅ F3 completado — PI1={rep_f3['por_pi']['PI1']}, PI2={rep_f3['por_pi']['PI2']}, PI3={rep_f3['por_pi']['PI3']}, PI4={rep_f3['por_pi']['PI4']}")
        progress_f3.empty()

        st.balloons()
        st.session_state["screening_pipeline_done"] = True

    # --- Resultados por fase ---
    for label, key_df, key_rep in [
        ("F0", "screening_f0_df", "screening_f0_reporte"),
        ("F1", "screening_f1_df", "screening_f1_reporte"),
        ("F2", "screening_f2_df", "screening_f2_reporte"),
        ("F3", "screening_f3_df", "screening_f3_reporte"),
    ]:
        df_s = st.session_state.get(key_df)
        rep = st.session_state.get(key_rep)
        if df_s is not None and rep is not None:
            with st.expander(f"Resultados {label}"):
                st.write(rep)
                st.dataframe(df_s.head(20), use_container_width=True)

    # --- Reporte PRISMA ---
    st.divider()
    st.markdown("### Reporte PRISMA por Criterio")
    df_f0_s = st.session_state.get("screening_f0_df")
    df_f1_s = st.session_state.get("screening_f1_df")
    df_f2_s = st.session_state.get("screening_f2_df")
    df_f3_s = st.session_state.get("screening_f3_df")

    if st.button("Generar reporte PRISMA", type="primary", key="btn_prisma"):
        rep_prisma = generar_reporte_prisma_por_criterio(
            df_f0_s if df_f0_s is not None else df_master,
            df_f1_s, df_f2_s, df_f3_s
        )
        st.session_state["screening_prisma_reporte"] = rep_prisma
        generar_figura_prisma(rep_prisma, OUTPUT_FOLDER / "figura_prisma.png")
        generar_reporte_md(rep_prisma, OUTPUT_FOLDER / "fase_reporte.md")
        st.success("Reporte PRISMA generado.")

    if "screening_prisma_reporte" in st.session_state:
        rep = st.session_state["screening_prisma_reporte"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", rep["total_registros"])
        c2.metric("Incluidos final", rep["f3_extraidos"])
        c3.metric("F2→Include", rep["f2_include"])

        fig_path = OUTPUT_FOLDER / "figura_prisma.png"
        if fig_path.exists():
            st.image(str(fig_path), caption="Diagrama PRISMA-ScR")

        md_path = OUTPUT_FOLDER / "fase_reporte.md"
        if md_path.exists():
            with open(md_path, "r", encoding="utf-8") as f:
                st.download_button(
                    "Descargar reporte MD", data=f.read(),
                    file_name="fase_reporte.md", mime="text/markdown",
                )
