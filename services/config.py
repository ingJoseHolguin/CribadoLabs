"""Carga y guarda de archivos de configuración JSON."""

import json
from pathlib import Path

CONFIG_FOLDER = Path("config")
CRITERIA_FILE = CONFIG_FOLDER / "criteria.json"
KEYWORDS_FILE = CONFIG_FOLDER / "keywords.json"
LLM_CONFIG_FILE = CONFIG_FOLDER / "llm_config.json"


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
