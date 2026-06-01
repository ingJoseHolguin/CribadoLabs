"""Servicio de traducción offline con Argos Translate y PyMuPDF."""

import os
import re
import subprocess
import sys
from pathlib import Path


def verify_cuda_working() -> bool:
    try:
        cmd = [
            sys.executable,
            "-c",
            "import os; os.environ['ARGOS_DEVICE_TYPE']='cuda'; import argostranslate.translate; "
            "installed = argostranslate.translate.get_installed_languages(); "
            "from_l = next(filter(lambda x: x.code == 'en', installed), None); "
            "to_l = next(filter(lambda x: x.code == 'es', installed), None); "
            "from_l.get_translation(to_l).translate('test') if (from_l and to_l) else None"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def get_argos_translator(from_code="en", to_code="es", device="auto"):
    """Retorna el traductor Argos y el device efectivo usado."""
    effective_device = device
    if device in ("cuda", "auto"):
        if not verify_cuda_working():
            effective_device = "cpu"

    os.environ["ARGOS_DEVICE_TYPE"] = effective_device

    import argostranslate.package
    import argostranslate.translate

    installed_languages = argostranslate.translate.get_installed_languages()
    from_lang = next(filter(lambda x: x.code == from_code, installed_languages), None)
    to_lang = next(filter(lambda x: x.code == to_code, installed_languages), None)

    translation = None
    if from_lang and to_lang:
        translation = from_lang.get_translation(to_lang)

    if translation is None:
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            filter(
                lambda x: x.from_code == from_code and x.to_code == to_code,
                available_packages
            ), None
        )
        if package_to_install:
            download_path = package_to_install.download()
            argostranslate.package.install_from_path(download_path)

            installed_languages = argostranslate.translate.get_installed_languages()
            from_lang = next(filter(lambda x: x.code == from_code, installed_languages), None)
            to_lang = next(filter(lambda x: x.code == to_code, installed_languages), None)
            if from_lang and to_lang:
                translation = from_lang.get_translation(to_lang)

    return translation, effective_device


def translate_pdf_with_fitz_and_md(input_path, output_pdf_path, output_md_path, translator, progress_callback=None):
    import fitz

    doc = fitz.open(input_path)
    total_pages = len(doc)

    only_symbols_re = re.compile(r'^[0-9\s\-\+\*\/\(\)\[\]\,\.\:\;\_\#\%\&\=\>\<\@\“\”\u2022\–\—]+$')

    md_content = []

    for page_idx, page in enumerate(doc):
        if progress_callback:
            progress_callback(page_idx, total_pages)

        md_content.append(f"\n## --- Página {page_idx + 1} ---\n")

        blocks = page.get_text("blocks")
        for b in blocks:
            x0, y0, x1, y1, text, block_no, block_type = b
            if block_type != 0:
                continue

            text_clean = text.strip()
            if not text_clean or len(text_clean) < 2:
                continue

            if only_symbols_re.match(text_clean):
                md_content.append(text_clean + "\n")
                continue

            text_to_translate = text_clean.replace("-\n", "").replace("- \n", "").replace("\n", " ")
            text_to_translate = re.sub(r'\s+', ' ', text_to_translate).strip()

            try:
                translated_text = translator.translate(text_to_translate)
            except Exception:
                translated_text = text_clean

            md_content.append(translated_text + "\n")

            rect = fitz.Rect(x0, y0, x1, y1)
            bg_rect = fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
            page.draw_rect(bg_rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)

            font_size = 9.0
            while font_size >= 4.5:
                res = page.insert_textbox(
                    rect,
                    translated_text,
                    fontsize=font_size,
                    fontname="helv",
                    align=0
                )
                if res >= 0:
                    break
                font_size -= 0.5
            else:
                page.insert_textbox(
                    rect,
                    translated_text,
                    fontsize=4.5,
                    fontname="helv",
                    align=0
                )

    doc.save(output_pdf_path)
    doc.close()

    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_content))
