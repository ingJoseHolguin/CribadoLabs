"""Gestión de columnas dinámicas de criterios y puntuaciones."""

import re

import pandas as pd


TOTAL_SCORE_COLUMN = "Total Score"


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


def rebuild_criteria_columns(df, criteria, keywords):
    """Reconstruye las columnas de criterios y keywords sobre el DataFrame base.

    Retorna un nuevo DataFrame con las columnas sincronizadas.
    """
    # 1. Conservar valores de palabras clave existentes
    existing_kw_title = {}
    existing_kw_abstract = {}

    for column in df.columns:
        match_kw_title = re.match(r"^KW_Titulo:\s*(.+)$", column)
        if match_kw_title:
            kw = match_kw_title.group(1).strip()
            existing_kw_title[kw] = df[column].copy()

        match_kw_abs = re.match(r"^KW_Abstract:\s*(.+)$", column)
        if match_kw_abs:
            kw = match_kw_abs.group(1).strip()
            existing_kw_abstract[kw] = df[column].copy()

    # Mapeos basados en el TEXTO del criterio
    existing_responses = {}
    existing_subscores = {
        "Semantic": {},
        "Context": {},
        "Centrality": {},
        "Evidence": {},
        "Penalty": {},
        "Total": {}
    }

    text_to_old_index = {}
    for column in df.columns:
        match_resp = re.match(r"^(?:Criterio\s+)?(C\d+)\s+Respuesta:\s*(.+)$", column)
        if match_resp:
            c_index, criterion_text = match_resp.groups()
            criterion_text = criterion_text.strip()
            existing_responses[criterion_text] = df[column].copy()
            text_to_old_index[criterion_text] = c_index

    for col_type in ["Semantic", "Context", "Centrality", "Evidence", "Penalty", "Total"]:
        for column in df.columns:
            match_sub = re.match(
                r"^(?:Criterio\s+)?(C\d+)\s+" + col_type + r"(?::.*)?$",
                column, re.IGNORECASE
            )
            if match_sub:
                c_index = match_sub.group(1)
                for txt, old_idx in text_to_old_index.items():
                    if old_idx == c_index:
                        existing_subscores[col_type][txt] = df[column].copy()
                        break

    base_columns = [
        column
        for column in df.columns
        if not re.match(r"^(?:C\d+|Criterio\s+C\d+)\s+", column)
           and not re.match(r"^KW_(?:Titulo|Abstract):\s*", column)
           and column != TOTAL_SCORE_COLUMN
    ]
    df = df[base_columns].copy()

    # Escribir columnas de palabras clave
    for keyword in keywords:
        kw = keyword.strip()
        col_title = f"KW_Titulo: {kw}"
        col_abstract = f"KW_Abstract: {kw}"

        df[col_title] = existing_kw_title.get(kw, "")
        df[col_abstract] = existing_kw_abstract.get(kw, "")
        df[col_title] = df[col_title].astype("object")
        df[col_abstract] = df[col_abstract].astype("object")

    # Escribir columnas de criterios
    for index, criterion in enumerate(criteria, start=1):
        c_index = f"C{index}"
        criterion_text = criterion.get("text", "").strip()

        response_col = f"{c_index} Respuesta: {criterion_text}"
        df[response_col] = existing_responses.get(criterion_text, "")
        df[response_col] = df[response_col].astype("object")

        for col_type in ["Semantic", "Context", "Centrality", "Evidence", "Penalty", "Total"]:
            col_name = f"{c_index} {col_type}"
            if criterion_text in existing_subscores[col_type]:
                df[col_name] = pd.to_numeric(
                    existing_subscores[col_type][criterion_text], errors="coerce"
                ).fillna(0)
            else:
                df[col_name] = 0

    update_total_score(df)
    return df
