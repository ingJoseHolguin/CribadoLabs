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
    fase0_busqueda_terminos,
    fase0_limpiar_terminos,
    fase0_prefiltrado,
    fase0_reiniciar_terminos,
    fase0_sumar_score,
    fase1_cribado_por_criterio,
    fase1_evaluar_inclusion,
    fase1_evaluar_exclusion,
    fase1_limpiar_inclusion,
    fase1_limpiar_exclusion,
    fase1_reiniciar_evaluacion,
    fase1_sumar_inclusion,
    fase1_sumar_exclusion,
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
                min_value=0.0, max_value=5.0, value=0.1, step=0.1, key="scr_delay"
            )
        with c2:
            skip_evaluated = st.checkbox("Saltar filas ya evaluadas", value=True, key="scr_skip")

    # Keywords editables (nuevo sistema dinámico de términos)
    with st.expander("Configuración de Términos de Búsqueda (Fase 0)", expanded=True):
        kw = cargar_keywords_screening()
        terminos_actuales = kw.get("terminos_busqueda", [])
        # Si no hay términos nuevos pero sí antiguos, mostrarlos para facilitar la migración
        if not terminos_actuales:
            terminos_actuales = (
                kw.get("keywords_colaboracion", [])
                + kw.get("keywords_contexto", [])
                + kw.get("sinonimos_calidad", [])
            )
        st.session_state.setdefault("kw_terminos", "\n".join(terminos_actuales))

        txt_terminos = st.text_area(
            "Términos de búsqueda (uno por línea). Se busca la frase exacta en Título y Abstract.",
            value=st.session_state["kw_terminos"],
            height=250, key="kw_terminos",
            help="Ejemplo: collaboration quality\nco-located\nMMLA",
        )

        terminos_lista = [l.strip() for l in txt_terminos.split("\n") if l.strip()]

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            if st.button("💾 Guardar términos", key="btn_save_kw"):
                nuevo_kw = {
                    "terminos_busqueda": terminos_lista,
                    "keywords_colaboracion": kw.get("keywords_colaboracion", []),
                    "keywords_contexto": kw.get("keywords_contexto", []),
                    "sinonimos_calidad": kw.get("sinonimos_calidad", []),
                }
                guardar_keywords_screening(nuevo_kw)
                st.success(f"Términos guardados ({len(terminos_lista)}).")
        with c2:
            if st.button("🔍 Generar búsqueda", key="btn_run_kw"):
                if not terminos_lista:
                    st.warning("No hay términos para buscar.")
                else:
                    with st.spinner("Buscando términos en Título y Abstract..."):
                        df_result, rep = fase0_busqueda_terminos(df_master, terminos_lista, clasificar=False)
                        st.session_state["master_df"] = df_result
                        st.session_state["screening_f0_df"] = df_result
                        st.session_state["screening_f0_reporte"] = rep
                        exportar_excel_por_etapa(df_result, "fase0", OUTPUT_FOLDER)
                        exportar_resumen_excel(rep, "fase0", OUTPUT_FOLDER)
                    st.success(
                        f"Búsqueda completada — Registros con coincidencias={rep['coincidencias']}, "
                        f"Score máximo={rep['max_score']}"
                    )
                    # Mostrar tabla de frecuencias por término
                    if rep.get("terminos"):
                        st.caption("Frecuencia por término:")
                        freq_df = pd.DataFrame([
                            {"Término": k, "Coincidencias": v}
                            for k, v in rep["terminos"].items()
                        ])
                        st.dataframe(freq_df, use_container_width=True, hide_index=True)
        with c3:
            if st.button("🧹 Limpiar valores", key="btn_clear_kw"):
                if not terminos_lista:
                    st.warning("No hay términos configurados.")
                else:
                    df_cleared = fase0_limpiar_terminos(df_master, terminos_lista)
                    st.session_state["master_df"] = df_cleared
                    st.session_state["screening_f0_df"] = df_cleared
                    st.success("Valores de columnas de términos puestos a 0.")
        with c4:
            if st.button("➕ Sumar score", key="btn_sum_kw"):
                if not terminos_lista:
                    st.warning("No hay términos configurados.")
                else:
                    df_scored = fase0_sumar_score(df_master, terminos_lista)
                    st.session_state["master_df"] = df_scored
                    st.session_state["screening_f0_df"] = df_scored
                    st.success(f"Score recalculado. Máx={df_scored['F0_Score'].max()}")
        with c5:
            if st.button("🔄 Reiniciar y regenerar", key="btn_reset_kw"):
                if not terminos_lista:
                    st.warning("No hay términos configurados.")
                else:
                    with st.spinner("Reiniciando columnas y regenerando búsqueda..."):
                        terminos_guardados = cargar_keywords_screening().get("terminos_busqueda", [])
                        df_clean = fase0_reiniciar_terminos(df_master, terminos_lista, terminos_guardados)
                        df_result, rep = fase0_busqueda_terminos(df_clean, terminos_lista, clasificar=False)
                        st.session_state["master_df"] = df_result
                        st.session_state["screening_f0_df"] = df_result
                        st.session_state["screening_f0_reporte"] = rep
                        exportar_excel_por_etapa(df_result, "fase0", OUTPUT_FOLDER)
                        exportar_resumen_excel(rep, "fase0", OUTPUT_FOLDER)
                    st.success(
                        f"Reinicio completado — Registros con coincidencias={rep['coincidencias']}, "
                        f"Score máximo={rep['max_score']}"
                    )

        st.caption(
            "Nota: Fase 0 no usa LLM, por lo que el 'Delay entre llamadas' no aplica aquí. "
            "El delay solo se usa en F1, F2 y F3 donde se consulta Ollama."
        )

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

    # --- Fase 1 Manual: Inclusión y Exclusión ---
    st.divider()
    st.markdown("### Fase 1: Evaluación por Criterios (LLM)")
    st.caption(
        "La evaluación ordena automáticamente por F0_Score descendente (mayor score primero)."
    )

    # Mostrar criterios activos
    from services.screening import cargar_criterios_dinamicos
    inclusion_cfg, exclusion_cfg = cargar_criterios_dinamicos()
    with st.expander("📋 Ver criterios activos", expanded=False):
        col_inc_info, col_exc_info = st.columns(2)
        with col_inc_info:
            st.markdown(f"**Inclusión ({len(inclusion_cfg)} criterios) — Score 0-2:**")
            for cid, cfg in inclusion_cfg.items():
                st.write(f"- {cid}: {cfg['nombre']}")
        with col_exc_info:
            st.markdown(f"**Exclusión ({len(exclusion_cfg)} criterios) — Score 0-1:**")
            for cid, cfg in exclusion_cfg.items():
                st.write(f"- {cid}: {cfg['nombre']}")

    # Caja para mostrar el ultimo prompt en tiempo real
    prompt_container = st.empty()
    last_prompt_key = "last_llm_prompt"
    if last_prompt_key not in st.session_state:
        st.session_state[last_prompt_key] = "Esperando inicio de evaluacion..."
    prompt_container.text_area(
        "Ultimo prompt enviado al LLM",
        value=st.session_state[last_prompt_key],
        height=250,
        disabled=True,
        label_visibility="collapsed",
    )

    col_inc, col_exc, col_gest = st.columns([1, 1, 1])

    with col_inc:
        if st.button("✅ Evaluar criterios de inclusión", use_container_width=True, key="btn_eval_inc"):
            df_eval = st.session_state.get("master_df", load_master_dataframe())
            if df_eval.empty:
                st.warning("Carga o genera la tabla maestra primero.")
            else:
                progress_inc = st.progress(0.0, text="Evaluando inclusión...")
                log_container_inc = st.empty()
                log_lines_inc = []

                def _cb_inc(current, total):
                    progress_inc.progress(current / total, text=f"Inclusión: {current}/{total}")

                def _log_inc(msg):
                    log_lines_inc.append(msg)
                    log_container_inc.text_area("Log Inclusión", value="\n".join(log_lines_inc[-50:]), height=200, disabled=True, label_visibility="collapsed")

                def _prompt_inc(prompt_text):
                    st.session_state[last_prompt_key] = prompt_text
                    prompt_container.text_area(
                        "Ultimo prompt enviado al LLM",
                        value=prompt_text,
                        height=250,
                        disabled=True,
                        label_visibility="collapsed",
                    )

                with st.spinner("Evaluando criterios de inclusión..."):
                    df_inc, rep_inc = fase1_evaluar_inclusion(
                        df_eval, llm_config, delay=delay, progress_callback=_cb_inc, log_callback=_log_inc, prompt_callback=_prompt_inc, skip_evaluated=skip_evaluated
                    )
                    st.session_state["master_df"] = df_inc
                    st.session_state["screening_f1_df"] = df_inc
                    st.session_state["screening_f1_inc_reporte"] = rep_inc
                    exportar_excel_por_etapa(df_inc, "fase1", OUTPUT_FOLDER)
                st.success(f"Inclusión evaluada — Total inc. máx={df_inc['F1_Inclusion_Total'].max()}")
                progress_inc.empty()

    with col_exc:
        if st.button("❌ Evaluar criterios de exclusión", use_container_width=True, key="btn_eval_exc"):
            df_eval = st.session_state.get("master_df", load_master_dataframe())
            if df_eval.empty:
                st.warning("Carga o genera la tabla maestra primero.")
            else:
                progress_exc = st.progress(0.0, text="Evaluando exclusión...")
                log_container_exc = st.empty()
                log_lines_exc = []

                def _cb_exc(current, total):
                    progress_exc.progress(current / total, text=f"Exclusión: {current}/{total}")

                def _log_exc(msg):
                    log_lines_exc.append(msg)
                    log_container_exc.text_area("Log Exclusión", value="\n".join(log_lines_exc[-50:]), height=200, disabled=True, label_visibility="collapsed")

                def _prompt_exc(prompt_text):
                    st.session_state[last_prompt_key] = prompt_text
                    prompt_container.text_area(
                        "Ultimo prompt enviado al LLM",
                        value=prompt_text,
                        height=250,
                        disabled=True,
                        label_visibility="collapsed",
                    )

                with st.spinner("Evaluando criterios de exclusión..."):
                    df_exc, rep_exc = fase1_evaluar_exclusion(
                        df_eval, llm_config, delay=delay, progress_callback=_cb_exc, log_callback=_log_exc, prompt_callback=_prompt_exc, skip_evaluated=skip_evaluated
                    )
                    st.session_state["master_df"] = df_exc
                    st.session_state["screening_f1_df"] = df_exc
                    st.session_state["screening_f1_exc_reporte"] = rep_exc
                    exportar_excel_por_etapa(df_exc, "fase1", OUTPUT_FOLDER)
                st.success(f"Exclusión evaluada — Total exc. máx={df_exc['F1_Exclusion_Total'].max()}")
                progress_exc.empty()

    with col_gest:
        st.markdown("**Gestión**")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🧹 Limpiar Inc.", use_container_width=True, key="btn_clear_inc"):
                df_eval = st.session_state.get("master_df", load_master_dataframe())
                df_clean = fase1_limpiar_inclusion(df_eval)
                st.session_state["master_df"] = df_clean
                st.session_state["screening_f1_df"] = df_clean
                st.success("Evaluación de inclusión limpiada.")
            if st.button("🧹 Limpiar Exc.", use_container_width=True, key="btn_clear_exc"):
                df_eval = st.session_state.get("master_df", load_master_dataframe())
                df_clean = fase1_limpiar_exclusion(df_eval)
                st.session_state["master_df"] = df_clean
                st.session_state["screening_f1_df"] = df_clean
                st.success("Evaluación de exclusión limpiada.")
        with c2:
            if st.button("➕ Sumar Inc.", use_container_width=True, key="btn_sum_inc"):
                df_eval = st.session_state.get("master_df", load_master_dataframe())
                df_scored = fase1_sumar_inclusion(df_eval)
                st.session_state["master_df"] = df_scored
                st.session_state["screening_f1_df"] = df_scored
                st.success(f"Score de inclusión recalculado. Máx={df_scored['F1_Inclusion_Total'].max()}")
            if st.button("➕ Sumar Exc.", use_container_width=True, key="btn_sum_exc"):
                df_eval = st.session_state.get("master_df", load_master_dataframe())
                df_scored = fase1_sumar_exclusion(df_eval)
                st.session_state["master_df"] = df_scored
                st.session_state["screening_f1_df"] = df_scored
                st.success(f"Score de exclusión recalculado. Máx={df_scored['F1_Exclusion_Total'].max()}")
        with c3:
            if st.button("🔄 Reiniciar F1", use_container_width=True, key="btn_reset_f1"):
                df_eval = st.session_state.get("master_df", load_master_dataframe())
                df_clean = fase1_reiniciar_evaluacion(df_eval)
                st.session_state["master_df"] = df_clean
                st.session_state["screening_f1_df"] = df_clean
                st.success("Todas las columnas F1 eliminadas.")

    # Botón para exportar F1 con hojas separadas
    if st.button("📊 Exportar F1 con hojas Incluidos/Excluidos", type="primary", key="btn_export_f1"):
        df_eval = st.session_state.get("master_df", load_master_dataframe())
        if df_eval.empty:
            st.warning("No hay datos para exportar.")
        else:
            from services.reporting import exportar_fase1_con_hojas
            path = exportar_fase1_con_hojas(df_eval, OUTPUT_FOLDER)
            st.success(f"Excel exportado: {path}")

    # Pipeline automático
    st.divider()
    col_pipe, col_pipe_info = st.columns([1, 3])
    with col_pipe:
        run_pipeline = st.button(
            "Ejecutar Pipeline Automático (F0→F3)",
            type="primary", key="btn_pipeline", use_container_width=True,
        )
    with col_pipe_info:
        st.caption("Ejecuta F0 (keywords) → F1 (inclusión + exclusión) → F2 (dudosos) → F3 (extracción) → Reporte PRISMA")

    if run_pipeline:
        kw_config = cargar_keywords_screening()
        with st.spinner("Pipeline: F0 (pre-filtrado por keywords)..."):
            df_f0, rep_f0 = fase0_prefiltrado(df_master, kw_config)
            st.session_state["screening_f0_df"] = df_f0
            st.session_state["screening_f0_reporte"] = rep_f0
            exportar_excel_por_etapa(df_f0, "fase0", OUTPUT_FOLDER)
            exportar_resumen_excel(rep_f0, "fase0", OUTPUT_FOLDER)
        st.success(f"✅ F0 completado — Pasan={rep_f0['pasan']}, Dudoso={rep_f0['dudosos']}, Excluidos={rep_f0['excluidos']}")

        progress_f1_inc = st.progress(0.0, text="F1-Inclusión: Iniciando...")
        log_container_f1 = st.empty()
        log_lines_f1 = []

        def _callback_f1(current, total):
            progress_f1_inc.progress(current / total, text=f"F1-Inclusión: {current}/{total}")

        def _log_f1(msg):
            log_lines_f1.append(msg)
            log_container_f1.text_area("Log F1", value="\n".join(log_lines_f1[-50:]), height=250, disabled=True, label_visibility="collapsed")

        st.info("⏳ La primera llamada al LLM puede tardar varios minutos mientras Ollama carga el modelo en memoria.")
        with st.spinner("Pipeline: F1-Inclusión (I1-I4)..."):
            df_f1, rep_f1_inc = fase1_evaluar_inclusion(
                df_f0, llm_config, delay=delay, progress_callback=_callback_f1, log_callback=_log_f1, skip_evaluated=skip_evaluated
            )
            st.session_state["screening_f1_df"] = df_f1
            st.session_state["screening_f1_inc_reporte"] = rep_f1_inc
        st.success(f"✅ F1-Inclusión completado — Total inc. máx={df_f1['F1_Inclusion_Total'].max()}")
        progress_f1_inc.empty()

        progress_f1_exc = st.progress(0.0, text="F1-Exclusión: Iniciando...")
        log_container_f1_exc = st.empty()
        log_lines_f1_exc = []

        def _callback_f1_exc(current, total):
            progress_f1_exc.progress(current / total, text=f"F1-Exclusión: {current}/{total}")

        def _log_f1_exc(msg):
            log_lines_f1_exc.append(msg)
            log_container_f1_exc.text_area("Log F1-Exc", value="\n".join(log_lines_f1_exc[-50:]), height=200, disabled=True, label_visibility="collapsed")

        with st.spinner("Pipeline: F1-Exclusión (E1-E9)..."):
            df_f1, rep_f1_exc = fase1_evaluar_exclusion(
                df_f1, llm_config, delay=delay, progress_callback=_callback_f1_exc, log_callback=_log_f1_exc, skip_evaluated=skip_evaluated
            )
            st.session_state["screening_f1_df"] = df_f1
            st.session_state["screening_f1_exc_reporte"] = rep_f1_exc
            exportar_excel_por_etapa(df_f1, "fase1", OUTPUT_FOLDER)
            exportar_resumen_excel({"inclusion": rep_f1_inc, "exclusion": rep_f1_exc}, "fase1", OUTPUT_FOLDER)
        st.success(f"✅ F1-Exclusión completado — Total exc. máx={df_f1['F1_Exclusion_Total'].max()}")
        progress_f1_exc.empty()

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
    fases = [
        ("F0", "screening_f0_df", "screening_f0_reporte"),
        ("F1-Inclusión", "screening_f1_df", "screening_f1_inc_reporte"),
        ("F1-Exclusión", "screening_f1_df", "screening_f1_exc_reporte"),
        ("F2", "screening_f2_df", "screening_f2_reporte"),
        ("F3", "screening_f3_df", "screening_f3_reporte"),
    ]
    for label, key_df, key_rep in fases:
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
