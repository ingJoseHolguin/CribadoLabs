"""Cliente LLM único para Ollama local."""

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any


def ollama_chat(endpoint: str, model: str, prompt: str, options: dict | None = None, force_json: bool = True) -> str:
    """Envía un prompt a Ollama y retorna el texto de respuesta."""
    default_options = {
        "num_ctx": 4096,
        "temperature": 0.0,
        "top_p": 0.0,
        "repeat_penalty": 1.0,
        "num_predict": 1024,
    }
    opts = options if options is not None else default_options

    endpoint = endpoint.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": opts,
    }
    if force_json:
        payload["format"] = "json"
    request = urllib.request.Request(
        f"{endpoint}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body.get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(
                "HTTP 401 Unauthorized: Ollama rechazó la petición. "
                "Verifica que Ollama esté ejecutándose sin autenticación (ollama serve) "
                "o que el endpoint en la pestaña LLM sea correcto. "
                f"Error: {e.read().decode('utf-8', errors='ignore')}"
            ) from e
        raise


def extract_json_response(text: str) -> dict[str, Any]:
    """Extrae JSON de la respuesta del LLM, tolerando truncamientos."""
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


def ollama_chat_with_retry(
    endpoint: str,
    model: str,
    prompt: str,
    max_retries: int = 2,
    delay: float = 1.0,
    options: dict | None = None,
) -> dict[str, Any]:
    """Llama al LLM, reintenta ante fallo y retorna el JSON parseado."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            raw = ollama_chat(endpoint, model, prompt, options=options)
            return extract_json_response(raw)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(delay * (attempt + 1))
    raise last_error


def fetch_ollama_models(endpoint: str) -> list[str]:
    """Obtiene la lista de modelos disponibles en Ollama."""
    try:
        endpoint = endpoint.rstrip("/")
        request = urllib.request.Request(f"{endpoint}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        return [model["name"] for model in body.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Prompt builders para evaluación por criterio (pestaña LLM)
# ---------------------------------------------------------------------------

def build_semantic_match_prompt(title: str, abstract: str, criterion: str) -> str:
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


def build_centrality_prompt(title: str, abstract: str, criterion: str) -> str:
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


def build_exclusion_penalty_prompt(title: str, abstract: str, criterion: str) -> str:
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


def evaluate_row_criterion(endpoint: str, model: str, title: str, abstract: str, criterion_id: str, criterion: str) -> dict:
    """Evalúa una fila contra un criterio usando 3 consultas al LLM."""
    # Consulta 1: Semantic Match
    p_sem = build_semantic_match_prompt(title, abstract, criterion)
    r_sem = ollama_chat(endpoint, model, p_sem)
    try:
        parsed_sem = extract_json_response(r_sem)
        semantic = int(parsed_sem.get("score", 0))
        semantic_reason = str(parsed_sem.get("reason", "")).strip()
    except Exception as e:
        semantic = 0
        semantic_reason = f"Error: {e}. Respuesta cruda: {r_sem}"

    # Consulta 2: Centrality
    p_cen = build_centrality_prompt(title, abstract, criterion)
    r_cen = ollama_chat(endpoint, model, p_cen)
    try:
        parsed_cen = extract_json_response(r_cen)
        centrality = int(parsed_cen.get("score", 0))
        centrality_reason = str(parsed_cen.get("reason", "")).strip()
    except Exception as e:
        centrality = 0
        centrality_reason = f"Error: {e}. Respuesta cruda: {r_cen}"

    # Consulta 3: Exclusion Penalty
    p_pen = build_exclusion_penalty_prompt(title, abstract, criterion)
    r_pen = ollama_chat(endpoint, model, p_pen)
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
