"""Extracción de texto limpio de PDFs usando PyMuPDF."""

import re
from pathlib import Path


def extract_raw_text(pdf_path: Path) -> str:
    """Extrae texto crudo de un PDF preservando el orden de lectura."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF (fitz) no está instalado. Instálalo con: pip install PyMuPDF") from exc

    doc = fitz.open(pdf_path)
    all_blocks = []

    for page_idx, page in enumerate(doc):
        blocks = page.get_text("blocks")
        for b in blocks:
            x0, y0, x1, y1, text, block_no, block_type = b
            if block_type != 0:
                continue
            text_clean = text.strip()
            if not text_clean or len(text_clean) < 2:
                continue
            all_blocks.append({
                "page": page_idx + 1,
                "y": y0,
                "x": x0,
                "text": text_clean,
            })

    doc.close()

    # Ordenar por página, luego por Y ascendente, luego por X ascendente
    all_blocks.sort(key=lambda b: (b["page"], b["y"], b["x"]))

    # Agrupar por página para separar con marcadores
    lines = []
    current_page = 0
    for blk in all_blocks:
        if blk["page"] != current_page:
            current_page = blk["page"]
            lines.append(f"\n--- Página {current_page} ---\n")
        lines.append(blk["text"])

    return "\n\n".join(lines)


def extract_clean_text(pdf_path: Path) -> str:
    """Extrae texto de PDF aplicando heurísticas simples de limpieza."""
    raw = extract_raw_text(pdf_path)
    lines = raw.splitlines()
    cleaned_lines = []

    # Patrones para detectar basura
    page_number_re = re.compile(r"^\s*\d+\s*$")
    header_footer_re = re.compile(r"^(.*?)(\d+\s*$/\s*\d+|www\.|http|@|doi\.org|vol\.|pp\.|page|journal|conference|proceedings)", re.IGNORECASE)
    references_start_re = re.compile(r"^(References|Bibliografía|Bibliography|Acknowledgments|Acknowledgements|Agradecimientos|Notas|Notes|Appendix|Apéndice)\s*$", re.IGNORECASE)
    isolated_symbols_re = re.compile(r"^[0-9\s\-\+\*\/\(\)\[\]\,\.\:\;\_\#\%\&\=\>\<\@\“\”\u2022\–\—]+$")

    in_references = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue

        # Detectar inicio de referencias
        if references_start_re.match(stripped):
            in_references = True
            continue
        if in_references:
            continue

        # Descartar números de página aislados
        if page_number_re.match(stripped):
            continue

        # Descartar líneas que parecen headers/footers genéricos
        if len(stripped) < 60 and header_footer_re.match(stripped):
            continue

        # Descartar líneas que son solo símbolos/números
        if isolated_symbols_re.match(stripped):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)
