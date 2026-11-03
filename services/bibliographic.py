"""Procesamiento bibliográfico: parseo, normalización, deduplicación."""

import re
from pathlib import Path

import bibtexparser
import pandas as pd

from services.config import load_search_queries
from services.persistence import save_master_dataframe, load_master_dataframe


INPUT_FOLDER = Path("data")
OUTPUT_FOLDER = Path("output")
MASTER_FILENAME = "scoping_master.xlsx"

NORMALIZED_COLUMNS = [
    "Fuente",
    "Año",
    "Autor",
    "Titulo",
    "Abstract",
    "Titulo ES",
    "Abstract ES",
    "TipoDocumento",
    "Revista",
    "DOI",
    "Keywords",
    "URL",
    "CadenaBusqueda",
    "ArchivoOrigen",
]

SUPPORTED_EXTENSIONS = [".bib", ".txt", ".csv", ".xls", ".xlsx"]


def clean_doi(doi):
    """Limpia y normaliza identificadores DOI eliminando prefijos URL comunes."""
    if not doi:
        return ""
    doi_str = str(doi).strip()
    doi_str = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi_str, flags=re.IGNORECASE)
    return doi_str.strip()


def _get_val(row, candidate_keys, default=""):
    """Obtiene el primer valor no nulo ni vacío de una lista de claves candidatas en una fila."""
    for key in candidate_keys:
        if key in row:
            val = row[key]
            if pd.notna(val):
                s = str(val).strip()
                if s and s.lower() != "nan":
                    return s
    return default


def clean_str(val):
    """Convierte valores a cadena limpia eliminando nulos o representaciones 'nan'."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if s.lower() == "nan":
        return ""
    return s


def normalize_row(row, fuente):
    return {
        "Fuente": clean_str(fuente),
        "Año": clean_str(row.get("Año", "")),
        "Autor": clean_str(row.get("Autor", "")),
        "Titulo": clean_str(row.get("Titulo", "")),
        "Abstract": clean_str(row.get("Abstract", "")),
        "Titulo ES": clean_str(row.get("Titulo ES", "")),
        "Abstract ES": clean_str(row.get("Abstract ES", "")),
        "TipoDocumento": clean_str(row.get("TipoDocumento", "")),
        "Revista": clean_str(row.get("Revista", "")),
        "DOI": clean_doi(row.get("DOI", "")),
        "Keywords": clean_str(row.get("Keywords", "")),
        "URL": clean_str(row.get("URL", "")),
        "CadenaBusqueda": clean_str(row.get("CadenaBusqueda", "")),
        "ArchivoOrigen": clean_str(row.get("ArchivoOrigen", "")),
    }


def process_bib(filepath, fuente, cadena_busqueda=""):
    rows = []

    with open(filepath, "r", encoding="utf-8", errors="replace") as bibtex_file:
        raw_content = bibtex_file.read()

    # Scopus y otras fuentes a veces generan claves de citación con espacios
    # (ej. @CONFERENCE{Novoa Munoz2022,). bibtexparser las descarta si tienen espacios.
    def fix_citation_key(match):
        entry_type = match.group(1)
        key = match.group(2).strip()
        clean_key = re.sub(r"\s+", "_", key)
        return f"@{entry_type}{{{clean_key},"

    fixed_raw = re.sub(r"@([A-Za-z]+)\s*\{\s*([^,]+?),", fix_citation_key, raw_content)
    bib_database = bibtexparser.loads(fixed_raw)

    for entry in bib_database.entries:
        entry_type = entry.get("ENTRYTYPE", "").lower()
        tipo_documento = {
            "article": "Artículo",
            "inproceedings": "Conferencia",
            "conference": "Conferencia",
            "proceedings": "Proceedings",
            "book": "Libro",
            "inbook": "Capítulo",
            "incollection": "Capítulo",
            "conference review": "Revisión de Conferencia",
            "short survey": "Revisión",
            "review": "Revisión",
        }.get(entry_type, entry.get("type", entry_type))

        author = entry.get("author", "").strip()
        if not author:
            author = entry.get("editor", "").strip()
        if not author:
            author = entry.get("publisher", "").strip()

        keywords = entry.get("keywords", "").strip()
        author_keywords = entry.get("author_keywords", "").strip()
        all_keywords = (
            f"{keywords}; {author_keywords}".strip("; ")
            if (keywords and author_keywords)
            else (keywords or author_keywords)
        )

        revista = (
            entry.get("journal", "")
            or entry.get("booktitle", "")
            or entry.get("series", "")
        ).strip()

        row = {
            "Titulo": entry.get("title", ""),
            "Autor": author,
            "Año": entry.get("year", ""),
            "Abstract": entry.get("abstract", ""),
            "TipoDocumento": tipo_documento,
            "Revista": revista,
            "DOI": entry.get("doi", ""),
            "Keywords": all_keywords,
            "URL": entry.get("url", ""),
            "CadenaBusqueda": cadena_busqueda,
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def is_sciencedirect_landscape(df):
    """Detecta si un DataFrame corresponde a una tabla comparativa de ScienceDirect Topic Landscape."""
    cols = set(df.columns)
    return {"Source", "Abstract"}.issubset(cols) and bool(
        {"PII", "EID", "Methods", "Results", "Conclusions"} & cols
    )


def process_sciencedirect_landscape(df, filepath, fuente, cadena_busqueda=""):
    """Procesa una tabla comparativa exportada desde ScienceDirect Topic Landscape."""
    rows = []
    for _, r in df.iterrows():
        pub_date = str(r.get("Publication Date", "")).strip()
        year_match = re.search(r"\b(19\d\d|20\d\d)\b", pub_date)
        anio = year_match.group(1) if year_match else (pub_date if pub_date.lower() != "nan" else "")

        doi_raw = str(r.get("DOI", "")).strip()
        if doi_raw.lower() == "nan":
            doi_raw = ""
        clean_d = clean_doi(doi_raw)
        url = doi_raw if doi_raw.startswith("http") else (f"https://doi.org/{clean_d}" if clean_d else "")

        abstract_base = str(r.get("Abstract", "")).strip()
        if abstract_base.lower() == "nan":
            abstract_base = ""

        extra_parts = []
        for field, label in [("Methods", "Métodos"), ("Results", "Resultados"), ("Conclusions", "Conclusiones")]:
            val = str(r.get(field, "")).strip()
            if val and val.lower() != "nan":
                extra_parts.append(f"[{label}]: {val}")

        if extra_parts:
            full_abstract = (abstract_base + "\n\n" + "\n\n".join(extra_parts)).strip() if abstract_base else "\n\n".join(extra_parts)
        else:
            full_abstract = abstract_base

        titulo = str(r.get("Source", "")).strip()
        if titulo.lower() == "nan":
            titulo = ""

        row = {
            "Titulo": titulo,
            "Autor": "",
            "Año": anio,
            "Abstract": full_abstract,
            "TipoDocumento": "Article",
            "Revista": "",
            "DOI": doi_raw,
            "Keywords": "",
            "URL": url,
            "CadenaBusqueda": cadena_busqueda,
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def process_csv(filepath, fuente, cadena_busqueda=""):
    try:
        df = pd.read_csv(filepath)
    except pd.errors.ParserError:
        df = read_irregular_springer_csv(filepath)

    if is_sciencedirect_landscape(df):
        return process_sciencedirect_landscape(df, filepath, fuente, cadena_busqueda=cadena_busqueda)

    rows = []
    for _, r in df.iterrows():
        row = {
            "Titulo": _get_val(r, ["Document Title", "Item Title", "Article Title", "Title", "Paper Title"]),
            "Autor": _get_val(r, ["Authors", "Author", "Author full names", "Editors", "Editor", "Author(s)"]),
            "Año": _get_val(r, ["Publication Year", "Year", "Published Year", "Date"]),
            "Abstract": _get_val(r, ["Abstract", "Description", "Abstract Note"]),
            "TipoDocumento": _get_val(r, ["Content Type", "Document Type", "Type", "Publication Type"]),
            "Revista": _get_val(r, ["Publication Title", "Journal Title", "Source title", "Book Series Title", "Journal", "Publication"]),
            "DOI": _get_val(r, ["Item DOI", "DOI", "Digital Object Identifier"]),
            "Keywords": _get_val(r, ["Author Keywords", "Keywords", "Index Keywords", "IEEE Terms", "Author Keywords/Keywords", "Mesh_Terms"]),
            "URL": _get_val(r, ["URL", "PDF Link", "Link", "Document Identifier", "Source URL"]),
            "CadenaBusqueda": cadena_busqueda,
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def read_irregular_springer_csv(filepath):
    records = []

    with open(filepath, "r", encoding="utf-8") as csv_file:
        lines = csv_file.readlines()

    for line in lines[1:]:
        line = line.strip().rstrip(";")
        if not line:
            continue

        parts = [part.strip().rstrip(";") for part in line.split(",")]
        doi_index = next(
            (index for index, part in enumerate(parts) if part.startswith("10.")), None
        )

        if doi_index is None or len(parts) < doi_index + 5:
            continue

        title_end = max(doi_index - 5, 1)
        records.append(
            {
                "Item Title": ",".join(parts[:title_end]).strip(),
                "Item DOI": parts[doi_index],
                "Authors": parts[doi_index + 1],
                "Publication Year": parts[doi_index + 2],
                "URL": parts[doi_index + 3],
                "Content Type": parts[doi_index + 4].strip(";"),
                "Publication Title": parts[title_end] if len(parts) > title_end else "",
            }
        )

    return pd.DataFrame(records)


def process_excel(filepath, fuente, cadena_busqueda=""):
    rows = []
    df = pd.read_excel(filepath)

    for _, r in df.iterrows():
        row = {
            "Titulo": _get_val(r, ["Article Title", "Document Title", "Item Title", "Title", "Paper Title"]),
            "Autor": _get_val(r, ["Authors", "Author", "Author full names", "Editors", "Editor", "Author(s)"]),
            "Año": _get_val(r, ["Publication Year", "Year", "Published Year", "Date"]),
            "Abstract": _get_val(r, ["Abstract", "Description", "Abstract Note"]),
            "TipoDocumento": _get_val(r, ["Document Type", "Content Type", "Type", "Publication Type"]),
            "Revista": _get_val(r, ["Publication Title", "Journal Title", "Source title", "Book Series Title", "Journal", "Publication"]),
            "DOI": _get_val(r, ["DOI", "Item DOI", "Digital Object Identifier"]),
            "Keywords": _get_val(r, ["Author Keywords", "Keywords", "Index Keywords", "Author Keywords/Keywords"]),
            "URL": _get_val(r, ["URL", "Link", "PDF Link", "Document Identifier", "Source URL"]),
            "CadenaBusqueda": cadena_busqueda,
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def process_file(filepath, fuente=None, cadena_busqueda=None, search_queries=None):
    filepath = Path(filepath)
    extension = filepath.suffix.lower()
    fuente = fuente or filepath.parent.name

    if cadena_busqueda is None:
        if search_queries is None:
            search_queries = load_search_queries()
        file_key = f"{fuente}/{filepath.name}"
        cadena_busqueda = (
            search_queries.get(file_key)
            or search_queries.get(filepath.name)
            or search_queries.get(fuente, "")
        )

    if extension in [".bib", ".txt"]:
        return process_bib(filepath, fuente, cadena_busqueda=cadena_busqueda)
    if extension == ".csv":
        return process_csv(filepath, fuente, cadena_busqueda=cadena_busqueda)
    if extension in [".xls", ".xlsx"]:
        return process_excel(filepath, fuente, cadena_busqueda=cadena_busqueda)

    return []


def process_folder(input_folder=INPUT_FOLDER):
    input_folder = Path(input_folder)
    all_rows = []
    errors = []
    search_queries = load_search_queries()

    for filepath in sorted(input_folder.rglob("*")):
        if not filepath.is_file() or filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            all_rows.extend(
                process_file(
                    filepath,
                    filepath.parent.name,
                    search_queries=search_queries,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "Archivo": str(filepath),
                    "Fuente": filepath.parent.name,
                    "Error": str(exc),
                }
            )

    return build_master_dataframe(all_rows), errors


def build_master_dataframe(rows):
    df = pd.DataFrame(rows, columns=NORMALIZED_COLUMNS)

    if df.empty:
        return df

    df["DOI"] = df["DOI"].fillna("").astype(str).map(clean_doi)
    has_doi = df["DOI"].str.strip() != ""
    has_author = df["Autor"].fillna("").astype(str).str.strip() != ""

    # Priorizar registros con autor antes de deduplicar por DOI
    df_with_doi = df[has_doi].assign(_has_author=has_author[has_doi]).sort_values(
        by="_has_author", ascending=False, kind="stable"
    )
    with_doi = (
        df_with_doi.drop_duplicates(subset=["DOI"], keep="first")
        .drop(columns=["_has_author"])
    )
    without_doi = df[~has_doi].drop_duplicates(
        subset=["Titulo", "Autor", "Año"], keep="first"
    )
    df = pd.concat([with_doi, without_doi], ignore_index=True)
    df["Año"] = pd.to_numeric(df["Año"], errors="coerce")
    df = df.sort_values(by="Año", ascending=False, na_position="last")

    return df
