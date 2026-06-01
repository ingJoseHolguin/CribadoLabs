"""Procesamiento bibliográfico: parseo, normalización, deduplicación."""

from pathlib import Path

import bibtexparser
import pandas as pd

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
    "DOI",
    "Keywords",
    "URL",
    "ArchivoOrigen",
]

SUPPORTED_EXTENSIONS = [".bib", ".txt", ".csv", ".xls", ".xlsx"]


def normalize_row(row, fuente):
    return {
        "Fuente": fuente,
        "Año": row.get("Año", ""),
        "Autor": row.get("Autor", ""),
        "Titulo": row.get("Titulo", ""),
        "Abstract": row.get("Abstract", ""),
        "Titulo ES": row.get("Titulo ES", ""),
        "Abstract ES": row.get("Abstract ES", ""),
        "TipoDocumento": row.get("TipoDocumento", ""),
        "DOI": row.get("DOI", ""),
        "Keywords": row.get("Keywords", ""),
        "URL": row.get("URL", ""),
        "ArchivoOrigen": row.get("ArchivoOrigen", ""),
    }


def process_bib(filepath, fuente):
    rows = []

    with open(filepath, "r", encoding="utf-8") as bibtex_file:
        bib_database = bibtexparser.load(bibtex_file)

    for entry in bib_database.entries:
        entry_type = entry.get("ENTRYTYPE", "").lower()
        tipo_documento = {
            "article": "Artículo",
            "inproceedings": "Conferencia",
            "proceedings": "Proceedings",
            "book": "Libro",
            "inbook": "Capítulo",
        }.get(entry_type, entry_type)

        row = {
            "Titulo": entry.get("title", ""),
            "Autor": entry.get("author", ""),
            "Año": entry.get("year", ""),
            "Abstract": entry.get("abstract", ""),
            "TipoDocumento": tipo_documento,
            "DOI": entry.get("doi", ""),
            "Keywords": entry.get("keywords", ""),
            "URL": entry.get("url", ""),
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def process_csv(filepath, fuente):
    rows = []
    try:
        df = pd.read_csv(filepath)
    except pd.errors.ParserError:
        df = read_irregular_springer_csv(filepath)

    for _, r in df.iterrows():
        row = {
            "Titulo": r.get("Item Title", r.get("Title", "")),
            "Autor": r.get("Authors", r.get("Author", "")),
            "Año": r.get("Publication Year", r.get("Year", "")),
            "Abstract": r.get("Abstract", ""),
            "TipoDocumento": r.get("Content Type", r.get("Document Type", "")),
            "DOI": r.get("Item DOI", r.get("DOI", "")),
            "Keywords": r.get("Author Keywords", r.get("Keywords", "")),
            "URL": r.get("URL", ""),
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
            }
        )

    return pd.DataFrame(records)


def process_excel(filepath, fuente):
    rows = []
    df = pd.read_excel(filepath)

    for _, r in df.iterrows():
        row = {
            "Titulo": r.get("Article Title", r.get("Title", "")),
            "Autor": r.get("Authors", r.get("Author", "")),
            "Año": r.get("Publication Year", r.get("Year", "")),
            "Abstract": r.get("Abstract", ""),
            "TipoDocumento": r.get("Document Type", r.get("Content Type", "")),
            "DOI": r.get("DOI", r.get("Item DOI", "")),
            "Keywords": r.get("Author Keywords", r.get("Keywords", "")),
            "URL": r.get("URL", ""),
            "ArchivoOrigen": Path(filepath).name,
        }
        rows.append(normalize_row(row, fuente))

    return rows


def process_file(filepath, fuente=None):
    filepath = Path(filepath)
    extension = filepath.suffix.lower()
    fuente = fuente or filepath.parent.name

    if extension in [".bib", ".txt"]:
        return process_bib(filepath, fuente)
    if extension == ".csv":
        return process_csv(filepath, fuente)
    if extension in [".xls", ".xlsx"]:
        return process_excel(filepath, fuente)

    return []


def process_folder(input_folder=INPUT_FOLDER):
    input_folder = Path(input_folder)
    all_rows = []
    errors = []

    for filepath in sorted(input_folder.rglob("*")):
        if not filepath.is_file() or filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            all_rows.extend(process_file(filepath, filepath.parent.name))
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

    doi = df["DOI"].fillna("").astype(str).str.strip()
    with_doi = df[doi != ""].drop_duplicates(subset=["DOI"], keep="first")
    without_doi = df[doi == ""].drop_duplicates(
        subset=["Titulo", "Autor", "Año"], keep="first"
    )
    df = pd.concat([with_doi, without_doi], ignore_index=True)
    df["Año"] = pd.to_numeric(df["Año"], errors="coerce")
    df = df.sort_values(by="Año", ascending=False, na_position="last")

    return df
