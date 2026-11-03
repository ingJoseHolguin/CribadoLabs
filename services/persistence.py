"""Utilidades de persistencia atómica en Excel con tolerancia a fallos y autorreparación."""

import io
import logging
import os
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_FOLDER = Path("output")
MASTER_FILENAME = "scoping_master.xlsx"
INVALID_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

# Lock global re-entrante para evitar colisiones de lectura/escritura entre hilos (Streamlit y Telegram)
GLOBAL_EXCEL_LOCK = threading.RLock()


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
    """Guarda DataFrame en Excel con escritura atómica, nombres temporales únicos y copia de respaldo (.bak)."""
    with GLOBAL_EXCEL_LOCK:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        unique_token = f"{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
        temp_file = output_path.with_name(f"{output_path.stem}_{unique_token}.tmp.xlsx")

        try:
            clean_for_excel(df).to_excel(temp_file, index=False, engine="openpyxl")
            if temp_file.exists() and temp_file.stat().st_size > 0:
                # Si el archivo destino ya existe y tiene contenido válido, guardar copia de seguridad
                if output_path.exists() and output_path.stat().st_size > 1000:
                    backup_file = output_path.with_suffix(".bak.xlsx")
                    try:
                        shutil.copy2(str(output_path), str(backup_file))
                    except Exception as e:
                        logger.warning(f"No se pudo crear backup de {output_path.name}: {e}")

                # Reemplazo atómico del archivo
                try:
                    os.replace(str(temp_file), str(output_path))
                except Exception:
                    shutil.move(str(temp_file), str(output_path))
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

        return output_path


def atomic_save_excel_multisheet(sheets: dict[str, pd.DataFrame], output_path: Path) -> Path:
    """Guarda múltiples DataFrames como hojas en un solo Excel con escritura atómica."""
    with GLOBAL_EXCEL_LOCK:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        unique_token = f"{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
        temp_file = output_path.with_name(f"{output_path.stem}_{unique_token}.tmp.xlsx")

        try:
            with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
                for sheet_name, df in sheets.items():
                    clean_for_excel(df).to_excel(writer, sheet_name=sheet_name, index=False)

            if temp_file.exists() and temp_file.stat().st_size > 0:
                if output_path.exists() and output_path.stat().st_size > 1000:
                    backup_file = output_path.with_suffix(".bak.xlsx")
                    try:
                        shutil.copy2(str(output_path), str(backup_file))
                    except Exception:
                        pass
                try:
                    os.replace(str(temp_file), str(output_path))
                except Exception:
                    shutil.move(str(temp_file), str(output_path))
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

        return output_path


def save_master_dataframe(df, output_folder=OUTPUT_FOLDER, filename=MASTER_FILENAME):
    """Guarda el DataFrame maestro en Excel de forma atómica y segura."""
    output_folder = Path(output_folder)
    output_file = output_folder / filename
    atomic_save_excel(df, output_file)
    return output_file


def _attempt_repair_excel(path: Path) -> Optional[pd.DataFrame]:
    """Intenta autorreparar un archivo Excel con entradas zip corruptas (ej. Bad CRC en theme1.xml u otras metadatas)."""
    try:
        import openpyxl

        path = Path(path)
        if not path.exists():
            return None

        with zipfile.ZipFile(path, "r") as z_in:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z_out:
                for item in z_in.infolist():
                    try:
                        data = z_in.read(item.filename)
                        z_out.writestr(item.filename, data)
                    except Exception as e:
                        logger.warning(f"Entrada zip dañada en {path.name}: {item.filename} ({e}). Reparando...")
                        if "theme" in item.filename:
                            try:
                                tmp_wb = openpyxl.Workbook()
                                tmp_buf = io.BytesIO()
                                tmp_wb.save(tmp_buf)
                                tmp_buf.seek(0)
                                with zipfile.ZipFile(tmp_buf, "r") as z_theme:
                                    theme_data = z_theme.read("xl/theme/theme1.xml")
                                z_out.writestr(item.filename, theme_data)
                            except Exception:
                                pass
            buf.seek(0)
            df = pd.read_excel(buf)
            logger.info(f"Autorreparación exitosa de {path.name} ({len(df)} registros recuperados).")
            # Sobrescribir con la versión reparada y limpia
            atomic_save_excel(df, path)
            return df
    except Exception as e:
        logger.error(f"Fallo en la autorreparación de {path}: {e}")
        return None


def load_master_dataframe(path=OUTPUT_FOLDER / MASTER_FILENAME, normalized_columns=None):
    """Carga el DataFrame maestro desde Excel, asegurando columnas base y autorreparación ante corrupción."""
    with GLOBAL_EXCEL_LOCK:
        path = Path(path)
        if not path.exists():
            bak_path = path.with_suffix(".bak.xlsx")
            if bak_path.exists():
                logger.info(f"Restaurando {path.name} desde su copia de respaldo {bak_path.name}")
                shutil.copy2(str(bak_path), str(path))
            else:
                if normalized_columns:
                    return pd.DataFrame(columns=normalized_columns)
                return pd.DataFrame()

        df = None
        load_error = None
        try:
            df = pd.read_excel(path)
        except Exception as e:
            load_error = e
            logger.warning(f"Error al leer '{path.name}': {e}. Iniciando procedimiento de recuperación...")

            # 1. Intentar autorreparación directa de la estructura zip
            df = _attempt_repair_excel(path)

            # 2. Si falló la reparación, intentar cargar desde la copia de respaldo .bak.xlsx
            if df is None:
                bak_path = path.with_suffix(".bak.xlsx")
                if bak_path.exists():
                    try:
                        df = pd.read_excel(bak_path)
                        logger.info(f"Cargado exitosamente desde respaldo: {bak_path.name}")
                        atomic_save_excel(df, path)
                    except Exception as bak_err:
                        logger.error(f"Error cargando respaldo {bak_path.name}: {bak_err}")

        if df is None:
            raise RuntimeError(
                f"El archivo '{path.name}' está dañado o incompleto (se interrumpió la escritura). "
                f"Puedes recuperarlo desde tu Git o volver a procesar tu carpeta de origen. Error original: {load_error}"
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

        if "CadenaBusqueda" not in df.columns and "Fuente" in df.columns:
            from services.config import load_search_queries
            search_queries = load_search_queries()

            def _resolve_query(row):
                f = str(row.get("Fuente", ""))
                a = str(row.get("ArchivoOrigen", ""))
                return (
                    search_queries.get(f"{f}/{a}")
                    or search_queries.get(a)
                    or search_queries.get(f, "")
                )

            df["CadenaBusqueda"] = df.apply(_resolve_query, axis=1)

        if "Revista" not in df.columns:
            df["Revista"] = ""
        df["Revista"] = df["Revista"].fillna("").astype(object)

        if "Seleccion_Manual" not in df.columns:
            df["Seleccion_Manual"] = 0

        if "Comentarios" not in df.columns:
            df["Comentarios"] = ""
        df["Comentarios"] = df["Comentarios"].fillna("").astype(object)

        return df
