from pathlib import Path

import streamlit as st

from services.bibliographic import INPUT_FOLDER
from services.config import CONFIG_FOLDER, load_criteria, load_keywords
from services.persistence import OUTPUT_FOLDER
from tabs.sources import SOURCES, sources_tab
from tabs.master_table import processing_tab
from tabs.criteria import criteria_tab
from tabs.llm_settings import llm_settings_tab
from tabs.screening import progressive_screening_tab
from tabs.translation import translation_tab
from tabs.filtering import filtering_tab


st.set_page_config(
    page_title="CribadoLabs",
    page_icon="CL",
    layout="wide",
    initial_sidebar_state="expanded",
)


def ensure_workspace():
    INPUT_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)
    CONFIG_FOLDER.mkdir(exist_ok=True)
    for source in SOURCES:
        (INPUT_FOLDER / source).mkdir(parents=True, exist_ok=True)


def main():
    ensure_workspace()

    if "criteria" not in st.session_state:
        st.session_state["criteria"] = load_criteria()

    if "keywords" not in st.session_state:
        st.session_state["keywords"] = load_keywords()

    st.title("CribadoLabs")
    st.caption("MVP para cargar fuentes, consolidar registros y preparar cribado académico.")

    with st.sidebar:
        st.header("Arquitectura")
        st.write("1. Cargar fuentes")
        st.write("2. Procesar y editar")
        st.write("3. Añadir criterios")
        st.write("4. Configurar LLM")
        st.write("5. Traducir contenido")
        st.write("6. Filtrar resultados (PRISMA)")

    tab_sources, tab_processing, tab_criteria, tab_llm, tab_screening, tab_translation, tab_filtering = st.tabs(
        [
            "Fuentes",
            "Tabla maestra",
            "Criterios",
            "LLM",
            "Cribado Progresivo",
            "Traducción",
            "Filtrado (PRISMA)"
        ]
    )

    with tab_sources:
        sources_tab()
    with tab_processing:
        processing_tab()
    with tab_criteria:
        criteria_tab()
    with tab_llm:
        llm_settings_tab()
    with tab_screening:
        progressive_screening_tab()
    with tab_translation:
        translation_tab()
    with tab_filtering:
        filtering_tab()


if __name__ == "__main__":
    main()
