"""Pestaña: Traducción — traducción offline de metadatos y PDFs."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from services.persistence import load_master_dataframe
from services.translator import get_argos_translator, translate_pdf_with_fitz_and_md
from tabs import safe_save_master_dataframe


def translation_tab():
    st.subheader("Traducción Offline (Argos Translate)")
    st.write("Traduce y procesa metadatos de la tabla maestra o archivos PDF de forma 100% offline.")

    df = st.session_state.get("master_df", load_master_dataframe())

    st.markdown("### Configuración del Motor de Traducción")
    device_type = st.radio(
        "Dispositivo de procesamiento (Aceleración GPU):",
        options=["auto", "cpu", "cuda"],
        index=0,
        help=(
            "auto: Detecta y usa GPU si está disponible.\n"
            "cpu: Usa el procesador principal (más lento pero compatible con todo).\n"
            "cuda: Fuerza el uso de GPU NVIDIA (requiere drivers CUDA instalados)."
        ),
        horizontal=True
    )

    tab_metadata, tab_pdf = st.tabs(["Traducción de Tabla (Excel)", "Traducción de Archivos PDF"])

    with tab_metadata:
        st.markdown("### Traducción de Títulos y Abstracts (Excel)")
        st.write(
            "Traduce los campos **Titulo** y **Abstract** de la tabla maestra al Español. "
            "Los resultados se guardarán en las columnas **Titulo ES** y **Abstract ES** respectivamente."
        )

        if df.empty:
            st.warning("No hay registros en la tabla maestra para traducir.")
        else:
            solo_vacias = st.checkbox("Traducir solo filas sin traducción previa", value=True)

            def is_empty_value(val):
                if pd.isna(val):
                    return True
                s = str(val).strip()
                return s == "" or s.lower() in ("nan", "none", "<none>")

            if st.button("Ejecutar traducción al Español", type="primary", key="btn_run_translate"):
                df["Titulo ES"] = df["Titulo ES"].astype(object)
                df["Abstract ES"] = df["Abstract ES"].astype(object)

                if solo_vacias:
                    tit_empty = df["Titulo ES"].apply(is_empty_value)
                    abs_empty = df["Abstract ES"].apply(is_empty_value)
                    rows_to_translate = df[tit_empty | abs_empty]
                else:
                    rows_to_translate = df

                total_rows = len(rows_to_translate)
                if total_rows == 0:
                    st.success("¡Todos los registros ya cuentan con su respectiva traducción!")
                else:
                    with st.status("Cargando motor de traducción offline...", expanded=True) as status:
                        try:
                            status.write("Inicializando Argos Translate (puede tardar en descargar el modelo si es la primera vez)...")
                            translator, effective_device = get_argos_translator("en", "es", device=device_type)
                            if effective_device == "cpu" and device_type in ("auto", "cuda"):
                                st.warning("⚠️ La aceleración GPU (CUDA) no está disponible o le faltan dependencias del sistema. Cambiando a traducción por CPU de forma automática.")
                            if not translator:
                                status.update(label="Error al inicializar el traductor", state="error")
                                st.error("No se pudo cargar o descargar el paquete de idioma Inglés -> Español.")
                                return
                            status.update(label="Motor de traducción cargado correctamente.", state="complete")
                        except Exception as e:
                            status.update(label="Error de inicialización", state="error")
                            st.error(f"Ocurrió un error al cargar el traductor: {e}")
                            return

                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    translated_count = 0

                    for idx, row in rows_to_translate.iterrows():
                        status_text.text(f"Traduciendo fila {translated_count + 1} de {total_rows}...")

                        titulo_original = row.get("Titulo", "")
                        current_translated_title = df.at[idx, "Titulo ES"]
                        if not solo_vacias or is_empty_value(current_translated_title):
                            if not is_empty_value(titulo_original):
                                try:
                                    df.at[idx, "Titulo ES"] = translator.translate(str(titulo_original).strip())
                                except Exception as ex:
                                    df.at[idx, "Titulo ES"] = f"Error: {ex}"
                            else:
                                df.at[idx, "Titulo ES"] = ""

                        abstract_original = row.get("Abstract", "")
                        current_translated_abstract = df.at[idx, "Abstract ES"]
                        if not solo_vacias or is_empty_value(current_translated_abstract):
                            if not is_empty_value(abstract_original):
                                try:
                                    df.at[idx, "Abstract ES"] = translator.translate(str(abstract_original).strip())
                                except Exception as ex:
                                    df.at[idx, "Abstract ES"] = f"Error: {ex}"
                            else:
                                df.at[idx, "Abstract ES"] = ""

                        translated_count += 1
                        progress_bar.progress(translated_count / total_rows)

                    status_text.text("Guardando cambios en scoping_master.xlsx...")
                    st.session_state["master_df"] = df
                    safe_save_master_dataframe(df)
                    progress_bar.empty()
                    status_text.empty()
                    st.success(f"¡Traducción completada con éxito! Se procesaron {total_rows} filas.")
                    st.rerun()

            st.markdown("### Vista previa de Traducciones")
            cols_to_show = ["Fuente", "Titulo", "Titulo ES", "Abstract", "Abstract ES"]
            existing_show_cols = [c for c in cols_to_show if c in df.columns]
            st.dataframe(df[existing_show_cols].head(10), use_container_width=True)

    with tab_pdf:
        st.markdown("### Traducción por Lote de PDFs (Preservando Imágenes/Gráficos)")
        st.write(
            "Carga archivos PDF en inglés. El sistema extraerá el texto, lo traducirá al español "
            "y generará nuevos archivos PDF sobreescribiendo el texto en la misma posición (coordenadas). "
            "Esto mantiene los gráficos, imágenes y la distribución original del documento intacta."
        )

        uploaded_files = st.file_uploader(
            "Subir archivos PDF (en inglés)",
            type=["pdf"],
            accept_multiple_files=True,
            key="pdf_uploader"
        )

        # Boton de limpieza visible siempre (no solo cuando hay traducciones)
        espanol_dir = Path("output/pdf_traducciones/espanol")
        ingles_dir = Path("output/pdf_traducciones/ingles")
        if espanol_dir.exists() and any(espanol_dir.glob("*.pdf")):
            if st.button("🗑️ Limpiar PDFs traducidos anteriores", use_container_width=True, key="btn_clear_pdf_translations"):
                import shutil
                shutil.rmtree("output/pdf_traducciones", ignore_errors=True)
                st.success("Carpeta de traducciones limpiada.")
                st.rerun()

        if uploaded_files:
            st.write(f"**Archivos cargados ({len(uploaded_files)}):**")
            files_data = []
            for f in uploaded_files:
                files_data.append({"Nombre": f.name, "Tamaño (KB)": round(len(f.getvalue()) / 1024, 2)})
            st.dataframe(pd.DataFrame(files_data), use_container_width=True)

            skip_translated = st.checkbox("Saltar PDFs ya traducidos", value=True, key="skip_pdf_translated")

            if st.button("Iniciar traducción de PDFs", type="primary", key="btn_run_translate_pdf"):
                ingles_dir.mkdir(parents=True, exist_ok=True)
                espanol_dir.mkdir(parents=True, exist_ok=True)

                with st.status("Cargando motor de traducción offline...", expanded=True) as status:
                    try:
                        status.write("Inicializando Argos Translate...")
                        translator, effective_device = get_argos_translator("en", "es", device=device_type)
                        if effective_device == "cpu" and device_type in ("auto", "cuda"):
                            st.warning("⚠️ La aceleración GPU (CUDA) no está disponible. Cambiando a traducción por CPU de forma automática.")
                        if not translator:
                            status.update(label="Error al inicializar el traductor", state="error")
                            st.error("No se pudo cargar o descargar el paquete de idioma Inglés -> Español.")
                            return
                        status.update(label="Motor de traducción cargado correctamente.", state="complete")
                    except Exception as e:
                        status.update(label="Error de inicialización", state="error")
                        st.error(f"Ocurrió un error al cargar el traductor: {e}")
                        return

                progress_bar = st.progress(0)
                status_text = st.empty()

                files_to_process = []
                for f in uploaded_files:
                    filename = f.name
                    espanol_pdf_path = espanol_dir / filename
                    if skip_translated and espanol_pdf_path.exists():
                        continue
                    files_to_process.append(f)

                total_files = len(files_to_process)
                skipped = len(uploaded_files) - total_files

                if skipped > 0:
                    st.info(f"⏭️ {skipped} archivo(s) ya traducido(s) — se omite(n).")

                if total_files == 0:
                    st.success("¡Todos los PDFs subidos ya están traducidos!")
                else:
                    for f_idx, f in enumerate(files_to_process):
                        filename = f.name
                        ingles_path = ingles_dir / filename
                        with open(ingles_path, "wb") as out_f:
                            out_f.write(f.getvalue())

                        espanol_pdf_path = espanol_dir / filename
                        espanol_md_path = espanol_dir / Path(filename).with_suffix(".md").name
                        status_text.write(f"⏳ Procesando archivo {f_idx + 1}/{total_files}: **{filename}**...")

                        try:
                            def page_callback(page_num, total_pages):
                                status_text.write(f"⏳ Traduciendo **{filename}** | Página {page_num + 1}/{total_pages}...")

                            translate_pdf_with_fitz_and_md(ingles_path, espanol_pdf_path, espanol_md_path, translator, page_callback)
                        except Exception as ex:
                            st.error(f"❌ Error al traducir {filename}: {ex}")

                        progress_bar.progress((f_idx + 1) / total_files)

                progress_bar.empty()
                status_text.empty()
                st.success("¡Proceso de traducción de PDFs finalizado!")
                st.rerun()

        espanol_dir = Path("output/pdf_traducciones/espanol")
        if espanol_dir.exists() and any(espanol_dir.glob("*.pdf")):
            st.markdown("---")
            st.markdown("### Descargar Archivos Traducidos")
            translated_files = list(espanol_dir.glob("*"))
            files_list = []
            for f in translated_files:
                files_list.append({
                    "Archivo": f.name,
                    "Tipo": "PDF" if f.suffix.lower() == ".pdf" else "Markdown (Texto)",
                    "Tamaño (KB)": round(f.stat().st_size / 1024, 2)
                })
            st.dataframe(pd.DataFrame(files_list), use_container_width=True)

            try:
                zip_buffer = BytesIO()
                with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as zip_file:
                    for f in translated_files:
                        zip_file.write(f, f.name)

                st.download_button(
                    label="📥 Descargar todo en un archivo ZIP",
                    data=zip_buffer.getvalue(),
                    file_name="pdfs_traducidos_espanol.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            except Exception as zip_ex:
                st.error(f"Error al preparar el ZIP de descarga: {zip_ex}")
