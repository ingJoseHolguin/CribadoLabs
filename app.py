from pathlib import Path
from datetime import datetime
from io import BytesIO
import json
import re
import urllib.error
import urllib.request
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


def safe_save_master_dataframe(df_to_save):
    try:
        return save_master_dataframe(df_to_save)
    except PermissionError:
        st.toast("⚠️ No se pudo guardar en Excel. Por favor, cierra el archivo master si lo tienes abierto.", icon="⚠️")
        return OUTPUT_FOLDER / MASTER_FILENAME


SOURCES = ["ACM", "IEEE", "ScienceDirect", "Springer", "Scopus", "WebOfScience"]
TOTAL_SCORE_COLUMN = "Total Score"
CONFIG_FOLDER = Path("config")
LLM_CONFIG_FILE = CONFIG_FOLDER / "llm_config.json"
CRITERIA_FILE = CONFIG_FOLDER / "criteria.json"


st.set_page_config(
    page_title="CribadoLabs",
    page_icon="CL",
    layout="wide",
    initial_sidebar_state="expanded",
)


def ensure_workspace():
    INPUT_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)
    CONFIG_FOLDER.mkdir(exist_ok=True)
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
            output_file = safe_save_master_dataframe(df)
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
    update_total_score(edited_df)
    st.session_state["master_df"] = edited_df

    if save_edits:
        update_total_score(edited_df)
        output_file = safe_save_master_dataframe(edited_df)
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
            output_file = safe_save_master_dataframe(empty_df)
            st.success(f"Tabla maestra limpia guardada en {output_file}.")
            st.rerun()

    errors = st.session_state.get("processing_errors", [])
    if errors:
        with st.expander("Errores de procesamiento"):
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)


def criteria_dataframe():
    criteria = st.session_state.get("criteria", [])
    return pd.DataFrame(
        [
            {"ID": f"C{index}", "Criterio": criterion}
            for index, criterion in enumerate(criteria, start=1)
        ]
    )


def score_columns(df):
    return [
        column
        for column in df.columns
        if re.match(r"^Criterio C\d+ Score:", column)
    ]


def update_total_score(df):
    columns = score_columns(df)
    if not columns:
        df[TOTAL_SCORE_COLUMN] = 0
        return df

    numeric_scores = df[columns].apply(pd.to_numeric, errors="coerce").fillna(0)
    df[TOTAL_SCORE_COLUMN] = numeric_scores.sum(axis=1).astype(int)
    return df


def sync_criteria_columns():
    df = st.session_state.get("master_df", load_master_dataframe())
    criteria = st.session_state.get("criteria", [])
    existing_notes = {}
    existing_scores = {}

    for column in df.columns:
        match = re.match(r"^Criterio C\d+ (Respuesta|Score): (.+)$", column)
        if not match:
            continue

        column_type, criterion_text = match.groups()
        if column_type == "Respuesta":
            existing_notes[criterion_text] = df[column].copy()
        else:
            existing_scores[criterion_text] = df[column].copy()

    base_columns = [
        column
        for column in df.columns
        if not column.startswith("Criterio C") and column != TOTAL_SCORE_COLUMN
    ]
    df = df[base_columns].copy()

    for index, criterion in enumerate(criteria, start=1):
        response_column = f"Criterio C{index} Respuesta: {criterion}"
        score_column = f"Criterio C{index} Score: {criterion}"
        df[response_column] = existing_notes.get(criterion, "")
        df[response_column] = df[response_column].astype("object")
        if criterion in existing_scores:
            df[score_column] = pd.to_numeric(
                existing_scores[criterion], errors="coerce"
            ).fillna(0)
        else:
            df[score_column] = 0

    update_total_score(df)
    st.session_state["master_df"] = df
    safe_save_master_dataframe(df)


def ollama_chat(endpoint, model, prompt):
    endpoint = endpoint.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": 4096,
            "temperature": 0.0,
            "top_p": 0.0,
            "repeat_penalty": 1.0,
            "num_predict": 256,
            "stop": ["}", "```", "\n\n"]
        },
    }
    request = urllib.request.Request(
        f"{endpoint}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))

    return body.get("message", {}).get("content", "")


def extract_json_response(text):
    text = text.strip()
    if text.startswith("{") and not text.endswith("}"):
        text += "}"

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            match_open = re.search(r"\{.*", text, flags=re.DOTALL)
            if match_open:
                try:
                    return json.loads(match_open.group(0) + "}")
                except json.JSONDecodeError:
                    pass
            raise ValueError("La respuesta del LLM no contiene JSON.")
        return json.loads(match.group(0))


def build_criterion_prompt(title, abstract, criterion_id, criterion):
    return f"""
Evaluate a bibliographic record against a selection criterion.

Return ONLY valid JSON, no markdown, no additional text.

Scale:
0 = does not meet.
1 = meets it indirectly or it is only mentioned.
2 = has a clear relationship with the criterion.
3 = meets it exactly.

Required JSON:
{{
  "criterio_id": "{criterion_id}",
  "score": 0,
  "respuesta": "Brief explanation of why it meets or does not meet the criterion."
}}

Criterion:
{criterion}

Title:
{title}

Abstract:
{abstract}
""".strip()


def evaluate_row_criterion(endpoint, model, title, abstract, criterion_id, criterion):
    prompt = build_criterion_prompt(title, abstract, criterion_id, criterion)
    raw_response = ollama_chat(endpoint, model, prompt)
    parsed = extract_json_response(raw_response)
    score = int(parsed.get("score", 0))
    score = max(0, min(3, score))

    return {
        "score": score,
        "respuesta": str(parsed.get("respuesta", "")).strip(),
        "raw": raw_response,
    }


def load_llm_config():
    if not LLM_CONFIG_FILE.exists():
        return {"endpoint": "http://localhost:11434", "model": "llama3.1"}

    try:
        with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return {"endpoint": "http://localhost:11434", "model": "llama3.1"}

    return {
        "endpoint": config.get("endpoint", "http://localhost:11434"),
        "model": config.get("model", "llama3.1"),
    }


def save_llm_config(endpoint, model):
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(LLM_CONFIG_FILE, "w", encoding="utf-8") as config_file:
        json.dump({"endpoint": endpoint, "model": model}, config_file, indent=2)


def load_criteria():
    if not CRITERIA_FILE.exists():
        return []

    try:
        with open(CRITERIA_FILE, "r", encoding="utf-8") as config_file:
            criteria = json.load(config_file)
            if isinstance(criteria, list):
                return criteria
            return []
    except (OSError, json.JSONDecodeError):
        return []


def save_criteria(criteria):
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(CRITERIA_FILE, "w", encoding="utf-8") as config_file:
        json.dump(criteria, config_file, indent=2, ensure_ascii=False)


@st.cache_data(ttl=10, show_spinner=False)
def fetch_ollama_models(endpoint):
    try:
        endpoint = endpoint.rstrip("/")
        request = urllib.request.Request(f"{endpoint}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        return [model["name"] for model in body.get("models", [])]
    except Exception:
        return []


def llm_settings_tab():
    st.subheader("LLM local/API")
    st.write(
        "Configura un endpoint compatible con Ollama para evaluar cada fila sin conservar contexto global."
    )

    llm_config = load_llm_config()
    st.session_state.setdefault("ollama_endpoint", llm_config["endpoint"])
    st.session_state.setdefault("ollama_model", llm_config["model"])

    col_endpoint, col_model = st.columns([2, 1])
    with col_endpoint:
        endpoint = st.text_input(
            "URL o IP con puerto",
            value=st.session_state["ollama_endpoint"],
            placeholder="http://localhost:11434",
        )
    
    available_models = fetch_ollama_models(endpoint.strip())
    
    with col_model:
        if available_models:
            current_model = st.session_state["ollama_model"]
            default_index = available_models.index(current_model) if current_model in available_models else 0
            model = st.selectbox(
                "Modelo",
                options=available_models,
                index=default_index,
            )
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
            save_llm_config(
                st.session_state["ollama_endpoint"],
                st.session_state["ollama_model"],
            )
            st.success(f"Configuración guardada en {LLM_CONFIG_FILE}.")

    with col_test:
        test_connection = st.button("Probar conexión", use_container_width=True)

    if test_connection:
        with st.spinner("Conectando con Ollama (esto puede tardar si el modelo se está cargando)..."):
            try:
                response = ollama_chat(
                    st.session_state["ollama_endpoint"],
                    st.session_state["ollama_model"],
                    'Responde solamente {"ok": true}',
                )
                st.success("Conexión recibida exitosamente.")
                st.code(response, language="json")
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
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

    sync_criteria_columns()
    df = st.session_state["master_df"]
    update_total_score(df)

    criterion_options = {
        f"C{index}: {criterion}": (index, criterion)
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
    skip_evaluated = st.checkbox("Saltar criterios ya evaluados", value=True, help="Si marcas esto, el LLM solo evaluará las celdas que estén vacías para no repetir trabajo.")

    if st.button("Ejecutar evaluación LLM", type="primary", use_container_width=True):
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
                response_column = f"Criterio {criterion_id} Respuesta: {criterion}"
                score_column = f"Criterio {criterion_id} Score: {criterion}"

                if skip_evaluated:
                    existing_response = df.at[row_position, response_column]
                    if pd.notna(existing_response) and str(existing_response).strip() != "":
                        completed += 1
                        progress_text = f"Progreso: {completed}/{total_tasks} evaluaciones"
                        progress.progress(completed / total_tasks, text=progress_text)
                        
                        log_entry = f"⏭️ Fila {row_position + 1} | {criterion_id} -> Ya evaluado (omitido)\n\n"
                        log_text += log_entry
                        log_container.text_area("Registro", value=log_text, height=300, disabled=True, label_visibility="collapsed")
                        continue

                status.write(f"Evaluando fila {row_position + 1}, {criterion_id}...")

                try:
                    result = evaluate_row_criterion(
                        st.session_state["ollama_endpoint"],
                        st.session_state["ollama_model"],
                        title,
                        abstract,
                        criterion_id,
                        criterion,
                    )
                    score = result["score"]
                    respuesta = result["respuesta"]
                    
                    df.at[row_position, response_column] = respuesta
                    df.at[row_position, score_column] = score
                    
                    log_entry = f"✅ Fila {row_position + 1} | {criterion_id} -> Score: {score} | {respuesta}\n\n"
                    log_text += log_entry
                    log_container.text_area("Registro", value=log_text, height=300, disabled=True, label_visibility="collapsed")
                except Exception as exc:
                    df.at[row_position, response_column] = f"Error: {exc}"
                    df.at[row_position, score_column] = 0
                    
                    log_entry = f"❌ Fila {row_position + 1} | {criterion_id} -> Error: {exc}\n\n"
                    log_text += log_entry
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


def criteria_tab():
    st.subheader("Criterios de selección")
    st.write(
        "Aquí se preparará la iteración por fila. Cada criterio creará una nueva columna escalable."
    )

    def handle_add_criterion():
        val = st.session_state.get("new_criterion_input", "").strip()
        if val:
            st.session_state["criteria"].append(val)
            save_criteria(st.session_state["criteria"])
            sync_criteria_columns()
        st.session_state["new_criterion_input"] = ""

    if "new_criterion_input" not in st.session_state:
        st.session_state["new_criterion_input"] = ""

    st.text_input(
        "Nuevo criterio", 
        placeholder="Ej. Incluye población adulta", 
        key="new_criterion_input"
    )
    col_add, col_apply = st.columns([1, 1])

    with col_add:
        st.button("Añadir criterio", use_container_width=True, on_click=handle_add_criterion)

    with col_apply:
        if st.button("Sincronizar columnas", use_container_width=True):
            sync_criteria_columns()
            st.success("Columnas de criterios sincronizadas.")

    if st.session_state["criteria"]:
        st.dataframe(criteria_dataframe(), use_container_width=True, hide_index=True)

        criterion_ids = [f"C{index}" for index in range(1, len(st.session_state["criteria"]) + 1)]
        delete_id = st.selectbox("Criterio a eliminar", criterion_ids)
        confirm_delete = st.checkbox(
            f"Confirmo que quiero eliminar {delete_id}",
            key="confirm_delete_criterion",
        )

        if st.button(
            "Eliminar criterio",
            disabled=not confirm_delete,
            use_container_width=True,
        ):
            delete_index = int(delete_id.replace("C", "")) - 1
            removed = st.session_state["criteria"].pop(delete_index)
            save_criteria(st.session_state["criteria"])
            sync_criteria_columns()
            st.success(f"Se eliminó {delete_id}: {removed}. Los criterios fueron renumerados.")
            st.rerun()


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

    if "criteria" not in st.session_state:
        st.session_state["criteria"] = load_criteria()

    st.title("CribadoLabs")
    st.caption("MVP para cargar fuentes, consolidar registros y preparar cribado académico.")

    with st.sidebar:
        st.header("Arquitectura")
        st.write("1. Cargar fuentes")
        st.write("2. Procesar y editar")
        st.write("3. Añadir criterios")
        st.write("4. Configurar LLM")
        st.write("5. Traducir contenido")

    tab_sources, tab_processing, tab_criteria, tab_llm, tab_translation = st.tabs(
        [
            "Fuentes",
            "Tabla maestra",
            "Criterios",
            "LLM",
            "Traducción",
        ]
    )

    with tab_sources:
        sources_tab()
    with tab_processing:
        processing_tab()
    with tab_criteria:
        criteria_tab()
    with tab_llm:
        llm_settings_tab()
    with tab_translation:
        translation_tab()


if __name__ == "__main__":
    main()
