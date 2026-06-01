"""Utilidades de persistencia atómica en Excel."""

import os
import re
import shutil
from pathlib import Path

import pandas as pd


OUTPUT_FOLDER = Path("output")
MASTER_FILENAME = "scoping_master.xlsx"
INVALID_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def clean_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina caracteres de control inválidos para XML/Excel."""
    df_clean = df.copy()
    for col in df_clean.columns:
        if df_clean[col].dtype == object:
            df_clean[col] = df_clean[col].apply(
                lambda x: INVALID_XML_RE.sub("", str(x)) if isinstance(x, str) else x
            )
    return df_clean


def atomic_save_excel(df: pd.DataFrame, output_path: Path) -> Path:
    """Guarda DataFrame en Excel con escritura atómica (.tmp -> rename)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output_path.with_suffix(".tmp.xlsx")
    clean_for_excel(df).to_excel(temp_file, index=False)
    if temp_file.exists():
        if output_path.exists():
            try:
                os.replace(str(temp_file), str(output_path))
            except Exception:
                shutil.move(str(temp_file), str(output_path))
        else:
            temp_file.rename(output_path)
    return output_path


def save_master_dataframe(df, output_folder=OUTPUT_FOLDER, filename=MASTER_FILENAME):
    """Guarda el DataFrame maestro en Excel de forma atómica."""
    output_folder = Path(output_folder)
    output_file = output_folder / filename
    atomic_save_excel(df, output_file)
    return output_file


def load_master_dataframe(path=OUTPUT_FOLDER / MASTER_FILENAME, normalized_columns=None):
    """Carga el DataFrame maestro desde Excel, asegurando columnas base."""
    path = Path(path)
    if not path.exists():
        if normalized_columns:
            return pd.DataFrame(columns=normalized_columns)
        return pd.DataFrame()

    try:
        df = pd.read_excel(path)
    except Exception as e:
        raise RuntimeError(
            f"El archivo '{path.name}' está dañado o incompleto (se interrumpió la escritura). "
            f"Puedes recuperarlo desde tu Git o volver a procesar tu carpeta de origen. Error original: {e}"
        )

    if normalized_columns:
        for col in normalized_columns:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].astype(object)

        existing_cols = list(df.columns)
        ordered_base_cols = [col for col in normalized_columns if col in existing_cols]
        extra_cols = [col for col in existing_cols if col not in normalized_columns]
        return df[ordered_base_cols + extra_cols]

    return df
