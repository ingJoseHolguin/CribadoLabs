"""Carga y guarda de archivos de configuración JSON."""

import json
from pathlib import Path

CONFIG_FOLDER = Path("config")
CRITERIA_FILE = CONFIG_FOLDER / "criteria.json"
KEYWORDS_FILE = CONFIG_FOLDER / "keywords.json"
LLM_CONFIG_FILE = CONFIG_FOLDER / "llm_config.json"
SEARCH_QUERIES_FILE = CONFIG_FOLDER / "search_queries.json"
MANUAL_SCREENING_STATE_FILE = CONFIG_FOLDER / "manual_screening_state.json"
TELEGRAM_CONFIG_FILE = CONFIG_FOLDER / "telegram_config.json"


def load_criteria():
    if not CRITERIA_FILE.exists():
        return []
    try:
        with open(CRITERIA_FILE, "r", encoding="utf-8") as f:
            criteria = json.load(f)
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
    with open(CRITERIA_FILE, "w", encoding="utf-8") as f:
        json.dump(criteria, f, indent=2, ensure_ascii=False)


def load_keywords():
    if not KEYWORDS_FILE.exists():
        return []
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            keywords = json.load(f)
            if isinstance(keywords, list):
                return [str(kw) for kw in keywords]
            return []
    except (OSError, json.JSONDecodeError):
        return []


def save_keywords(keywords):
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(keywords, f, indent=2, ensure_ascii=False)


def load_llm_config():
    """Carga configuración LLM. Soporta JSON antiguo con provider/api_key."""
    default = {"endpoint": "http://localhost:11434", "model": "llama3.1"}
    if not LLM_CONFIG_FILE.exists():
        return default
    try:
        with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default

    return {
        "endpoint": config.get("endpoint", "http://localhost:11434"),
        "model": config.get("model", "llama3.1"),
    }


def save_llm_config(endpoint, model):
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(LLM_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"endpoint": endpoint, "model": model}, f, indent=2)


def load_search_queries():
    """Carga el diccionario de cadenas de búsqueda por fuente o archivo."""
    if not SEARCH_QUERIES_FILE.exists():
        return {}
    try:
        with open(SEARCH_QUERIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
            return {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_search_queries(queries):
    """Guarda el diccionario de cadenas de búsqueda por fuente o archivo."""
    CONFIG_FOLDER.mkdir(exist_ok=True)
    with open(SEARCH_QUERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(queries, f, indent=2, ensure_ascii=False)


def load_manual_screening_state():
    """Carga el estado del progreso de selección manual (último registro revisado, filtros)."""
    default = {
        "last_index": 0,
        "last_doi": "",
        "last_titulo": "",
        "last_decision": 0,
        "sort_by": "F0_Score (Mayor a menor)",
        "filter_by": "Todos los registros",
        "auto_advance": True,
    }
    if not MANUAL_SCREENING_STATE_FILE.exists():
        return default
    try:
        with open(MANUAL_SCREENING_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {**default, **data}
            return default
    except (OSError, json.JSONDecodeError):
        return default


def save_manual_screening_state(state):
    """Persiste el estado actual de la selección manual en JSON."""
    CONFIG_FOLDER.mkdir(exist_ok=True)
    try:
        with open(MANUAL_SCREENING_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def load_telegram_config():
    """Carga configuración del bot de Telegram para cribado manual."""
    default = {
        "bot_token": "",
        "allowed_chat_ids": [],
        "auto_advance": True,
        "auto_send_audio": False,
        "show_abstract": True,
        "default_lang": "es",
        "tts_voice": "es-ES-ElviraNeural",
        "is_enabled": False,
    }
    if not TELEGRAM_CONFIG_FILE.exists():
        return default
    try:
        with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {**default, **data}
            return default
    except (OSError, json.JSONDecodeError):
        return default


def save_telegram_config(config):
    """Persiste configuración del bot de Telegram en JSON."""
    CONFIG_FOLDER.mkdir(exist_ok=True)
    try:
        with open(TELEGRAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


