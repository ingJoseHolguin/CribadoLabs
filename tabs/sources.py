"""Pestaña: Fuentes — carga, listado y borrado de archivos por fuente."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from services.bibliographic import INPUT_FOLDER, SUPPORTED_EXTENSIONS
from services.config import load_search_queries, save_search_queries
from services.persistence import MASTER_FILENAME, OUTPUT_FOLDER, load_master_dataframe


SOURCES = ["ACM", "IEEE", "ScienceDirect", "Springer", "Scopus", "WebOfScience"]


def list_source_files():
    rows = []
    for source_dir in sorted(INPUT_FOLDER.iterdir()):
        if not source_dir.is_dir():
            continue
        for filepath in sorted(source_dir.iterdir()):
            if filepath.is_file():
                rows.append(
                    {
                        "Fuente": source_dir.name,
                        "Archivo": filepath.name,
                        "Tipo": filepath.suffix.lower(),
                        "Tamaño KB": round(filepath.stat().st_size / 1024, 2),
                    }
                )
    return pd.DataFrame(rows, columns=["Fuente", "Archivo", "Tipo", "Tamaño KB"])


def save_uploaded_files(source, uploaded_files):
    source_dir = INPUT_FOLDER / source
    source_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for uploaded_file in uploaded_files:
        destination = source_dir / uploaded_file.name
        destination.write_bytes(uploaded_file.getbuffer())
        saved.append(destination)
    return saved


def delete_source_contents(source):
    source_dir = INPUT_FOLDER / source
    if not source_dir.exists() or not source_dir.is_dir():
        return 0
    deleted = 0
    for filepath in source_dir.iterdir():
        if filepath.is_file():
            filepath.unlink()
            deleted += 1
    return deleted


def build_sources_backup_zip():
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        for source_dir in sorted(INPUT_FOLDER.iterdir()):
            if not source_dir.is_dir():
                continue
            for filepath in sorted(source_dir.iterdir()):
                if filepath.is_file():
                    arcname = f"{source_dir.name}/{filepath.name}"
                    zip_file.write(filepath, arcname)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cribadolabs_backup_{timestamp}.zip", buffer.getvalue()


def sources_tab():
    st.subheader("Carga de fuentes de información")
    st.write("Sube archivos por fuente. Cada archivo se guarda dentro de su carpeta en `data/`.")

    backup_name, backup_bytes = build_sources_backup_zip()
    st.download_button(
        "Descargar respaldo ZIP",
        data=backup_bytes,
        file_name=backup_name,
        mime="application/zip",
        use_container_width=True,
    )

    col_left, col_right = st.columns([1, 2], gap="large")

    with col_left:
        source_options = sorted(
            {path.name for path in INPUT_FOLDER.iterdir() if path.is_dir()} | set(SOURCES)
        )
        source = st.selectbox("Fuente", source_options)
        new_source = st.text_input("Nueva fuente", placeholder="Ej. PubMed")
        if new_source.strip():
            source = new_source.strip().replace("/", "-")

        queries = load_search_queries()
        current_query = queries.get(source, "")

        search_query_val = st.text_area(
            "Cadena de búsqueda general (fuente)",
            value=current_query,
            placeholder='Ej. TITLE-ABS-KEY("collaborative learning" AND "multimodal")',
            help="Pega aquí la consulta o sintaxis general utilizada en esta base de datos.",
            height=90,
            key=f"search_query_{source}",
        )

        source_folder = INPUT_FOLDER / source
        files_in_source = (
            sorted(
                [
                    p.name
                    for p in source_folder.glob("*")
                    if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
                ]
            )
            if source_folder.exists()
            else []
        )

        if files_in_source:
            with st.expander(
                f"⚙️ Cadenas específicas por archivo ({len(files_in_source)})",
                expanded=(len(files_in_source) > 1),
            ):
                st.caption(
                    "Si esta fuente se descargó en varias partes o búsquedas divididas (ej. Springer), "
                    "asigna aquí la sub-cadena específica a cada archivo. "
                    "Los archivos sin sub-cadena heredarán la cadena general de la fuente."
                )
                selected_file = st.selectbox(
                    "Archivo a configurar",
                    files_in_source,
                    key=f"sel_file_{source}",
                )
                file_key = f"{source}/{selected_file}"
                current_file_query = queries.get(file_key, queries.get(selected_file, ""))

                file_query_val = st.text_area(
                    f"Sub-cadena para `{selected_file}`",
                    value=current_file_query,
                    placeholder=f"Cadena específica utilizada para generar {selected_file}",
                    height=80,
                    key=f"query_file_{source}_{selected_file}",
                )
                col_f_save, col_f_clear = st.columns([1, 1])
                with col_f_save:
                    if st.button(
                        "💾 Guardar cadena de archivo",
                        key=f"btn_save_file_{source}_{selected_file}",
                        use_container_width=True,
                    ):
                        if file_query_val.strip():
                            queries[file_key] = file_query_val.strip()
                        else:
                            queries.pop(file_key, None)
                            queries.pop(selected_file, None)
                        save_search_queries(queries)
                        st.success(f"Cadena para '{selected_file}' guardada correctamente.")
                        st.rerun()
                with col_f_clear:
                    if current_file_query and st.button(
                        "Restaurar a general",
                        key=f"btn_clear_file_{source}_{selected_file}",
                        use_container_width=True,
                    ):
                        queries.pop(file_key, None)
                        queries.pop(selected_file, None)
                        save_search_queries(queries)
                        st.info(f"'{selected_file}' ahora usará la cadena general.")
                        st.rerun()

        uploaded_files = st.file_uploader(
            "Documentos bibliográficos",
            type=[extension.replace(".", "") for extension in SUPPORTED_EXTENSIONS],
            accept_multiple_files=True,
        )

        col_save_data, col_save_query = st.columns([1, 1])
        with col_save_data:
            if st.button("Guardar en data", type="primary", use_container_width=True):
                if not uploaded_files:
                    st.warning("Selecciona al menos un archivo.")
                else:
                    saved = save_uploaded_files(source, uploaded_files)
                    if search_query_val.strip():
                        queries[source] = search_query_val.strip()
                        save_search_queries(queries)
                    st.success(f"Se guardaron {len(saved)} archivo(s) en data/{source}.")
                    st.rerun()

        with col_save_query:
            if st.button("💾 Guardar solo cadena", use_container_width=True):
                queries[source] = search_query_val.strip()
                save_search_queries(queries)
                st.success(f"Cadena de búsqueda actualizada para {source}.")
                st.rerun()

        with st.expander("Borrar contenido de fuente"):
            files_to_delete = [path for path in (INPUT_FOLDER / source).rglob("*") if path.is_file()]
            st.write(f"Fuente seleccionada: `data/{source}`")
            st.write(f"Archivos encontrados: {len(files_to_delete)}")
            confirm_delete_source = st.checkbox(
                f"Confirmo que quiero borrar los archivos de {source}",
                key=f"confirm_delete_source_{source}",
            )
            if st.button("Borrar fuente", disabled=not confirm_delete_source, use_container_width=True):
                deleted = delete_source_contents(source)
                to_remove = [k for k in queries if k.startswith(f"{source}/")]
                for k in to_remove:
                    queries.pop(k, None)
                save_search_queries(queries)
                st.success(f"Se borraron {deleted} archivo(s) de data/{source}.")
                st.rerun()

    with col_right:
        st.markdown("##### Archivos disponibles por fuente")
        files_df = list_source_files()
        st.dataframe(files_df, use_container_width=True, hide_index=True)

        st.markdown("##### Cadenas de búsqueda registradas")
        queries = load_search_queries()
        if queries:
            queries_rows = []
            for k, v in sorted(queries.items()):
                if not v or not v.strip():
                    continue
                if "/" in k:
                    f_name, a_name = k.split("/", 1)
                    queries_rows.append({
                        "Ámbito": "Archivo específico",
                        "Fuente": f_name,
                        "Archivo": a_name,
                        "Cadena de búsqueda": v,
                    })
                else:
                    queries_rows.append({
                        "Ámbito": "Fuente (general)",
                        "Fuente": k,
                        "Archivo": "(Todos los archivos)",
                        "Cadena de búsqueda": v,
                    })
            if queries_rows:
                df_q = pd.DataFrame(queries_rows).sort_values(by=["Fuente", "Ámbito"], ascending=[True, False])
                st.dataframe(df_q, use_container_width=True, hide_index=True)
            else:
                st.info("No hay cadenas registradas con contenido aún.")
        else:
            st.info("No hay cadenas registradas aún. Ingresa la consulta a la izquierda y pulsa 'Guardar solo cadena'.")

        st.markdown("##### Resumen de registros por fuente")
        master_df = st.session_state.get("master_df")
        if master_df is None or master_df.empty:
            master_file = OUTPUT_FOLDER / MASTER_FILENAME
            if master_file.exists():
                try:
                    master_df = load_master_dataframe(master_file)
                except Exception:
                    master_df = pd.DataFrame()
            else:
                master_df = pd.DataFrame()

        if master_df is not None and not master_df.empty and "Fuente" in master_df.columns:
            total_records = len(master_df)
            counts_series = master_df["Fuente"].value_counts()

            summary_df = pd.DataFrame({
                "Fuente": counts_series.index,
                "Registros": counts_series.values,
                "% del total": [f"{(v / total_records * 100):.1f}%" for v in counts_series.values],
            })

            col_tot, col_sources = st.columns([1, 1])
            col_tot.metric("Total registros consolidados", f"{total_records:,}")
            col_sources.metric("Fuentes con registros", len(summary_df))

            st.dataframe(summary_df, use_container_width=True, hide_index=True)

            if "ArchivoOrigen" in master_df.columns:
                with st.expander("Ver desglose detallado por archivo"):
                    file_counts = (
                        master_df.groupby(["Fuente", "ArchivoOrigen"])
                        .size()
                        .reset_index(name="Registros")
                        .sort_values(by=["Fuente", "Registros"], ascending=[True, False])
                    )
                    st.dataframe(file_counts, use_container_width=True, hide_index=True)
        else:
            st.info(
                "Aún no hay registros consolidados en la tabla maestra. "
                "Ve a la pestaña 'Tabla maestra' y pulsa 'Procesar fuentes' para generarla."
            )
