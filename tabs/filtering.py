"""Pestaña: Filtrado (PRISMA) — aplicación de umbrales de inclusión/exclusión."""

from pathlib import Path

import pandas as pd
import streamlit as st

from services.persistence import load_master_dataframe, save_master_dataframe

OUTPUT_FOLDER = Path("output")
MASTER_FILENAME = "scoping_master.xlsx"


def safe_save_dataframe(df_to_save, filename):
    try:
        return save_master_dataframe(df_to_save, filename=filename)
    except PermissionError:
        st.toast(f"⚠️ No se pudo guardar en Excel. Por favor, cierra el archivo {filename} si lo tienes abierto.", icon="⚠️")
        return OUTPUT_FOLDER / filename


def filtering_tab():
    st.subheader("Filtrado de Flujo (PRISMA)")
    st.write("Crea subtablas a partir de la tabla maestra aplicando criterios de inclusión y exclusión.")

    df = st.session_state.get("master_df", load_master_dataframe())
    criteria = st.session_state.get("criteria", [])

    if df.empty:
        st.warning("Carga o procesa la tabla maestra antes de realizar el filtrado.")
        return

    inclusion_criteria = [c for c in criteria if c.get("type", "inclusion") == "inclusion"]
    exclusion_criteria = [c for c in criteria if c.get("type", "inclusion") == "exclusion"]

    if not criteria:
        st.warning("Debes definir criterios en la pestaña 'Criterios' antes de filtrar.")
        return

    st.markdown("### 1. Configuración de Inclusión")
    if not inclusion_criteria:
        st.info("No hay criterios de inclusión definidos.")
        inc_threshold = 4
        inc_rule = "Todos"
        apply_inc = []
    else:
        apply_inc = st.multiselect(
            "Criterios de Inclusión a aplicar",
            options=[c.get("text", "") for c in inclusion_criteria],
            default=[c.get("text", "") for c in inclusion_criteria],
            key="filtering_apply_inc"
        )
        col_inc_thresh, col_inc_rule = st.columns([1, 1])
        with col_inc_thresh:
            inc_threshold = st.slider(
                "Umbral de puntuación mínima para inclusión",
                min_value=-3,
                max_value=12,
                value=4,
                help="El artículo debe tener un puntaje total mayor o igual a este valor para ser incluido. (Por defecto 4).",
                key="filtering_inc_threshold"
            )
        with col_inc_rule:
            inc_rule = st.radio(
                "Regla de Inclusión",
                options=["Todos", "Al menos uno"],
                help="Todos: debe cumplir con cada criterio de inclusión seleccionado. Al menos uno: debe cumplir con al menos uno.",
                key="filtering_inc_rule"
            )

    st.markdown("### 2. Configuración de Exclusión")
    if not exclusion_criteria:
        st.info("No hay criterios de exclusión definidos.")
        exc_threshold = 4
        apply_exc = []
    else:
        apply_exc = st.multiselect(
            "Criterios de Exclusión a aplicar",
            options=[c.get("text", "") for c in exclusion_criteria],
            default=[c.get("text", "") for c in exclusion_criteria],
            key="filtering_apply_exc"
        )
        exc_threshold = st.slider(
            "Umbral de puntuación mínima para exclusión",
            min_value=-3,
            max_value=12,
            value=4,
            help="Si un artículo obtiene un puntaje para un criterio de exclusión mayor o igual a este valor, se considerará que CUMPLE con la exclusión y será DESCARTADO. (Por defecto 4).",
            key="filtering_exc_threshold"
        )

    st.markdown("---")

    if st.button("Ejecutar Cribado y Generar Tablas", type="primary", use_container_width=True):
        total_initial = len(df)
        df_included = df.copy()

        # 1. Aplicar filtro de Inclusión
        if apply_inc:
            inc_conditions = []
            for item in apply_inc:
                idx = next((i for i, c in enumerate(criteria, start=1) if c.get("text") == item), None)
                if idx is not None:
                    col_total = f"C{idx} Total"
                    if col_total in df_included.columns:
                        cond = pd.to_numeric(df_included[col_total], errors="coerce").fillna(0) >= inc_threshold
                        inc_conditions.append(cond)

            if inc_conditions:
                if inc_rule == "Todos":
                    passed_inc = inc_conditions[0]
                    for cond in inc_conditions[1:]:
                        passed_inc = passed_inc & cond
                else:
                    passed_inc = inc_conditions[0]
                    for cond in inc_conditions[1:]:
                        passed_inc = passed_inc | cond
                df_included = df_included[passed_inc].copy()

        total_included = len(df_included)

        # 2. Aplicar filtro de Exclusión (sobre los que pasaron la inclusión)
        df_final = df_included.copy()
        if apply_exc:
            exc_conditions = []
            for item in apply_exc:
                idx = next((i for i, c in enumerate(criteria, start=1) if c.get("text") == item), None)
                if idx is not None:
                    col_total = f"C{idx} Total"
                    if col_total in df_final.columns:
                        cond = pd.to_numeric(df_final[col_total], errors="coerce").fillna(0) < exc_threshold
                        exc_conditions.append(cond)

            if exc_conditions:
                survived = exc_conditions[0]
                for cond in exc_conditions[1:]:
                    survived = survived & cond
                df_final = df_final[survived].copy()

        total_final = len(df_final)
        excluded_by_exc = total_included - total_final

        safe_save_dataframe(df_included, "scoping_included.xlsx")
        safe_save_dataframe(df_final, "scoping_final.xlsx")

        st.session_state["filtering_results"] = {
            "initial": total_initial,
            "included": total_included,
            "excluded_inc": total_initial - total_included,
            "excluded_exc": excluded_by_exc,
            "final": total_final
        }
        st.success("¡Filtrado completado con éxito!")

    results = st.session_state.get("filtering_results", None)
    if results:
        st.markdown("### Resumen del Flujo PRISMA")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("1. Iniciales (Maestra)", results["initial"])
        col2.metric("2. Pasan Inclusión", results["included"], f"-{results['excluded_inc']} excl.")
        col3.metric("3. Descartados por Exclusión", results["excluded_exc"], delta_color="inverse")
        col4.metric("4. Finales", results["final"])

        st.markdown("### Descargar Resultados")
        col_m, col_i, col_f = st.columns(3)

        with col_m:
            master_path = OUTPUT_FOLDER / MASTER_FILENAME
            if master_path.exists():
                with open(master_path, "rb") as f:
                    st.download_button(
                        label="📥 Descargar Tabla Maestra",
                        data=f.read(),
                        file_name="scoping_master.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
        with col_i:
            inc_path = OUTPUT_FOLDER / "scoping_included.xlsx"
            if inc_path.exists():
                with open(inc_path, "rb") as f:
                    st.download_button(
                        label="📥 Descargar Incluidos (Etapa 1)",
                        data=f.read(),
                        file_name="scoping_included.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
        with col_f:
            final_path = OUTPUT_FOLDER / "scoping_final.xlsx"
            if final_path.exists():
                with open(final_path, "rb") as f:
                    st.download_button(
                        label="📥 Descargar Finales (Etapa 2)",
                        data=f.read(),
                        file_name="scoping_final.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
