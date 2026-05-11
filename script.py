import os
import pandas as pd
import bibtexparser

INPUT_FOLDER = "data"
OUTPUT_FOLDER = "output"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

all_rows = []

# =========================================
# NORMALIZAR
# =========================================

def normalize_row(row, fuente):

    return {
        "Fuente": fuente,
        "Titulo": row.get("Titulo", ""),
        "Autor": row.get("Autor", ""),
        "Año": row.get("Año", ""),
        "Abstract": row.get("Abstract", ""),
        "TipoDocumento": row.get("TipoDocumento", ""),
        "DOI": row.get("DOI", ""),
        "Keywords": row.get("Keywords", ""),
        "URL": row.get("URL", ""),
        "ArchivoOrigen": row.get("ArchivoOrigen", "")
    }

# =========================================
# BIBTEX
# =========================================

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
            "inbook": "Capítulo"
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
            "ArchivoOrigen": os.path.basename(filepath)
        }

        rows.append(normalize_row(row, fuente))

    return rows

# =========================================
# SPRINGER CSV
# =========================================

def process_csv(filepath, fuente):

    rows = []

    df = pd.read_csv(filepath)

    for _, r in df.iterrows():

        row = {
            "Titulo": r.get("Item Title", ""),
            "Autor": r.get("Authors", ""),
            "Año": r.get("Publication Year", ""),
            "Abstract": "",
            "TipoDocumento": r.get("Content Type", ""),
            "DOI": r.get("Item DOI", ""),
            "Keywords": "",
            "URL": r.get("URL", ""),
            "ArchivoOrigen": os.path.basename(filepath)
        }

        rows.append(normalize_row(row, fuente))

    return rows

# =========================================
# EXCEL WOS
# =========================================

def process_excel(filepath, fuente):

    rows = []

    df = pd.read_excel(filepath)

    for _, r in df.iterrows():

        row = {
            "Titulo": r.get("Article Title", ""),
            "Autor": r.get("Authors", ""),
            "Año": r.get("Publication Year", ""),
            "Abstract": r.get("Abstract", ""),
            "TipoDocumento": r.get("Document Type", ""),
            "DOI": r.get("DOI", ""),
            "Keywords": r.get("Author Keywords", ""),
            "URL": "",
            "ArchivoOrigen": os.path.basename(filepath)
        }

        rows.append(normalize_row(row, fuente))

    return rows

# =========================================
# RECORRER TODO
# =========================================

for root, dirs, files in os.walk(INPUT_FOLDER):

    for file in files:

        filepath = os.path.join(root, file)

        extension = os.path.splitext(file)[1].lower()

        # FUENTE = nombre carpeta
        fuente = os.path.basename(root)

        print(f"\nProcesando: {file}")
        print(f"Fuente: {fuente}")

        try:

            # BibTeX
            if extension in [".bib", ".txt"]:

                rows = process_bib(filepath, fuente)
                all_rows.extend(rows)

            # CSV
            elif extension == ".csv":

                rows = process_csv(filepath, fuente)
                all_rows.extend(rows)

            # Excel
            elif extension in [".xls", ".xlsx"]:

                rows = process_excel(filepath, fuente)
                all_rows.extend(rows)

        except Exception as e:

            print(f"ERROR en {file}")
            print(e)

# =========================================
# DATAFRAME FINAL
# =========================================

df = pd.DataFrame(all_rows)

# Eliminar duplicados
df = df.drop_duplicates(subset=["DOI"], keep="first")

# Convertir año
df["Año"] = pd.to_numeric(df["Año"], errors="coerce")

# Ordenar
df = df.sort_values(by="Año", ascending=False)

# Exportar
output_file = os.path.join(
    OUTPUT_FOLDER,
    "scoping_master.xlsx"
)

df.to_excel(output_file, index=False)

print("\n====================================")
print("EXTRACCIÓN COMPLETADA")
print(f"Total artículos: {len(df)}")
print(f"Archivo: {output_file}")
print("====================================")