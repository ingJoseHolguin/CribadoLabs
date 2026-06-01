"""Pestaña: Fuentes — carga, listado y borrado de archivos por fuente."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from services.bibliographic import INPUT_FOLDER, SUPPORTED_EXTENSIONS


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
            files_in_source = [path for path in (INPUT_FOLDER / source).rglob("*") if path.is_file()]
            st.write(f"Fuente seleccionada: `data/{source}`")
            st.write(f"Archivos encontrados: {len(files_in_source)}")
            confirm_delete_source = st.checkbox(
                f"Confirmo que quiero borrar los archivos de {source}",
                key=f"confirm_delete_source_{source}",
            )
            if st.button("Borrar fuente", disabled=not confirm_delete_source, use_container_width=True):
                deleted = delete_source_contents(source)
                st.success(f"Se borraron {deleted} archivo(s) de data/{source}.")
                st.rerun()

    with col_right:
        files_df = list_source_files()
        st.dataframe(files_df, use_container_width=True, hide_index=True)
