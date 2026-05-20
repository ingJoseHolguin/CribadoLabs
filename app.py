from pathlib import Path
from datetime import datetime
from io import BytesIO
import json
import os
import re
import time
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

    col_run, col_load, col_save, col_refresh = st.columns([1, 1, 1, 1])
    with col_run:
        run_processing = st.button("Procesar fuentes", type="primary", use_container_width=True)
    with col_load:
        load_existing = st.button("Cargar Excel existente", use_container_width=True)
    with col_save:
        save_edits = st.button("Guardar edición", use_container_width=True)
    with col_refresh:
        if st.button("Actualizar vista", use_container_width=True):
            st.session_state["master_df"] = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
            st.rerun()

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
            {
                "ID": f"C{index}", 
                "Tipo": "Inclusión" if criterion.get("type", "inclusion") == "inclusion" else "Exclusión", 
                "Criterio": criterion.get("text", "")
            }
            for index, criterion in enumerate(criteria, start=1)
        ]
    )


def score_columns(df):
    return [
        column
        for column in df.columns
        if re.match(r"^(C\d+ Total|Criterio C\d+ Final Score:|Criterio C\d+ Score:)", column)
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
    
    # Mapeos basados en el TEXTO del criterio para evitar desalineación al reordenar o borrar
    existing_responses = {} # text -> series
    existing_subscores = {
        "Semantic": {},      # text -> series
        "Context": {},
        "Centrality": {},
        "Evidence": {},
        "Penalty": {},
        "Total": {}
    }
    
    # 1. Encontrar los textos de criterios existentes y su índice viejo (C1, C2...)
    text_to_old_index = {}
    for column in df.columns:
        # Soportar formatos: "C1 Respuesta: Texto" o "Criterio C1 Respuesta: Texto"
        match_resp = re.match(r"^(?:Criterio\s+)?(C\d+)\s+Respuesta:\s*(.+)$", column)
        if match_resp:
            c_index, criterion_text = match_resp.groups()
            criterion_text = criterion_text.strip()
            existing_responses[criterion_text] = df[column].copy()
            text_to_old_index[criterion_text] = c_index
            
    # 2. Mapear subscores usando el índice viejo encontrado para ese texto
    for col_type in ["Semantic", "Context", "Centrality", "Evidence", "Penalty", "Total"]:
        for column in df.columns:
            # Coincidir con "C1 Semantic" o "Criterio C1 Semantic: ..."
            match_sub = re.match(r"^(?:Criterio\s+)?(C\d+)\s+" + col_type + r"(?::.*)?$", column, re.IGNORECASE)
            if match_sub:
                c_index = match_sub.group(1)
                # Buscar a qué texto corresponde este c_index
                for txt, old_idx in text_to_old_index.items():
                    if old_idx == c_index:
                        existing_subscores[col_type][txt] = df[column].copy()
                        break

    # Conservar columnas base (que no sean de criterios antiguos)
    base_columns = [
        column
        for column in df.columns
        if not re.match(r"^(?:C\d+|Criterio\s+C\d+)\s+", column) and column != TOTAL_SCORE_COLUMN
    ]
    df = df[base_columns].copy()

    # Escribir las nuevas columnas respetando el nuevo orden/lista de criterios actual
    for index, criterion in enumerate(criteria, start=1):
        c_index = f"C{index}"
        criterion_text = criterion.get("text", "").strip()
        
        # 1. Respuesta
        response_col = f"{c_index} Respuesta: {criterion_text}"
        df[response_col] = existing_responses.get(criterion_text, "")
        df[response_col] = df[response_col].astype("object")
        
        # 2. Subscore columns y Total
        for col_type in ["Semantic", "Context", "Centrality", "Evidence", "Penalty", "Total"]:
            col_name = f"{c_index} {col_type}"
            if criterion_text in existing_subscores[col_type]:
                df[col_name] = pd.to_numeric(
                    existing_subscores[col_type][criterion_text], errors="coerce"
                ).fillna(0)
            else:
                df[col_name] = 0

    update_total_score(df)
    st.session_state["master_df"] = df
    safe_save_master_dataframe(df)


def verify_cuda_working():
    import subprocess
    import sys
    try:
        # Ejecutar en un subproceso rápido para evitar bloquear hilos en Streamlit en caso de error
        cmd = [
            sys.executable,
            "-c",
            "import os; os.environ['ARGOS_DEVICE_TYPE']='cuda'; import argostranslate.translate; "
            "installed = argostranslate.translate.get_installed_languages(); "
            "from_l = next(filter(lambda x: x.code == 'en', installed), None); "
            "to_l = next(filter(lambda x: x.code == 'es', installed), None); "
            "from_l.get_translation(to_l).translate('test') if (from_l and to_l) else None"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def get_argos_translator(from_code="en", to_code="es", device="auto"):
    if device in ("cuda", "auto"):
        # Verificar si CUDA realmente funciona en el sistema
        if not verify_cuda_working():
            st.warning("⚠️ La aceleración GPU (CUDA) no está disponible o le faltan dependencias del sistema (ej. cublas64_12.dll). Cambiando a traducción por CPU de forma automática.")
            device = "cpu"

    # Configurar el tipo de dispositivo antes de importar argostranslate
    os.environ["ARGOS_DEVICE_TYPE"] = device
    
    import argostranslate.package
    import argostranslate.translate
    
    installed_languages = argostranslate.translate.get_installed_languages()
    from_lang = next(filter(lambda x: x.code == from_code, installed_languages), None)
    to_lang = next(filter(lambda x: x.code == to_code, installed_languages), None)
    
    translation = None
    if from_lang and to_lang:
        translation = from_lang.get_translation(to_lang)
        
    if translation is None:
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            filter(
                lambda x: x.from_code == from_code and x.to_code == to_code,
                available_packages
            ), None
        )
        if package_to_install:
            download_path = package_to_install.download()
            argostranslate.package.install_from_path(download_path)
            
            # Recargar lenguajes
            installed_languages = argostranslate.translate.get_installed_languages()
            from_lang = next(filter(lambda x: x.code == from_code, installed_languages), None)
            to_lang = next(filter(lambda x: x.code == to_code, installed_languages), None)
            if from_lang and to_lang:
                translation = from_lang.get_translation(to_lang)
                
    return translation


def llm_chat(provider, endpoint, model, api_key, prompt):
    if provider == "OpenRouter":
        is_auto_free = model.strip().lower() == "openrouter/auto:free"
        api_model = "openrouter/auto" if is_auto_free else model
        
        payload = {
            "model": api_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        
        if is_auto_free:
            payload["plugins"] = [
                {
                    "id": "auto-router",
                    "allowed_models": ["*/*:free"]
                }
            ]

        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST",
        )

        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    body = json.loads(response.read().decode("utf-8"))
                return body.get("choices", [{}])[0].get("message", {}).get("content", "")
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 5:
                    time.sleep(3 + (2 ** attempt))  # 4s, 5s, 7s, 11s, 19s
                    continue
                raise

    # Default to Ollama
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
            "num_predict": 1024
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


def build_semantic_match_prompt(title, abstract, criterion):
    return f"""
You are a strict scientific screening assistant.

Your task is to evaluate the Semantic Match of a bibliographic record against a selection criterion.

IMPORTANT RULES:
- Be highly conservative and strict.
- Do NOT infer missing details. If a concept is not explicitly mentioned, score it low.
- Return STRICT JSON ONLY. Do not wrap in markdown blocks, do not write code blocks, do not output explanations outside the JSON.

---

## BIBLIOGRAPHIC RECORD:
Title: {title}
Abstract: {abstract}

## SELECTION CRITERION:
{criterion}

---

## SCORING DIMENSION TO EVALUATE:

Semantic Match (Score: 0 to 3)
Measures semantic similarity between the concepts in the criterion and the article content.
- 0 = Unrelated or absent (no conceptual overlap)
- 1 = Weak conceptual overlap (only minor keywords mentioned, no deeper connection)
- 2 = Related conceptually (addresses similar themes but doesn't directly map)
- 3 = Strongly aligned semantically (concepts directly overlap and map to the criterion)

---

## REQUIRED JSON RESPONSE FORMAT:
{{
  "score": <0|1|2|3>,
  "reason": "<strict_justification_in_english>"
}}
""".strip()


def build_centrality_prompt(title, abstract, criterion):
    return f"""
You are a strict scientific screening assistant.

Your task is to evaluate the Centrality of a bibliographic record against a selection criterion.

IMPORTANT RULES:
- Be highly conservative and strict.
- Do NOT assume a topic is central just because it is mentioned.
- Return STRICT JSON ONLY. Do not wrap in markdown blocks, do not write code blocks, do not output explanations outside the JSON.

---

## BIBLIOGRAPHIC RECORD:
Title: {title}
Abstract: {abstract}

## SELECTION CRITERION:
{criterion}

---

## SCORING DIMENSION TO EVALUATE:

Centrality (Score: 0 to 3)
Measures whether the criterion is central to the paper's main focus or goals.
- 0 = Absent
- 1 = Incidental mention (only in passing or as background context)
- 2 = Secondary topic (discussed in a section, but not the main objective)
- 3 = Primary focus (the main objective or key result of the paper)

---

## REQUIRED JSON RESPONSE FORMAT:
{{
  "score": <0|1|2|3>,
  "reason": "<strict_justification_in_english>"
}}
""".strip()


def build_exclusion_penalty_prompt(title, abstract, criterion):
    return f"""
You are a strict scientific screening assistant acting as a strict exclusion gatekeeper.

Your only task is to identify deviations, gaps, or explicit exclusion signals between the bibliographic record and the selection criterion.

IMPORTANT RULES:
- Be extremely critical. Look for any mismatch in scope, population, methods, or assumptions.
- If there is any mismatch, apply a negative penalty.
- Return STRICT JSON ONLY. Do not wrap in markdown blocks, do not write code blocks, do not output explanations outside the JSON.

---

## BIBLIOGRAPHIC RECORD:
Title: {title}
Abstract: {abstract}

## SELECTION CRITERION:
{criterion}

---

## SCORING DIMENSION TO EVALUATE:

Exclusion Penalty (Score: 0 to -3)
Penalizes important deviations from the intended scope or clear exclusion signals.
- 0 = No penalty (perfect alignment, no mismatched scope)
- -1 = Mild mismatch in scope or parameters
- -2 = Significant mismatch or clear deviation from the intended scope
- -3 = Strong exclusion signal (explicitly states focus is outside, or contains a hard exclusion parameter)

---

## REQUIRED JSON RESPONSE FORMAT:
{{
  "score": <0|-1|-2|-3>,
  "reason": "<strict_justification_in_english>"
}}
""".strip()


def evaluate_row_criterion(provider, endpoint, model, api_key, title, abstract, criterion_id, criterion):
    # Consulta 1: Semantic Match
    p_sem = build_semantic_match_prompt(title, abstract, criterion)
    r_sem = llm_chat(provider, endpoint, model, api_key, p_sem)
    try:
        parsed_sem = extract_json_response(r_sem)
        semantic = int(parsed_sem.get("score", 0))
        semantic_reason = str(parsed_sem.get("reason", "")).strip()
    except Exception as e:
        semantic = 0
        semantic_reason = f"Error: {e}. Respuesta cruda: {r_sem}"

    # Consulta 2: Centrality
    p_cen = build_centrality_prompt(title, abstract, criterion)
    r_cen = llm_chat(provider, endpoint, model, api_key, p_cen)
    try:
        parsed_cen = extract_json_response(r_cen)
        centrality = int(parsed_cen.get("score", 0))
        centrality_reason = str(parsed_cen.get("reason", "")).strip()
    except Exception as e:
        centrality = 0
        centrality_reason = f"Error: {e}. Respuesta cruda: {r_cen}"

    # Consulta 3: Exclusion Penalty
    p_pen = build_exclusion_penalty_prompt(title, abstract, criterion)
    r_pen = llm_chat(provider, endpoint, model, api_key, p_pen)
    try:
        parsed_pen = extract_json_response(r_pen)
        penalty = int(parsed_pen.get("score", 0))
        penalty_reason = str(parsed_pen.get("reason", "")).strip()
    except Exception as e:
        penalty = 0
        penalty_reason = f"Error: {e}. Respuesta cruda: {r_pen}"

    # Mantener a 0 Context y Evidence por retrocompatibilidad
    context = 0
    evidence = 0
    
    final_score = semantic + context + centrality + evidence + penalty

    combined_response = (
        f"1. COINCIDENCIA SEMÁNTICA ({semantic}/3): {semantic_reason}\n\n"
        f"2. CENTRALIDAD ({centrality}/3): {centrality_reason}\n\n"
        f"3. PENALIZACIÓN POR EXCLUSIÓN ({penalty}/-3): {penalty_reason}"
    )

    return {
        "semantic_match": semantic,
        "context_alignment": context,
        "centrality": centrality,
        "evidence_strength": evidence,
        "exclusion_penalty": penalty,
        "final_score": final_score,
        "respuesta": combined_response,
        "raw": f"Evaluado en 3 consultas separadas.\n\n{combined_response}",
    }


def load_llm_config():
    default_config = {"provider": "Ollama", "endpoint": "http://localhost:11434", "model": "llama3.1", "api_key": ""}
    if not LLM_CONFIG_FILE.exists():
        return default_config

    try:
        with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return default_config

    return {
        "provider": config.get("provider", "Ollama"),
        "endpoint": config.get("endpoint", "http://localhost:11434"),
        "model": config.get("model", "llama3.1"),
        "api_key": config.get("api_key", ""),
    }


def save_llm_config(provider, endpoint, model, api_key):
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(LLM_CONFIG_FILE, "w", encoding="utf-8") as config_file:
        json.dump({"provider": provider, "endpoint": endpoint, "model": model, "api_key": api_key}, config_file, indent=2)


def load_criteria():
    if not CRITERIA_FILE.exists():
        return []

    try:
        with open(CRITERIA_FILE, "r", encoding="utf-8") as config_file:
            criteria = json.load(config_file)
            if isinstance(criteria, list):
                migrated = []
                for item in criteria:
                    if isinstance(item, str):
                        migrated.append({"text": item, "type": "inclusion"})
                    elif isinstance(item, dict):
                        migrated.append({
                            "text": item.get("text", ""),
                            "type": item.get("type", "inclusion")
                        })
                return migrated
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
        "Configura un proveedor (Ollama local o OpenRouter API) para evaluar cada fila sin conservar contexto global."
    )

    llm_config = load_llm_config()
    st.session_state.setdefault("llm_provider", llm_config["provider"])
    st.session_state.setdefault("ollama_endpoint", llm_config["endpoint"])
    st.session_state.setdefault("ollama_model", llm_config["model"])
    st.session_state.setdefault("llm_api_key", llm_config["api_key"])

    provider = st.radio("Proveedor de LLM", ["Ollama", "OpenRouter"], horizontal=True, index=0 if st.session_state["llm_provider"] == "Ollama" else 1)
    st.session_state["llm_provider"] = provider

    if provider == "Ollama":
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
    else:
        # OpenRouter
        col_model, col_key = st.columns([1, 2])
        with col_model:
            model = st.text_input(
                "Modelo OpenRouter",
                value=st.session_state["ollama_model"],
                placeholder="openai/gpt-4o-mini",
            )
        with col_key:
            api_key = st.text_input(
                "API Key OpenRouter",
                value=st.session_state["llm_api_key"],
                type="password"
            )
        st.session_state["llm_api_key"] = api_key.strip()

    st.session_state["ollama_model"] = model.strip()

    col_save_config, col_test = st.columns([1, 1])
    with col_save_config:
        if st.button("Guardar configuración", use_container_width=True):
            save_llm_config(
                st.session_state["llm_provider"],
                st.session_state["ollama_endpoint"],
                st.session_state["ollama_model"],
                st.session_state["llm_api_key"]
            )
            st.success(f"Configuración guardada en {LLM_CONFIG_FILE}.")

    with col_test:
        test_connection = st.button("Probar conexión", use_container_width=True)

    if test_connection:
        with st.spinner(f"Conectando con {provider} (esto puede tardar si el modelo se está cargando)..."):
            try:
                response = llm_chat(
                    st.session_state["llm_provider"],
                    st.session_state["ollama_endpoint"],
                    st.session_state["ollama_model"],
                    st.session_state["llm_api_key"],
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

    sync_criteria_columns()
    df = st.session_state["master_df"]
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
    skip_evaluated = st.checkbox("Saltar criterios ya evaluados", value=True, help="Si marcas esto, el LLM solo evaluará las celdas que estén vacías para no repetir trabajo.")

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
                        st.session_state["llm_provider"],
                        st.session_state["ollama_endpoint"],
                        st.session_state["ollama_model"],
                        st.session_state["llm_api_key"],
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


def criteria_tab():
    st.subheader("Criterios de selección")
    st.write(
        "Aquí se preparará la iteración por fila. Cada criterio creará una nueva columna escalable."
    )

    def handle_add_criterion():
        val = st.session_state.get("new_criterion_input", "").strip()
        c_type = st.session_state.get("new_criterion_type", "inclusion")
        if val:
            st.session_state["criteria"].append({"text": val, "type": c_type})
            save_criteria(st.session_state["criteria"])
            sync_criteria_columns()
        st.session_state["new_criterion_input"] = ""

    if "new_criterion_input" not in st.session_state:
        st.session_state["new_criterion_input"] = ""

    col_text, col_type = st.columns([3, 1])
    with col_text:
        st.text_input(
            "Nuevo criterio", 
            placeholder="Ej. Incluye población adulta", 
            key="new_criterion_input"
        )
    with col_type:
        st.selectbox(
            "Tipo",
            options=["inclusion", "exclusion"],
            format_func=lambda x: "Inclusión" if x == "inclusion" else "Exclusión",
            key="new_criterion_type"
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
            st.success(f"Se eliminó {delete_id}: {removed.get('text', '')}. Los criterios fueron renumerados.")
            st.rerun()


def translation_tab():
    st.subheader("Traducción Offline de Tabla (Argos Translate)")
    st.write(
        "Traduce los campos **Titulo** y **Abstract** al Español de manera 100% offline. "
        "Los resultados se guardarán en las columnas **Titulo ES** y **Abstract ES** respectivamente."
    )

    df = st.session_state.get("master_df", load_master_dataframe())
    
    if df.empty:
        st.warning("No hay registros en la tabla maestra para traducir.")
        return

    # Opciones de aceleración
    st.markdown("### Configuración de Aceleración")
    device_type = st.radio(
        "Seleccionar dispositivo de procesamiento (Aceleración GPU):",
        options=["auto", "cpu", "cuda"],
        index=0,
        help=(
            "auto: Detecta y usa GPU si está disponible.\n"
            "cpu: Usa el procesador principal (más lento pero compatible con todo).\n"
            "cuda: Fuerza el uso de GPU NVIDIA (requiere drivers CUDA instalados)."
        ),
        horizontal=True
    )

    def is_empty_value(val):
        if pd.isna(val):
            return True
        s = str(val).strip()
        return s == "" or s.lower() in ("nan", "none", "<none>")

    # Filtrar filas sin traducir (opcional)
    solo_vacias = st.checkbox("Traducir solo filas sin traducción previa", value=True)

    # Botón de traducción
    if st.button("Ejecutar traducción al Español", type="primary", key="btn_run_translate"):
        # Asegurar tipo object/string para evitar TypeError con columnas vacías (que pandas lee como float64)
        df["Titulo ES"] = df["Titulo ES"].astype(object)
        df["Abstract ES"] = df["Abstract ES"].astype(object)
        
        # Contar filas a procesar
        if solo_vacias:
            tit_empty = df["Titulo ES"].apply(is_empty_value)
            abs_empty = df["Abstract ES"].apply(is_empty_value)
            rows_to_translate = df[tit_empty | abs_empty]
        else:
            rows_to_translate = df

        total_rows = len(rows_to_translate)
        if total_rows == 0:
            st.success("¡Todos los registros ya cuentan con su respectiva traducción!")
            return

        # Inicialización del traductor
        with st.status("Cargando motor de traducción offline...", expanded=True) as status:
            try:
                status.write("Inicializando Argos Translate (puede tardar en descargar el modelo si es la primera vez)...")
                translator = get_argos_translator("en", "es", device=device_type)
                if not translator:
                    status.update(label="Error al inicializar el traductor", state="error")
                    st.error("No se pudo cargar o descargar el paquete de idioma Inglés -> Español.")
                    return
                status.update(label="Motor de traducción cargado correctamente.", state="complete")
            except Exception as e:
                status.update(label="Error de inicialización", state="error")
                st.error(f"Ocurrió un error al cargar el traductor: {e}")
                return

        # Barra de progreso
        progress_bar = st.progress(0)
        status_text = st.empty()

        translated_count = 0
        
        # Procesar fila por fila
        for idx, row in rows_to_translate.iterrows():
            status_text.text(f"Traduciendo fila {translated_count + 1} de {total_rows}...")
            
            # Traducir Titulo si aplica
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

            # Traducir Abstract si aplica
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
        
        # Guardar en session state y en archivo
        st.session_state["master_df"] = df
        safe_save_master_dataframe(df)
        
        progress_bar.empty()
        status_text.empty()
        st.success(f"¡Traducción completada con éxito! Se procesaron {total_rows} filas.")
        st.rerun()

    # Visualizar las columnas de traducción
    st.markdown("### Vista previa de Traducciones")
    cols_to_show = ["Fuente", "Titulo", "Titulo ES", "Abstract", "Abstract ES"]
    existing_show_cols = [c for c in cols_to_show if c in df.columns]
    st.dataframe(df[existing_show_cols].head(10), use_container_width=True)


def safe_save_dataframe(df_to_save, filename):
    try:
        return save_master_dataframe(df_to_save, filename=filename)
    except PermissionError:
        st.toast(f"⚠️ No se pudo guardar en Excel. Por favor, cierra el archivo {filename} si lo tienes abierto.", icon="⚠️")
        return OUTPUT_FOLDER / filename


def filtering_tab():
    st.subheader("Filtrado de Flujo (PRISMA)")
    st.write(
        "Crea subtablas a partir de la tabla maestra aplicando criterios de inclusión y exclusión."
    )
    
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
                        # Si saca >= exc_threshold en la exclusión, lo descartamos. Queremos mantener < exc_threshold.
                        cond = pd.to_numeric(df_final[col_total], errors="coerce").fillna(0) < exc_threshold
                        exc_conditions.append(cond)
            
            if exc_conditions:
                # Para sobrevivir, debe cumplir < exc_threshold en TODOS los criterios de exclusión
                survived = exc_conditions[0]
                for cond in exc_conditions[1:]:
                    survived = survived & cond
                df_final = df_final[survived].copy()
                
        total_final = len(df_final)
        excluded_by_exc = total_included - total_final
        
        # Guardar en Excel
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
        st.write("6. Filtrar resultados (PRISMA)")

    tab_sources, tab_processing, tab_criteria, tab_llm, tab_translation, tab_filtering = st.tabs(
        [
            "Fuentes",
            "Tabla maestra",
            "Criterios",
            "LLM",
            "Traducción",
            "Filtrado (PRISMA)"
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
    with tab_filtering:
        filtering_tab()


if __name__ == "__main__":
    main()
