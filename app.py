from pathlib import Path
from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from bibliographic_processor import (
    INPUT_FOLDER,
    MASTER_FILENAME,
    NORMALIZED_COLUMNS,
    OUTPUT_FOLDER,
    SUPPORTED_EXTENSIONS,
    load_master_dataframe,
    process_folder,
    save_master_dataframe,
)


SOURCES = ["ACM", "IEEE", "ScienceDirect", "Springer", "Scopus", "WebOfScience"]


st.set_page_config(
    page_title="CribadoLabs",
    page_icon="CL",
    layout="wide",
    initial_sidebar_state="expanded",
)


def ensure_workspace():
    INPUT_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)
    for source in SOURCES:
        (INPUT_FOLDER / source).mkdir(parents=True, exist_ok=True)


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
    for path in sorted(source_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
            deleted += 1
        elif path.is_dir():
            path.rmdir()

    return deleted


def build_sources_backup_zip():
    timestamp = datetime.now().strftime("%Y %m %d - %Hh%Mm")
    zip_name = f"respaldo_fuentes_{timestamp}.zip"
    buffer = BytesIO()

    with ZipFile(buffer, "w", ZIP_DEFLATED) as backup_zip:
        for source_dir in sorted(INPUT_FOLDER.iterdir()):
            if not source_dir.is_dir():
                continue

            files = [path for path in sorted(source_dir.rglob("*")) if path.is_file()]
            if not files:
                backup_zip.writestr(f"{source_dir.name}/.gitkeep", "")
                continue

            for filepath in files:
                archive_path = filepath.relative_to(INPUT_FOLDER)
                backup_zip.write(filepath, archive_path.as_posix())

        master_file = OUTPUT_FOLDER / MASTER_FILENAME
        if master_file.exists():
            backup_zip.write(master_file, MASTER_FILENAME)

    buffer.seek(0)
    return zip_name, buffer.getvalue()


def metric_cards(df):
    total = len(df)
    sources = df["Fuente"].nunique() if "Fuente" in df else 0
    years = df["Año"].dropna() if "Año" in df else pd.Series(dtype="float")
    min_year = int(years.min()) if not years.empty else "-"
    max_year = int(years.max()) if not years.empty else "-"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Registros", total)
    col2.metric("Fuentes", sources)
    col3.metric("Año inicial", min_year)
    col4.metric("Año final", max_year)


def sources_tab():
    st.subheader("Carga de fuentes de información")
    st.write(
        "Sube archivos por fuente. Cada archivo se guarda dentro de su carpeta en `data/`."
    )

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

        uploaded_files = st.file_uploader(
            "Documentos bibliográficos",
            type=[extension.replace(".", "") for extension in SUPPORTED_EXTENSIONS],
            accept_multiple_files=True,
        )

        if st.button("Guardar en data", type="primary", use_container_width=True):
            if not uploaded_files:
                st.warning("Selecciona al menos un archivo.")
            else:
                saved = save_uploaded_files(source, uploaded_files)
                st.success(f"Se guardaron {len(saved)} archivo(s) en data/{source}.")

        with st.expander("Borrar contenido de fuente"):
            files_in_source = [
                path for path in (INPUT_FOLDER / source).rglob("*") if path.is_file()
            ]
            st.write(f"Fuente seleccionada: `data/{source}`")
            st.write(f"Archivos encontrados: {len(files_in_source)}")
            confirm_delete_source = st.checkbox(
                f"Confirmo que quiero borrar los archivos de {source}",
                key=f"confirm_delete_source_{source}",
            )

            if st.button(
                "Borrar fuente",
                disabled=not confirm_delete_source,
                use_container_width=True,
            ):
                deleted = delete_source_contents(source)
                st.success(f"Se borraron {deleted} archivo(s) de data/{source}.")
                st.rerun()

    with col_right:
        files_df = list_source_files()
        st.dataframe(files_df, use_container_width=True, hide_index=True)


def processing_tab():
    st.subheader("Procesar y editar tabla maestra")

    col_run, col_load, col_save = st.columns([1, 1, 1])
    with col_run:
        run_processing = st.button("Procesar fuentes", type="primary", use_container_width=True)
    with col_load:
        load_existing = st.button("Cargar Excel existente", use_container_width=True)
    with col_save:
        save_edits = st.button("Guardar edición", use_container_width=True)

    if run_processing:
        with st.spinner("Leyendo fuentes y normalizando registros..."):
            df, errors = process_folder(INPUT_FOLDER)
            st.session_state["master_df"] = df
            st.session_state["processing_errors"] = errors
            output_file = save_master_dataframe(df)
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
    st.session_state["master_df"] = edited_df

    if save_edits:
        output_file = save_master_dataframe(edited_df)
        st.success(f"Cambios guardados en {output_file}.")

    with st.expander("Limpiar tabla maestra"):
        st.write(
            "Esto vacía la tabla visible y guarda un Excel maestro sin registros."
        )
        confirm_clear_master = st.checkbox(
            "Confirmo que quiero limpiar la tabla maestra",
            key="confirm_clear_master",
        )

        if st.button(
            "Limpiar tabla maestra",
            disabled=not confirm_clear_master,
            use_container_width=True,
        ):
            empty_df = pd.DataFrame(columns=NORMALIZED_COLUMNS)
            st.session_state["master_df"] = empty_df
            st.session_state["processing_errors"] = []
            output_file = save_master_dataframe(empty_df)
            st.success(f"Tabla maestra limpia guardada en {output_file}.")
            st.rerun()

    errors = st.session_state.get("processing_errors", [])
    if errors:
        with st.expander("Errores de procesamiento"):
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)


def criteria_tab():
    st.subheader("Criterios de selección")
    st.write(
        "Aquí se preparará la iteración por fila. Cada criterio creará una nueva columna escalable."
    )

    if "criteria" not in st.session_state:
        st.session_state["criteria"] = []

    criterion = st.text_input("Nuevo criterio", placeholder="Ej. Incluye población adulta")
    col_add, col_apply = st.columns([1, 1])

    with col_add:
        if st.button("Añadir criterio", use_container_width=True):
            if criterion.strip():
                st.session_state["criteria"].append(criterion.strip())
                st.success("Criterio añadido.")

    with col_apply:
        if st.button("Crear columnas en tabla", use_container_width=True):
            df = st.session_state.get("master_df", load_master_dataframe())
            for item in st.session_state["criteria"]:
                column_name = f"Criterio: {item}"
                if column_name not in df.columns:
                    df[column_name] = ""
            st.session_state["master_df"] = df
            st.success("Columnas de criterios listas para edición.")

    if st.session_state["criteria"]:
        st.table(pd.DataFrame({"Criterio": st.session_state["criteria"]}))


def translation_tab():
    st.subheader("Traducción de tabla")
    st.write(
        "Espacio reservado para traducir campos como título, abstract y keywords dentro de la tabla."
    )

    df = st.session_state.get("master_df", load_master_dataframe())
    selected_columns = st.multiselect(
        "Columnas a traducir",
        [column for column in df.columns if column in NORMALIZED_COLUMNS],
        default=[column for column in ["Titulo", "Abstract", "Keywords"] if column in df.columns],
    )
    target_language = st.selectbox("Idioma destino", ["Español", "Inglés", "Portugués"])
    st.info(
        f"Próximo paso: conectar un traductor local/gratuito o API opcional para {len(selected_columns)} columna(s) hacia {target_language}."
    )


def main():
    ensure_workspace()

    st.title("CribadoLabs")
    st.caption("MVP para cargar fuentes, consolidar registros y preparar cribado académico.")

    with st.sidebar:
        st.header("Arquitectura")
        st.write("1. Cargar fuentes")
        st.write("2. Procesar y editar")
        st.write("3. Añadir criterios")
        st.write("4. Traducir contenido")

    tab_sources, tab_processing, tab_criteria, tab_translation = st.tabs(
        [
            "Fuentes",
            "Tabla maestra",
            "Criterios",
            "Traducción",
        ]
    )

    with tab_sources:
        sources_tab()
    with tab_processing:
        processing_tab()
    with tab_criteria:
        criteria_tab()
    with tab_translation:
        translation_tab()


if __name__ == "__main__":
    main()
