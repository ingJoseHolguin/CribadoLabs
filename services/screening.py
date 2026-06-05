"""Módulo de Cribado por Criterio Individual con LLM Local.

Flujo:
  Fase 0: Pre-filtrado por keywords editables (scoring, sin LLM)
  Fase 1: 13 prompts independientes por fila (I1-I4, E1-E9)
  Fase 2: Revisión de dudosos con contexto completo (LLM)
  Fase 3: Extracción de datos para 4 PIs (LLM)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.llm_client import ollama_chat_with_retry


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
CONFIG_DIR = Path("config")
KEYWORDS_FILE = CONFIG_DIR / "screening_keywords.json"

# Opciones de Ollama optimizadas para prompts cortos (criterio individual)
OLLAMA_OPTIONS_CRITERIO = {
    "num_ctx": 2048,
    "temperature": 0.0,
    "top_p": 0.0,
    "repeat_penalty": 1.0,
    "num_predict": 256,
}

# ---------------------------------------------------------------------------
# Criterios dinámicos desde config/criteria.json
# ---------------------------------------------------------------------------

CRITERIOS_INCLUSION_DEFAULT = {
    "I1": {
        "nombre": "I1 - Artefacto computacional",
        "descripcion": (
            "El estudio propone, evalúa o revisa un ARTEFACTO COMPUTACIONAL "
            "(sistema, herramienta, modelo, framework, métrica, algoritmo) para "
            "medir/estimar/evaluar la CALIDAD DE LA COLABORACIÓN."
        ),
        "pregunta": "¿Este estudio trata sobre un artefacto computacional que mide o evalúa la calidad de la colaboración?",
    },
    "I2": {
        "nombre": "I2 - Colaboración humano-humano",
        "descripcion": (
            "El estudio se centra en colaboración HUMANO-HUMANO. "
            "No human-robot, no human-AI como agente colaborador, no multi-agent LLM."
        ),
        "pregunta": "¿Este estudio trata sobre colaboración entre humanos (no human-robot, no human-AI agente)?",
    },
    "I3": {
        "nombre": "I3 - Colaboración colocalizada síncrona",
        "descripcion": (
            "El contexto es colaboración COLOCALIZADA SÍNCRONA "
            "(face-to-face, co-located, same room, same time same place). "
            "No remoto, no virtual como sustituto, no distribuido, no híbrido sin componente F2F central."
        ),
        "pregunta": "¿El estudio se centra en entornos colocalizados face-to-face (no remoto, no virtual, no distribuido)?",
    },
    "I4": {
        "nombre": "I4 - Evaluación empírica o revisión",
        "descripcion": (
            "El estudio incluye una evaluación empírica, experimental, de caso, "
            "o es una revisión sistemática/survey."
        ),
        "pregunta": "¿El estudio incluye evaluación empírica o es una revisión/survey?",
    },
}

CRITERIOS_EXCLUSION_DEFAULT = {
    "E1": {
        "nombre": "E1 - Exclusión: Humano-robot/AI",
        "descripcion": (
            "Excluir si el estudio trata sobre colaboración humano-robot, "
            "humano-agente, o multi-agent systems con LLMs como colaboradores."
        ),
        "pregunta": "¿Este estudio trata sobre humano-robot, humano-AI agente, o multi-agent LLM como colaborador?",
    },
    "E2": {
        "nombre": "E2 - Exclusión: Virtual/remoto/distribuido",
        "descripcion": (
            "Excluir si el estudio es puramente virtual, remoto, distribuido "
            "o híbrido SIN componente face-to-face central."
        ),
        "pregunta": "¿Este estudio es puramente virtual, remoto o distribuido sin componente F2F central?",
    },
    "E3": {
        "nombre": "E3 - Exclusión: Telemedicina/salud mental digital",
        "descripcion": (
            "Excluir si es telemedicina, psicoterapia online, "
            "intervenciones de salud mental digitales."
        ),
        "pregunta": "¿Este estudio trata sobre telemedicina, psicoterapia online o salud mental digital?",
    },
    "E4": {
        "nombre": "E4 - Exclusión: Comunicación de oficina sin medición",
        "descripcion": (
            "Excluir si son sistemas de comunicación de oficina "
            "(email, Slack, Teams) SIN medición de calidad de colaboración."
        ),
        "pregunta": "¿Es un sistema de comunicación de oficina (email, Slack, Teams) sin medir calidad de colaboración?",
    },
    "E5": {
        "nombre": "E5 - Exclusión: Juegos serios sin medición CQ",
        "descripcion": (
            "Excluir si son juegos serios SIN medición de calidad de colaboración como constructo central."
        ),
        "pregunta": "¿Es un juego serio SIN medición de calidad de colaboración como constructo central?",
    },
    "E6": {
        "nombre": "E6 - Exclusión: Educación online/remota",
        "descripcion": (
            "Excluir si es educación online/remota (MOOCs, e-learning) "
            "SIN componente face-to-face significativo."
        ),
        "pregunta": "¿Es educación online/remota (MOOCs, e-learning) sin componente F2F?",
    },
    "E7": {
        "nombre": "E7 - Exclusión: Solo menciona sin medir",
        "descripcion": (
            "Excluir si solo menciona 'colaboración' o 'face-to-face' "
            "pero NO mide/evalúa la calidad de la colaboración."
        ),
        "pregunta": "¿Solo menciona colaboración o face-to-face pero NO mide/evalúa la calidad de colaboración?",
    },
    "E8": {
        "nombre": "E8 - Exclusión: Social media / dating apps",
        "descripcion": (
            "Excluir si trata sobre dating apps, social media, o redes sociales."
        ),
        "pregunta": "¿Trata sobre dating apps, social media o redes sociales?",
    },
    "E9": {
        "nombre": "E9 - Exclusión: Opinión/editorial",
        "descripcion": (
            "Excluir si es artículo de opinión, editorial, o sin datos empíricos/revisión."
        ),
        "pregunta": "¿Es un artículo de opinión, editorial, o sin datos empíricos?",
    },
}


def cargar_criterios_dinamicos() -> tuple[dict, dict]:
    """Carga criterios desde config/criteria.json. Si no existe o esta vacio, usa defaults."""
    path = CONFIG_DIR / "criteria.json"
    default_inclusion = CRITERIOS_INCLUSION_DEFAULT
    default_exclusion = CRITERIOS_EXCLUSION_DEFAULT

    if not path.exists():
        return default_inclusion, default_exclusion

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_inclusion, default_exclusion

    if not data or not isinstance(data, list):
        return default_inclusion, default_exclusion

    inclusion = {}
    exclusion = {}
    inc_counter = 1
    exc_counter = 1

    for item in data:
        text = item.get("text", "").strip()
        ctype = item.get("type", "inclusion")
        if not text:
            continue
        cfg = {
            "nombre": text,
            "descripcion": text,
            "pregunta": f"¿{text}?",
        }
        if ctype == "inclusion":
            inclusion[f"I{inc_counter}"] = cfg
            inc_counter += 1
        else:
            exclusion[f"E{exc_counter}"] = cfg
            exc_counter += 1

    # Si no hay criterios definidos, usar defaults
    if not inclusion and not exclusion:
        return default_inclusion, default_exclusion

    return inclusion, exclusion


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def _truncar_registro(titulo: str, abstract: str, max_chars: int = 300) -> tuple[str, str]:
    """Trunca el abstract para mantener prompts cortos."""
    abstract_corto = (abstract[:max_chars] + "...") if len(abstract) > max_chars else abstract
    return titulo, abstract_corto


def _build_corpus(df: pd.DataFrame) -> list[str]:
    """Construye el corpus de texto a partir de Titulo, Abstract y Keywords."""
    texts = []
    for _, row in df.iterrows():
        parts = []
        for col in ["Titulo", "Abstract", "Keywords", "Titulo ES", "Abstract ES"]:
            if col in row.index:
                val = row[col]
                if pd.notna(val):
                    parts.append(str(val))
        texts.append(" ".join(parts))
    return texts


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

def cargar_keywords_screening(path: Path = KEYWORDS_FILE) -> dict:
    """Carga keywords de screening desde JSON. Soporta formato nuevo (terminos_busqueda) y antiguo."""
    default = {
        "terminos_busqueda": [
            "collaboration quality",
            "collaborative quality",
            "quality of collaboration",
            "collaboration analytics",
            "collaborative analytics",
            "multimodal learning analytics",
            "MMLA",
            "co-located collaboration",
            "collocated collaboration",
            "face-to-face collaboration",
            "collaboration assessment",
            "collaboration measurement",
            "interpersonal synchrony",
            "inter-brain synchrony",
            "teamwork quality",
            "collaborative convergence",
            "embodied teamwork",
            "socio-spatial analytics",
            "collaboration modeling",
            "interaction analysis",
            "nonverbal cues",
            "augmented reality collaboration",
            "evaluating collaboration",
            "multi-sensory cues",
            "learning analytics",
            "computer vision",
            "team communication",
            "co-located",
            "collocated",
            "face-to-face",
            "face to face",
            "same room",
            "co-present",
            "in-person",
            "presencial",
            "cara a cara",
            "shared space",
            "same place",
            "physical presence",
            "co-presence",
            "joint activity",
            "interaction quality",
            "coordination quality",
            "mutual understanding",
            "shared understanding",
            "common ground",
            "group awareness",
            "team awareness",
            "collaboration effectiveness",
            "collaborative performance",
        ],
        # Campos antiguos se mantienen por retrocompatibilidad del pipeline automático
        "keywords_colaboracion": [],
        "keywords_contexto": [],
        "sinonimos_calidad": [],
    }
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Asegurar que existan todas las claves
        for k in default:
            if k not in data or not isinstance(data[k], list):
                data[k] = default[k]
        return data
    except (OSError, json.JSONDecodeError):
        return default


def guardar_keywords_screening(data: dict, path: Path = KEYWORDS_FILE) -> None:
    """Guarda keywords de screening a JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Prompts por criterio
# ---------------------------------------------------------------------------

def _build_prompt_criterio(titulo: str, abstract: str, keywords: str, cid: str, config: dict) -> str:
    """Construye prompt robusto con chain-of-thought para modelos pequeños (4B)."""
    nombre = config["nombre"]
    descripcion = config["descripcion"]
    pregunta = config["pregunta"]

    if cid.startswith("I"):
        instruccion_extra = (
            "INSTRUCTIONS:\n"
            "1. Read the title, abstract and keywords carefully.\n"
            "2. Look for explicit evidence that matches the criterion.\n"
            "3. If evidence is clear → cumple=true. If absent or contradictory → cumple=false.\n"
            "4. Do NOT guess. If unsure, set confianza=1 or 2 and cumple=false.\n"
            "5. Be conservative: when in doubt, say false."
        )
    else:
        instruccion_extra = (
            "INSTRUCTIONS:\n"
            "1. Read the title, abstract and keywords carefully.\n"
            "2. Look for explicit evidence that the study matches this EXCLUSION criterion.\n"
            "3. Only set cumple=true if there is CLEAR evidence (e.g., 'human-robot', 'virtual reality', 'telemedicine').\n"
            "4. If only mentioned in passing or unclear → cumple=false.\n"
            "5. Be conservative: do NOT exclude unless clearly proven."
        )

    return f"""You are a strict scientific screening assistant for scoping reviews.
Your task is to evaluate ONE criterion for one bibliographic record.
Be highly conservative. Do NOT infer missing details.

RECORD:
Title: {titulo}
Abstract: {abstract}
Keywords: {keywords}

CRITERION: {nombre}
DESCRIPTION: {descripcion}

{instruccion_extra}

QUESTION: {pregunta}

Respond ONLY in strict JSON with no markdown, no code blocks, no extra text:
{{
  "cumple": true or false,
  "confianza": 1 to 5,
  "justificacion": "one short sentence",
  "evidencia": "exact text fragment from record or empty"
}}
""".strip()


# ---------------------------------------------------------------------------
# Fase 0: Pre-filtrado por keywords con scoring
# ---------------------------------------------------------------------------

def _build_corpus_text(row: pd.Series) -> str:
    """Construye texto concatenado de Titulo, Abstract, Keywords y traducciones."""
    parts = []
    for col in ["Titulo", "Abstract", "Keywords", "Titulo ES", "Abstract ES"]:
        if col in row.index and pd.notna(row[col]):
            parts.append(str(row[col]))
    return " ".join(parts)


def fase0_prefiltrado(df_master: pd.DataFrame, keywords_config: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Pre-filtrado por keywords.
    Si keywords_config contiene 'terminos_busqueda', usa el nuevo sistema dinámico
    (una columna por término, búsqueda exacta case-insensitive).
    Si no, usa el sistema antiguo de 3 categorías.
    """
    if df_master.empty:
        df = df_master.copy()
        for col in ["F0_Score", "F0_Pasa", "F0_Dudoso", "F0_Excluido", "F0_KeywordsEncontradas"]:
            df[col] = 0 if col == "F0_Score" else False
        return df, {"total": 0, "pasan": 0, "dudosos": 0, "excluidos": 0}

    kw = keywords_config if keywords_config is not None else cargar_keywords_screening()

    # Preferir nuevo formato de términos dinámicos
    terminos = [t.strip() for t in kw.get("terminos_busqueda", []) if t.strip()]
    if terminos:
        return fase0_busqueda_terminos(df_master, terminos, clasificar=True)

    # Fallback al sistema antiguo de 3 categorías
    k_col = [k.lower() for k in kw.get("keywords_colaboracion", [])]
    k_ctx = [k.lower() for k in kw.get("keywords_contexto", [])]
    k_sin = [k.lower() for k in kw.get("sinonimos_calidad", [])]

    def _score_text(text: str) -> tuple[float, float, float, str]:
        t = text.lower()
        found = []

        col_hits = sum(1 for k in k_col if k in t)
        score_col = min(col_hits, 3)
        if col_hits:
            found.extend([k for k in k_col if k in t][:3])

        ctx_hits = sum(1 for k in k_ctx if k in t)
        score_ctx = min(ctx_hits, 2)
        if ctx_hits:
            found.extend([k for k in k_ctx if k in t][:2])

        sin_hits = sum(1 for k in k_sin if k in t)
        score_sin = min(sin_hits, 1)
        if sin_hits:
            found.extend([k for k in k_sin if k in t][:1])

        return score_col, score_ctx, score_sin, ", ".join(list(dict.fromkeys(found)))

    df = df_master.copy()
    scores = []
    pasan = []
    dudosos = []
    excluidos = []
    keywords_found = []

    for _, row in df.iterrows():
        text = _build_corpus_text(row)
        sc, sctx, ssin, found = _score_text(text)
        total = sc + sctx + ssin
        scores.append(total)
        keywords_found.append(found)

        if total >= 2:
            pasan.append(True)
            dudosos.append(False)
            excluidos.append(False)
        elif total == 1:
            pasan.append(False)
            dudosos.append(True)
            excluidos.append(False)
        else:
            pasan.append(False)
            dudosos.append(False)
            excluidos.append(True)

    df["F0_Score"] = scores
    df["F0_Pasa"] = pasan
    df["F0_Dudoso"] = dudosos
    df["F0_Excluido"] = excluidos
    df["F0_KeywordsEncontradas"] = keywords_found

    reporte = {
        "total": len(df),
        "pasan": int(sum(pasan)),
        "dudosos": int(sum(dudosos)),
        "excluidos": int(sum(excluidos)),
    }

    return df, reporte


def _termino_en_titulo_o_abstract(row: pd.Series, termino: str) -> int:
    """Busca el término en Titulo o Abstract (case-insensitive, frase exacta)."""
    titulo = str(row.get("Titulo", "")).lower()
    abstract = str(row.get("Abstract", "")).lower()
    term_lower = termino.lower()
    return 1 if (term_lower in titulo or term_lower in abstract) else 0


def fase0_busqueda_terminos(
    df_master: pd.DataFrame,
    terminos: list[str],
    clasificar: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Para cada término, crea una columna con valor 1 si aparece en Título O Abstract
    (búsqueda exacta case-insensitive de la frase completa). Cada término aporta
    máximo 1 punto, sin importar si aparece en título, abstract o ambos.

    También genera F0_Score con la suma total de coincidencias por fila.
    Si clasificar=True, genera además F0_Pasa/Dudoso/Excluido (uso del pipeline automático).
    Si clasificar=False (búsqueda manual), solo genera las columnas de términos y el score.
    """
    if df_master.empty:
        return df_master.copy(), {"total": 0, "terminos": {}, "coincidencias": 0, "max_score": 0}

    df = df_master.copy()
    terminos_limpios = [t.strip() for t in terminos if t.strip()]
    reporte_terminos: dict[str, int] = {}

    for termino in terminos_limpios:
        col_name = termino
        reporte_terminos[col_name] = 0
        matches = []

        for _, row in df.iterrows():
            found = _termino_en_titulo_o_abstract(row, termino)
            matches.append(found)
            if found:
                reporte_terminos[col_name] += 1

        df[col_name] = matches

    if terminos_limpios:
        df["F0_Score"] = df[terminos_limpios].sum(axis=1)
    else:
        df["F0_Score"] = 0

    # Ordenar por F0_Score descendente para que la tabla y la evaluación F1
    # usen el mismo orden (mayor score primero)
    df = df.sort_values("F0_Score", ascending=False).reset_index(drop=True)

    if clasificar:
        df["F0_Pasa"] = df["F0_Score"] >= 2
        df["F0_Dudoso"] = df["F0_Score"] == 1
        df["F0_Excluido"] = df["F0_Score"] == 0
        df["F0_KeywordsEncontradas"] = ""
        reporte = {
            "total": len(df),
            "pasan": int(df["F0_Pasa"].sum()),
            "dudosos": int(df["F0_Dudoso"].sum()),
            "excluidos": int(df["F0_Excluido"].sum()),
            "terminos": reporte_terminos,
        }
    else:
        reporte = {
            "total": len(df),
            "terminos": reporte_terminos,
            "coincidencias": int((df["F0_Score"] > 0).sum()),
            "max_score": int(df["F0_Score"].max()) if not df.empty else 0,
        }

    return df, reporte


def fase0_limpiar_terminos(df: pd.DataFrame, terminos: list[str]) -> pd.DataFrame:
    """Pone a 0 las columnas de los términos indicados y recalcula F0_Score."""
    df = df.copy()
    terminos_limpios = [t.strip() for t in terminos if t.strip()]
    cols_existentes = []
    for termino in terminos_limpios:
        if termino in df.columns:
            df[termino] = 0
            cols_existentes.append(termino)
    if cols_existentes:
        df["F0_Score"] = df[cols_existentes].sum(axis=1)
    else:
        df["F0_Score"] = 0
    df["F0_Pasa"] = df["F0_Score"] >= 2
    df["F0_Dudoso"] = df["F0_Score"] == 1
    df["F0_Excluido"] = df["F0_Score"] == 0
    return df


def fase0_sumar_score(df: pd.DataFrame, terminos: list[str]) -> pd.DataFrame:
    """Recalcula F0_Score a partir de las columnas de términos existentes."""
    df = df.copy()
    terminos_limpios = [t.strip() for t in terminos if t.strip()]
    cols_existentes = [t for t in terminos_limpios if t in df.columns]
    if cols_existentes:
        df["F0_Score"] = df[cols_existentes].sum(axis=1)
    else:
        df["F0_Score"] = 0
    # Asegurar que existan las columnas de decisión
    for col in ["F0_Pasa", "F0_Dudoso", "F0_Excluido", "F0_KeywordsEncontradas"]:
        if col not in df.columns:
            df[col] = False if col != "F0_KeywordsEncontradas" else ""
    df["F0_Pasa"] = df["F0_Score"] >= 2
    df["F0_Dudoso"] = df["F0_Score"] == 1
    df["F0_Excluido"] = df["F0_Score"] == 0
    return df


def fase0_reiniciar_terminos(
    df: pd.DataFrame,
    terminos_actuales: list[str],
    terminos_guardados: list[str] | None = None,
) -> pd.DataFrame:
    """
    Elimina todas las columnas de términos de búsqueda y las columnas F0 asociadas
    para poder regenerarlas desde cero.
    """
    df = df.copy()
    todos_terminos: set[str] = set(t.strip() for t in terminos_actuales if t.strip())
    if terminos_guardados:
        todos_terminos.update(t.strip() for t in terminos_guardados if t.strip())

    cols_a_eliminar = []
    for termino in todos_terminos:
        if termino in df.columns:
            cols_a_eliminar.append(termino)

    for col in ["F0_Score", "F0_Pasa", "F0_Dudoso", "F0_Excluido", "F0_KeywordsEncontradas"]:
        if col in df.columns:
            cols_a_eliminar.append(col)

    if cols_a_eliminar:
        df = df.drop(columns=cols_a_eliminar)

    return df


# ---------------------------------------------------------------------------
# Fase 1: Cribado por Criterio Individual (13 prompts por fila)
# ---------------------------------------------------------------------------

def fase1_cribado_por_criterio(
    df_f0: pd.DataFrame,
    llm_config: dict,
    delay: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    skip_evaluated: bool = True,
    max_chars_abstract: int = 300,
) -> tuple[pd.DataFrame, dict]:
    """
    Para cada fila que pasó F0 (F0_Pasa==True o F0_Dudoso==True opcional),
    evalúa 13 criterios con prompts independientes.
    """
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")

    df = df_f0.copy()

    inclusion_cfg, exclusion_cfg = cargar_criterios_dinamicos()
    all_cids = list(inclusion_cfg.keys()) + list(exclusion_cfg.keys())
    for cid in all_cids:
        for suffix in ["cumple", "confianza", "justificacion", "evidencia"]:
            col = f"F1_{cid}_{suffix}"
            default = False if suffix == "cumple" else (0 if suffix == "confianza" else "")
            if col not in df.columns:
                df[col] = default

    for col in ["F1_Decision", "F1_Score_PI", "F1_CriterioExclusion", "F1_Error"]:
        if col not in df.columns:
            df[col] = "" if col in ("F1_Decision", "F1_CriterioExclusion") else (0.0 if col == "F1_Score_PI" else False)

    # Determinar candidatos: si existe clasificación F0, usarla; si no, usar score > 0; si no hay nada, todos
    has_f0_classification = "F0_Pasa" in df.columns or "F0_Dudoso" in df.columns
    if has_f0_classification:
        mask_eval = df.get("F0_Pasa", False) | df.get("F0_Dudoso", False)
    elif "F0_Score" in df.columns:
        mask_eval = df["F0_Score"] > 0
    else:
        mask_eval = pd.Series(True, index=df.index)

    # Ordenar por F0_Score descendente para evaluar primero los más prometedores
    candidates_df = df[mask_eval].copy()
    if "F0_Score" in candidates_df.columns:
        candidates_df = candidates_df.sort_values("F0_Score", ascending=False)
    idx_candidates = candidates_df.index.tolist()

    total_filas = len(idx_candidates)
    total_tasks = total_filas * len(all_cids)
    completed = 0

    reporte_criterios: dict[str, dict] = {}
    for cid in all_cids:
        reporte_criterios[cid] = {"cumple": 0, "no_cumple": 0, "error": 0}

    for i, idx in enumerate(idx_candidates):
        if skip_evaluated:
            ya_evaluado = all(
                df.at[idx, f"F1_{cid}_justificacion"] != "" or df.at[idx, f"F1_{cid}_cumple"] == True
                for cid in all_cids
            )
            if ya_evaluado:
                completed += len(all_cids)
                if progress_callback:
                    progress_callback(completed, total_tasks)
                continue

        titulo_raw = str(df.at[idx, "Titulo"]) if "Titulo" in df.columns else ""
        abstract_raw = str(df.at[idx, "Abstract"]) if "Abstract" in df.columns else ""
        keywords_raw = str(df.at[idx, "Keywords"]) if "Keywords" in df.columns else ""

        titulo, abstract = _truncar_registro(titulo_raw, abstract_raw, max_chars_abstract)

        resultados_fila: dict[str, dict] = {}
        error_en_fila = False

        for cid in all_cids:
            config = inclusion_cfg.get(cid) or exclusion_cfg.get(cid)
            if config is None:
                continue

            prompt = _build_prompt_criterio(titulo, abstract, keywords_raw, cid, config)

            t0 = time.time()
            try:
                if log_callback:
                    log_callback(f"🔄 Fila {idx} | {cid} ...")

                parsed = ollama_chat_with_retry(
                    endpoint, model, prompt,
                    max_retries=2, delay=delay, options=OLLAMA_OPTIONS_CRITERIO,
                )
                cumple = bool(parsed.get("cumple", False))
                confianza = int(parsed.get("confianza", 0))
                justificacion = str(parsed.get("justificacion", ""))
                evidencia = str(parsed.get("evidencia", ""))

                df.at[idx, f"F1_{cid}_cumple"] = cumple
                df.at[idx, f"F1_{cid}_confianza"] = confianza
                df.at[idx, f"F1_{cid}_justificacion"] = justificacion
                df.at[idx, f"F1_{cid}_evidencia"] = evidencia

                if cumple:
                    reporte_criterios[cid]["cumple"] += 1
                else:
                    reporte_criterios[cid]["no_cumple"] += 1

                resultados_fila[cid] = {"cumple": cumple, "confianza": confianza}
                dur = time.time() - t0
                if log_callback:
                    icon = "✅" if cumple else "❌"
                    log_callback(f"{icon} Fila {idx} | {cid} → cumple={cumple} conf={confianza} ({dur:.1f}s)")

            except Exception as exc:
                df.at[idx, f"F1_{cid}_cumple"] = False
                df.at[idx, f"F1_{cid}_confianza"] = 0
                df.at[idx, f"F1_{cid}_justificacion"] = f"ERROR: {exc}"
                df.at[idx, f"F1_{cid}_evidencia"] = ""
                reporte_criterios[cid]["error"] += 1
                error_en_fila = True
                resultados_fila[cid] = {"cumple": False, "confianza": 0}
                if log_callback:
                    log_callback(f"❌ Fila {idx} | {cid} → ERROR: {exc}")

            completed += 1
            if progress_callback:
                progress_callback(completed, total_tasks)

            if delay > 0 and completed < total_tasks:
                time.sleep(delay)

        inclusion_cumple = all(resultados_fila.get(cid, {}).get("cumple", False) for cid in inclusion_cfg)
        exclusiones_activas = [cid for cid in exclusion_cfg if resultados_fila.get(cid, {}).get("cumple", False)]
        exclusion_cumple = len(exclusiones_activas) > 0
        score_pi = sum(resultados_fila.get(cid, {}).get("confianza", 0) for cid in inclusion_cfg)

        num_exclusiones = len(exclusiones_activas)
        max_conf_exclusion = max(
            [resultados_fila[cid]["confianza"] for cid in exclusiones_activas],
            default=0
        )

        if num_exclusiones >= 3:
            df.at[idx, "F1_Decision"] = "DUDOSO"
            df.at[idx, "F1_CriterioExclusion"] = f"INCONSISTENTE:{','.join(exclusiones_activas)}"
        elif exclusion_cumple and max_conf_exclusion >= 4:
            df.at[idx, "F1_Decision"] = "EXCLUIR"
            df.at[idx, "F1_CriterioExclusion"] = exclusiones_activas[0]
        elif exclusion_cumple:
            df.at[idx, "F1_Decision"] = "DUDOSO"
            df.at[idx, "F1_CriterioExclusion"] = f"DUDOSO:{exclusiones_activas[0]}"
        elif inclusion_cumple:
            df.at[idx, "F1_Decision"] = "INCLUIR"
            df.at[idx, "F1_CriterioExclusion"] = ""
        else:
            df.at[idx, "F1_Decision"] = "DUDOSO"
            df.at[idx, "F1_CriterioExclusion"] = ""

        df.at[idx, "F1_Score_PI"] = float(score_pi)
        df.at[idx, "F1_Error"] = error_en_fila

    reporte = {
        "total_evaluadas": total_filas,
        "incluir": int((df["F1_Decision"] == "INCLUIR").sum()),
        "excluir": int((df["F1_Decision"] == "EXCLUIR").sum()),
        "dudoso": int((df["F1_Decision"] == "DUDOSO").sum()),
        "errores": int(df["F1_Error"].sum()),
        "por_criterio": reporte_criterios,
    }

    return df, reporte


# ---------------------------------------------------------------------------
# Nuevos Prompts para F1 (scoring 0-2 inclusión, 0-1 exclusión)
# ---------------------------------------------------------------------------

def _build_prompt_inclusion(titulo: str, abstract: str, cid: str, config: dict) -> str:
    """Prompt para evaluar un criterio de inclusión con score 0/1/2."""
    nombre = config["nombre"]
    descripcion = config["descripcion"]
    return f"""You are a strict scientific screening assistant for scoping reviews.
Your task is to evaluate ONE INCLUSION criterion for one bibliographic record.
Be highly conservative. Do NOT infer missing details.

RECORD:
Title: {titulo}
Abstract: {abstract}

INCLUSION CRITERION: {nombre}
DESCRIPTION: {descripcion}

INSTRUCTIONS:
1. Read the title and abstract carefully.
2. Score how strongly this criterion applies to the study:
   - 2 = The criterion is EXACTLY met / central to the study's main focus.
   - 1 = The criterion is mentioned or applies SECONDARILY / tangentially.
   - 0 = The criterion does NOT apply / is absent.
3. Do NOT guess. If unsure, score 0.
4. Be conservative: when in doubt, say 0.

Respond ONLY in strict JSON with no markdown, no code blocks, no extra text:
{{
  "score": 0 or 1 or 2,
  "justificacion": "one short sentence in Spanish explaining the score"
}}
""".strip()


def _build_prompt_exclusion(titulo: str, abstract: str, cid: str, config: dict) -> str:
    """Prompt para evaluar un criterio de exclusión con score 0/1."""
    nombre = config["nombre"]
    descripcion = config["descripcion"]
    return f"""You are a strict scientific screening assistant for scoping reviews.
Your task is to evaluate ONE EXCLUSION criterion for one bibliographic record.
Be highly conservative. Do NOT infer missing details.

RECORD:
Title: {titulo}
Abstract: {abstract}

EXCLUSION CRITERION: {nombre}
DESCRIPTION: {descripcion}

INSTRUCTIONS:
1. Read the title and abstract carefully.
2. Score whether this exclusion criterion applies:
   - 1 = The study CLEARLY matches this exclusion criterion (e.g., explicit mention of excluded topics).
   - 0 = The study does NOT match this exclusion criterion.
3. Only score 1 if there is CLEAR evidence. If only mentioned in passing or unclear → 0.
4. Be conservative: do NOT exclude unless clearly proven.

Respond ONLY in strict JSON with no markdown, no code blocks, no extra text:
{{
  "score": 0 or 1,
  "justificacion": "one short sentence in Spanish explaining the score"
}}
""".strip()


# ---------------------------------------------------------------------------
# Fase 1-Inclusión: Evaluación con scoring 0-2
# ---------------------------------------------------------------------------

def fase1_evaluar_inclusion(
    df: pd.DataFrame,
    llm_config: dict,
    delay: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    prompt_callback: Callable[[str], None] | None = None,
    skip_evaluated: bool = True,
    max_chars_abstract: int = 300,
) -> tuple[pd.DataFrame, dict]:
    """
    Evalúa los 4 criterios de inclusión (I1-I4) con scoring 0/1/2.
    Genera columnas F1_I{ N }_score y F1_I{ N }_justificacion.
    Columna agregada: F1_Inclusion_Total.
    """
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")
    df = df.copy()

    inclusion_cfg, _ = cargar_criterios_dinamicos()
    inclusion_ids = list(inclusion_cfg.keys())
    for cid in inclusion_ids:
        for suffix in ["score", "justificacion"]:
            col = f"F1_{cid}_{suffix}"
            default = 0 if suffix == "score" else ""
            if col not in df.columns:
                df[col] = default

    if "F1_Inclusion_Total" not in df.columns:
        df["F1_Inclusion_Total"] = 0

    # Candidatos: todos los registros (o los que tengan F0_Score > 0 si existe)
    if "F0_Score" in df.columns:
        mask = df["F0_Score"] > 0
    else:
        mask = pd.Series(True, index=df.index)
    candidates_df = df[mask].copy()
    if "F0_Score" in candidates_df.columns:
        candidates_df = candidates_df.sort_values("F0_Score", ascending=False)
    idx_candidates = candidates_df.index.tolist()

    total = len(idx_candidates)
    completed = 0
    reporte = {cid: {"evaluadas": 0, "score_2": 0, "score_1": 0, "score_0": 0, "error": 0} for cid in inclusion_ids}

    for idx in idx_candidates:
        if skip_evaluated:
            ya_evaluado = all(
                df.at[idx, f"F1_{cid}_justificacion"] != "" or df.at[idx, f"F1_{cid}_score"] != 0
                for cid in inclusion_ids
            )
            if ya_evaluado:
                completed += len(inclusion_ids)
                if progress_callback:
                    progress_callback(completed, total * len(inclusion_ids))
                continue

        titulo_raw = str(df.at[idx, "Titulo"]) if "Titulo" in df.columns else ""
        abstract_raw = str(df.at[idx, "Abstract"]) if "Abstract" in df.columns else ""
        titulo, abstract = _truncar_registro(titulo_raw, abstract_raw, max_chars_abstract)

        for cid in inclusion_ids:
            config = inclusion_cfg[cid]
            prompt = _build_prompt_inclusion(titulo, abstract, cid, config)

            try:
                if prompt_callback:
                    prompt_callback(prompt)
                if log_callback:
                    log_callback(f"🔄 Fila {idx} | {cid} ...")
                parsed = ollama_chat_with_retry(
                    endpoint, model, prompt,
                    max_retries=2, delay=delay, options=OLLAMA_OPTIONS_CRITERIO,
                )
                score = int(parsed.get("score", 0))
                justif = str(parsed.get("justificacion", ""))
                df.at[idx, f"F1_{cid}_score"] = score
                df.at[idx, f"F1_{cid}_justificacion"] = justif
                reporte[cid]["evaluadas"] += 1
                reporte[cid][f"score_{score}"] += 1
                if log_callback:
                    log_callback(f"✅ Fila {idx} | {cid} → score={score}")
            except Exception as exc:
                df.at[idx, f"F1_{cid}_score"] = 0
                df.at[idx, f"F1_{cid}_justificacion"] = f"ERROR: {exc}"
                reporte[cid]["error"] += 1
                if log_callback:
                    log_callback(f"❌ Fila {idx} | {cid} → ERROR: {exc}")

            completed += 1
            if progress_callback:
                progress_callback(completed, total * len(inclusion_ids))
            if delay > 0 and completed < total * len(inclusion_ids):
                time.sleep(delay)

        # Recalcular total de inclusión para esta fila
        total_inc = sum(int(df.at[idx, f"F1_{cid}_score"]) for cid in inclusion_ids)
        df.at[idx, "F1_Inclusion_Total"] = total_inc

    return df, reporte


# ---------------------------------------------------------------------------
# Fase 1-Exclusión: Evaluación con scoring 0/1
# ---------------------------------------------------------------------------

def fase1_evaluar_exclusion(
    df: pd.DataFrame,
    llm_config: dict,
    delay: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    prompt_callback: Callable[[str], None] | None = None,
    skip_evaluated: bool = True,
    max_chars_abstract: int = 300,
) -> tuple[pd.DataFrame, dict]:
    """
    Evalúa los 9 criterios de exclusión (E1-E9) con scoring 0/1.
    Genera columnas F1_E{ N }_score y F1_E{ N }_justificacion.
    Columna agregada: F1_Exclusion_Total.
    """
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")
    df = df.copy()

    _, exclusion_cfg = cargar_criterios_dinamicos()
    exclusion_ids = list(exclusion_cfg.keys())
    for cid in exclusion_ids:
        for suffix in ["score", "justificacion"]:
            col = f"F1_{cid}_{suffix}"
            default = 0 if suffix == "score" else ""
            if col not in df.columns:
                df[col] = default

    if "F1_Exclusion_Total" not in df.columns:
        df["F1_Exclusion_Total"] = 0

    # Candidatos: todos (o los con F0_Score > 0)
    if "F0_Score" in df.columns:
        mask = df["F0_Score"] > 0
    else:
        mask = pd.Series(True, index=df.index)
    candidates_df = df[mask].copy()
    if "F0_Score" in candidates_df.columns:
        candidates_df = candidates_df.sort_values("F0_Score", ascending=False)
    idx_candidates = candidates_df.index.tolist()

    total = len(idx_candidates)
    completed = 0
    reporte = {cid: {"evaluadas": 0, "score_1": 0, "score_0": 0, "error": 0} for cid in exclusion_ids}

    for idx in idx_candidates:
        if skip_evaluated:
            ya_evaluado = all(
                df.at[idx, f"F1_{cid}_justificacion"] != "" or df.at[idx, f"F1_{cid}_score"] != 0
                for cid in exclusion_ids
            )
            if ya_evaluado:
                completed += len(exclusion_ids)
                if progress_callback:
                    progress_callback(completed, total * len(exclusion_ids))
                continue

        titulo_raw = str(df.at[idx, "Titulo"]) if "Titulo" in df.columns else ""
        abstract_raw = str(df.at[idx, "Abstract"]) if "Abstract" in df.columns else ""
        titulo, abstract = _truncar_registro(titulo_raw, abstract_raw, max_chars_abstract)

        for cid in exclusion_ids:
            config = exclusion_cfg[cid]
            prompt = _build_prompt_exclusion(titulo, abstract, cid, config)

            try:
                if prompt_callback:
                    prompt_callback(prompt)
                if log_callback:
                    log_callback(f"🔄 Fila {idx} | {cid} ...")
                parsed = ollama_chat_with_retry(
                    endpoint, model, prompt,
                    max_retries=2, delay=delay, options=OLLAMA_OPTIONS_CRITERIO,
                )
                score = int(parsed.get("score", 0))
                justif = str(parsed.get("justificacion", ""))
                df.at[idx, f"F1_{cid}_score"] = score
                df.at[idx, f"F1_{cid}_justificacion"] = justif
                reporte[cid]["evaluadas"] += 1
                reporte[cid][f"score_{score}"] += 1
                if log_callback:
                    log_callback(f"✅ Fila {idx} | {cid} → score={score}")
            except Exception as exc:
                df.at[idx, f"F1_{cid}_score"] = 0
                df.at[idx, f"F1_{cid}_justificacion"] = f"ERROR: {exc}"
                reporte[cid]["error"] += 1
                if log_callback:
                    log_callback(f"❌ Fila {idx} | {cid} → ERROR: {exc}")

            completed += 1
            if progress_callback:
                progress_callback(completed, total * len(exclusion_ids))
            if delay > 0 and completed < total * len(exclusion_ids):
                time.sleep(delay)

        # Recalcular total de exclusión para esta fila
        total_exc = sum(int(df.at[idx, f"F1_{cid}_score"]) for cid in exclusion_ids)
        df.at[idx, "F1_Exclusion_Total"] = total_exc

    return df, reporte


# ---------------------------------------------------------------------------
# Gestión de columnas F1
# ---------------------------------------------------------------------------

def fase1_limpiar_inclusion(df: pd.DataFrame) -> pd.DataFrame:
    """Pone a 0/vacío las columnas de inclusión y recalcula F1_Inclusion_Total."""
    df = df.copy()
    inclusion_cfg, _ = cargar_criterios_dinamicos()
    for cid in inclusion_cfg:
        col_score = f"F1_{cid}_score"
        col_just = f"F1_{cid}_justificacion"
        if col_score in df.columns:
            df[col_score] = 0
        if col_just in df.columns:
            df[col_just] = ""
    inclusion_ids = list(inclusion_cfg.keys())
    cols = [f"F1_{cid}_score" for cid in inclusion_ids if f"F1_{cid}_score" in df.columns]
    if cols:
        df["F1_Inclusion_Total"] = df[cols].sum(axis=1)
    else:
        df["F1_Inclusion_Total"] = 0
    return df


def fase1_limpiar_exclusion(df: pd.DataFrame) -> pd.DataFrame:
    """Pone a 0/vacío las columnas de exclusión y recalcula F1_Exclusion_Total."""
    df = df.copy()
    _, exclusion_cfg = cargar_criterios_dinamicos()
    for cid in exclusion_cfg:
        col_score = f"F1_{cid}_score"
        col_just = f"F1_{cid}_justificacion"
        if col_score in df.columns:
            df[col_score] = 0
        if col_just in df.columns:
            df[col_just] = ""
    exclusion_ids = list(exclusion_cfg.keys())
    cols = [f"F1_{cid}_score" for cid in exclusion_ids if f"F1_{cid}_score" in df.columns]
    if cols:
        df["F1_Exclusion_Total"] = df[cols].sum(axis=1)
    else:
        df["F1_Exclusion_Total"] = 0
    return df


def fase1_sumar_inclusion(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcula F1_Inclusion_Total a partir de las columnas de score existentes."""
    df = df.copy()
    inclusion_cfg, _ = cargar_criterios_dinamicos()
    inclusion_ids = list(inclusion_cfg.keys())
    cols = [f"F1_{cid}_score" for cid in inclusion_ids if f"F1_{cid}_score" in df.columns]
    if cols:
        df["F1_Inclusion_Total"] = df[cols].sum(axis=1)
    else:
        df["F1_Inclusion_Total"] = 0
    return df


def fase1_sumar_exclusion(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcula F1_Exclusion_Total a partir de las columnas de score existentes."""
    df = df.copy()
    _, exclusion_cfg = cargar_criterios_dinamicos()
    exclusion_ids = list(exclusion_cfg.keys())
    cols = [f"F1_{cid}_score" for cid in exclusion_ids if f"F1_{cid}_score" in df.columns]
    if cols:
        df["F1_Exclusion_Total"] = df[cols].sum(axis=1)
    else:
        df["F1_Exclusion_Total"] = 0
    return df


def fase1_reiniciar_evaluacion(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina todas las columnas F1_* del DataFrame."""
    df = df.copy()
    cols_a_eliminar = [c for c in df.columns if c.startswith("F1_")]
    if cols_a_eliminar:
        df = df.drop(columns=cols_a_eliminar)
    return df


# ---------------------------------------------------------------------------
# Fase 2: Revisión de Dudosos (contexto completo)
# ---------------------------------------------------------------------------

def fase2_revision_dudosos(
    df_f1: pd.DataFrame,
    llm_config: dict,
    delay: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    skip_evaluated: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Reevalúa con LLM las filas marcadas como DUDOSO en F1.
    Prompt con abstract completo + todos los criterios.
    """
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")

    df = df_f1.copy()

    for col in ["F2_Decision", "F2_Motivo", "F2_ScoreFinal", "F2_Error", "F2_Raw"]:
        if col not in df.columns:
            df[col] = "" if col in ("F2_Decision", "F2_Motivo", "F2_Raw") else (0.0 if col == "F2_ScoreFinal" else False)

    mask_dudoso = df.get("F1_Decision", "") == "DUDOSO"
    idx_candidates = df[mask_dudoso].index.tolist()
    total = len(idx_candidates)

    cambios = {"DUDOSO->INCLUIR": 0, "DUDOSO->EXCLUIR": 0, "DUDOSO->DUDOSO": 0}

    inclusion_cfg, exclusion_cfg = cargar_criterios_dinamicos()
    inclusion_text = "\n".join(
        f"{cid}. {cfg['nombre']}: {cfg['descripcion']}" for cid, cfg in inclusion_cfg.items()
    )
    exclusion_text = "\n".join(
        f"{cid}. {cfg['nombre']}: {cfg['descripcion']}" for cid, cfg in exclusion_cfg.items()
    )

    for i, idx in enumerate(idx_candidates):
        if skip_evaluated and df.at[idx, "F2_Decision"] != "":
            continue

        titulo = str(df.at[idx, "Titulo"]) if "Titulo" in df.columns else ""
        abstract = str(df.at[idx, "Abstract"]) if "Abstract" in df.columns else ""
        keywords = str(df.at[idx, "Keywords"]) if "Keywords" in df.columns else ""

        prompt = f"""You are an expert scoping review reviewer in Computer Science.
This record was marked as BORDERLINE (DUDOSO) in the first screening.
Review it carefully with the full abstract.

RECORD:
Title: {titulo}
Abstract: {abstract}
Keywords: {keywords}

INCLUSION criteria (ALL must be met):
{inclusion_text}

EXCLUSION criteria (ANY excludes):
{exclusion_text}

What is your final decision: INCLUDE, EXCLUDE, or BORDERLINE?
Respond ONLY in strict JSON:
{{"decision": "INCLUDE/EXCLUDE/BORDERLINE", "motivo": "explanation", "score_final": 0-20}}
""".strip()

        t0 = time.time()
        try:
            if log_callback:
                log_callback(f"🔄 Fila {idx} | F2 revisando dudoso ...")

            parsed = ollama_chat_with_retry(
                endpoint, model, prompt,
                max_retries=2, delay=delay,
            )
            decision = str(parsed.get("decision", "BORDERLINE")).upper()
            if decision not in ("INCLUDE", "EXCLUDE", "BORDERLINE"):
                decision = "BORDERLINE"
            motivo = str(parsed.get("motivo", ""))
            score_final = float(parsed.get("score_final", 0))

            df.at[idx, "F2_Decision"] = decision
            df.at[idx, "F2_Motivo"] = motivo
            df.at[idx, "F2_ScoreFinal"] = score_final
            df.at[idx, "F2_Error"] = False
            df.at[idx, "F2_Raw"] = json.dumps(parsed, ensure_ascii=False)

            transicion = f"DUDOSO->{decision}"
            if transicion in cambios:
                cambios[transicion] += 1

            dur = time.time() - t0
            if log_callback:
                log_callback(f"✅ Fila {idx} | F2 → {decision} ({dur:.1f}s)")

        except Exception as exc:
            df.at[idx, "F2_Error"] = True
            df.at[idx, "F2_Motivo"] = f"Error: {exc}"
            df.at[idx, "F2_Raw"] = str(exc)
            if log_callback:
                log_callback(f"❌ Fila {idx} | F2 → ERROR: {exc}")

        if progress_callback:
            progress_callback(i + 1, total)

        if delay > 0 and i < total - 1:
            time.sleep(delay)

    reporte = {
        "total_dudosos": total,
        "cambios": cambios,
        "decisiones_f2": {
            "INCLUDE": int((df["F2_Decision"] == "INCLUDE").sum()),
            "EXCLUDE": int((df["F2_Decision"] == "EXCLUDE").sum()),
            "BORDERLINE": int((df["F2_Decision"] == "BORDERLINE").sum()),
            "ERROR": int(df["F2_Error"].sum()),
        },
    }

    return df, reporte


# ---------------------------------------------------------------------------
# Fase 3: Extracción de datos para PIs
# ---------------------------------------------------------------------------

def fase3_extraccion_pis(
    df_f2: pd.DataFrame,
    llm_config: dict,
    delay: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    skip_evaluated: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Extrae datos estructurados para las 4 PIs de los estudios incluidos.
    Incluidos = F1_Decision=="INCLUIR" OR F2_Decision=="INCLUDE".
    """
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")

    df = df_f2.copy()

    f3_cols = {
        "F3_PI1_responde": False,
        "F3_PI1_modelo": "",
        "F3_PI1_descripcion": "",
        "F3_PI1_tipo": "",
        "F3_PI2_responde": False,
        "F3_PI2_artefacto": "",
        "F3_PI2_tecnologias": "",
        "F3_PI2_plataforma": "",
        "F3_PI3_responde": False,
        "F3_PI3_tipo_estudio": "",
        "F3_PI3_contexto": "",
        "F3_PI3_metricas": "",
        "F3_PI3_participantes": 0,
        "F3_PI4_responde": False,
        "F3_PI4_trabajos_futuros": "",
        "F3_PI4_limitaciones": "",
        "F3_CQ_definicion": "",
        "F3_metricas_CQ": "",
        "F3_modalidades": "",
        "F3_Error": False,
        "F3_Raw": "",
    }
    for col, default in f3_cols.items():
        if col not in df.columns:
            df[col] = default

    mask_incluido = (
        (df.get("F1_Decision", "") == "INCLUIR") |
        (df.get("F2_Decision", "") == "INCLUDE")
    )
    idx_candidates = df[mask_incluido].index.tolist()
    total = len(idx_candidates)

    reporte_pis = {"PI1": 0, "PI2": 0, "PI3": 0, "PI4": 0}

    for i, idx in enumerate(idx_candidates):
        if skip_evaluated and df.at[idx, "F3_PI1_modelo"] != "":
            continue

        titulo = str(df.at[idx, "Titulo"]) if "Titulo" in df.columns else ""
        abstract = str(df.at[idx, "Abstract"]) if "Abstract" in df.columns else ""
        keywords = str(df.at[idx, "Keywords"]) if "Keywords" in df.columns else ""

        prompt = f"""You are an expert data extractor for scoping reviews.
Extract structured information from this INCLUDED study about collaboration quality measurement in co-located face-to-face settings.

TITLE: {titulo}
ABSTRACT: {abstract}
KEYWORDS: {keywords}

Respond ONLY in strict JSON:
{{
  "PI1_modelos": {{"responde": true, "modelo": "name", "descripcion": "text", "tipo": "framework/metric/algorithm/other"}},
  "PI2_implementacion": {{"responde": true, "artefacto": "name", "tecnologias": ["sensor", "CV", "ML"], "plataforma": "text"}},
  "PI3_evaluacion": {{"responde": true, "tipo_estudio": "experimental/survey/case", "contexto": "classroom/simulation/office", "metricas": ["list"], "participantes": 0}},
  "PI4_futuros": {{"responde": true, "trabajos_futuros": ["list"], "limitaciones": ["list"]}},
  "calidad_colaboracion_definicion": "how they define CQ",
  "metricas_cq": ["list of CQ metrics"],
  "modalidades_datos": ["audio", "video", "position", "physiological"]
}}
""".strip()

        t0 = time.time()
        try:
            if log_callback:
                log_callback(f"🔄 Fila {idx} | F3 extrayendo PIs ...")

            parsed = ollama_chat_with_retry(
                endpoint, model, prompt,
                max_retries=2, delay=delay,
            )

            pi1 = parsed.get("PI1_modelos", {})
            pi2 = parsed.get("PI2_implementacion", {})
            pi3 = parsed.get("PI3_evaluacion", {})
            pi4 = parsed.get("PI4_futuros", {})

            df.at[idx, "F3_PI1_responde"] = bool(pi1.get("responde", False))
            df.at[idx, "F3_PI1_modelo"] = str(pi1.get("modelo", ""))
            df.at[idx, "F3_PI1_descripcion"] = str(pi1.get("descripcion", ""))
            df.at[idx, "F3_PI1_tipo"] = str(pi1.get("tipo", ""))

            df.at[idx, "F3_PI2_responde"] = bool(pi2.get("responde", False))
            df.at[idx, "F3_PI2_artefacto"] = str(pi2.get("artefacto", ""))
            techs = pi2.get("tecnologias", [])
            df.at[idx, "F3_PI2_tecnologias"] = ", ".join(techs) if isinstance(techs, list) else str(techs)
            df.at[idx, "F3_PI2_plataforma"] = str(pi2.get("plataforma", ""))

            df.at[idx, "F3_PI3_responde"] = bool(pi3.get("responde", False))
            df.at[idx, "F3_PI3_tipo_estudio"] = str(pi3.get("tipo_estudio", ""))
            df.at[idx, "F3_PI3_contexto"] = str(pi3.get("contexto", ""))
            metrics = pi3.get("metricas", [])
            df.at[idx, "F3_PI3_metricas"] = ", ".join(metrics) if isinstance(metrics, list) else str(metrics)
            part = pi3.get("participantes", 0)
            df.at[idx, "F3_PI3_participantes"] = int(part) if part else 0

            df.at[idx, "F3_PI4_responde"] = bool(pi4.get("responde", False))
            tf = pi4.get("trabajos_futuros", [])
            df.at[idx, "F3_PI4_trabajos_futuros"] = ", ".join(tf) if isinstance(tf, list) else str(tf)
            lim = pi4.get("limitaciones", [])
            df.at[idx, "F3_PI4_limitaciones"] = ", ".join(lim) if isinstance(lim, list) else str(lim)

            df.at[idx, "F3_CQ_definicion"] = str(parsed.get("calidad_colaboracion_definicion", ""))
            mcq = parsed.get("metricas_cq", [])
            df.at[idx, "F3_metricas_CQ"] = ", ".join(mcq) if isinstance(mcq, list) else str(mcq)
            mods = parsed.get("modalidades_datos", [])
            df.at[idx, "F3_modalidades"] = ", ".join(mods) if isinstance(mods, list) else str(mods)

            df.at[idx, "F3_Error"] = False
            df.at[idx, "F3_Raw"] = json.dumps(parsed, ensure_ascii=False)

            if df.at[idx, "F3_PI1_responde"]: reporte_pis["PI1"] += 1
            if df.at[idx, "F3_PI2_responde"]: reporte_pis["PI2"] += 1
            if df.at[idx, "F3_PI3_responde"]: reporte_pis["PI3"] += 1
            if df.at[idx, "F3_PI4_responde"]: reporte_pis["PI4"] += 1

            dur = time.time() - t0
            if log_callback:
                log_callback(f"✅ Fila {idx} | F3 → extraído ({dur:.1f}s)")

        except Exception as exc:
            df.at[idx, "F3_Error"] = True
            df.at[idx, "F3_Raw"] = str(exc)
            if log_callback:
                log_callback(f"❌ Fila {idx} | F3 → ERROR: {exc}")

        if progress_callback:
            progress_callback(i + 1, total)

        if delay > 0 and i < total - 1:
            time.sleep(delay)

    reporte = {
        "total_extraidos": total,
        "por_pi": reporte_pis,
    }

    return df, reporte
