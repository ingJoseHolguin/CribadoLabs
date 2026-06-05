"""Pestaña: Audio & Resumen — extracción, limpieza LLM, TTS y karaoke."""

from datetime import datetime
from pathlib import Path

import streamlit as st

from services.audio_pipeline import (
    build_karaoke_html,
    clean_and_summarize_for_audio,
    generate_speech,
    list_spanish_voices,
)
from services.pdf_text_extractor import extract_clean_text

OUTPUT_AUDIO_DIR = Path("output/audio_resumenes")


def audio_summarizer_tab():
    st.subheader("🎧 Audio & Resumen")
    st.write(
        "Convierte un texto (de PDF o pegado directamente) en un audio narrado. "
        "Puedes usar el LLM local para limpiar y resumir antes de generar la voz."
    )

    # Configuración LLM
    llm_config = {
        "endpoint": st.session_state.get("ollama_endpoint", "http://localhost:11434"),
        "model": st.session_state.get("ollama_model", "llama3.1"),
    }

    # ================================================================
    # PASO 0: ELEGIR ORIGEN DEL TEXTO
    # ================================================================
    st.markdown("### Paso 1: Origen del texto")
    source_option = st.radio(
        "¿De dónde viene el texto?",
        options=["Pegar texto directamente", "Subir un PDF"],
        horizontal=True,
        key="audio_source_option",
    )

    text_input = ""

    text_input = ""

    if source_option == "Subir un PDF":
        uploaded_pdf = st.file_uploader("Sube tu PDF", type=["pdf"], key="audio_pdf_uploader")
        if uploaded_pdf:
            OUTPUT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path = OUTPUT_AUDIO_DIR / f"input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path.write_bytes(uploaded_pdf.getvalue())

            if st.button("Extraer texto del PDF", use_container_width=True, key="btn_extract_pdf"):
                with st.spinner("Extrayendo texto del PDF..."):
                    try:
                        extracted = extract_clean_text(pdf_path)
                        st.session_state["audio_raw_text"] = extracted
                        st.success("Texto extraído.")
                    except Exception as exc:
                        st.error(f"Error al extraer texto: {exc}")

        text_input = st.session_state.get("audio_raw_text", "")
        if text_input:
            with st.expander("✏️ Texto extraído (puedes editarlo aquí)", expanded=True):
                edited = st.text_area(
                    "Edición del texto extraído",
                    value=text_input,
                    height=300,
                    key="ta_edit_extracted",
                )
                st.session_state["audio_raw_text"] = edited
                st.caption(f"{len(edited)} caracteres")
    else:
        text_input = st.text_area(
            "Pega aquí tu texto (artículo, notas, transcripción, etc.)",
            value=st.session_state.get("audio_raw_text", ""),
            height=300,
            key="ta_pasted_text",
            placeholder="Ej. El artículo propone un modelo de evaluación de calidad de colaboración...",
        )
        if text_input:
            st.session_state["audio_raw_text"] = text_input
            st.caption(f"{len(text_input)} caracteres pegados")

    if not text_input or not text_input.strip():
        st.info("Completa el paso 1 para continuar.")
        return

    st.divider()

    # ================================================================
    # PASO 2: LIMPIEZA / RESUMEN CON LLM (OPCIONAL)
    # ================================================================
    st.markdown("### Paso 2: Preparar texto para audio (opcional)")
    st.write(
        "Si el texto es muy técnico, largo o tiene basura (referencias, ecuaciones, tablas), "
        "el LLM puede limpiarlo y convertirlo en un resumen narrativo fluido apto para escuchar."
    )

    col_use_raw, col_use_llm = st.columns([1, 1])
    with col_use_raw:
        if st.button("✅ Usar texto tal cual", use_container_width=True, key="btn_use_raw"):
            st.session_state["audio_final_text"] = text_input.strip()
            st.success("Texto original seleccionado.")
    with col_use_llm:
        if st.button("🤖 Limpiar y resumir con LLM", use_container_width=True, key="btn_use_llm"):
            with st.spinner("El LLM está procesando (puede tardar varios minutos)..."):
                try:
                    summary = clean_and_summarize_for_audio(text_input.strip(), llm_config)
                    st.session_state["audio_final_text"] = summary
                    st.success("Texto limpiado y resumido.")
                except Exception as exc:
                    st.error(f"Error del LLM: {exc}")

    final_text = st.session_state.get("audio_final_text", "")
    if final_text:
        with st.expander("📝 Texto que se usará para el audio (editable)", expanded=True):
            edited_final = st.text_area(
                "Edición final antes de generar voz",
                value=final_text,
                height=250,
                key="ta_final_text",
            )
            st.session_state["audio_final_text"] = edited_final
            st.caption(f"{len(edited_final)} caracteres — estimado: ~{len(edited_final.split())} palabras")

    if not final_text or not final_text.strip():
        st.info("Elige si usas el texto tal cual o lo procesas con el LLM (paso 2).")
        return

    st.divider()

    # ================================================================
    # PASO 3: CONFIGURAR VOZ Y GENERAR AUDIO
    # ================================================================
    st.markdown("### Paso 3: Generar voz")

    voices = list_spanish_voices()
    voice_options = {v["name"]: v["id"] for v in voices}
    selected_voice_name = st.selectbox("Elige una voz", list(voice_options.keys()), index=0)
    selected_voice_id = voice_options[selected_voice_name]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = OUTPUT_AUDIO_DIR / f"audio_{timestamp}.mp3"
    vtt_path = OUTPUT_AUDIO_DIR / f"audio_{timestamp}.vtt"

    if st.button("🔊 Generar audio", type="primary", use_container_width=True, key="btn_generate_audio"):
        with st.spinner("Generando audio con edge-tts..."):
            try:
                generate_speech(final_text.strip(), selected_voice_id, audio_path, vtt_path)
                st.session_state["audio_generated_path"] = str(audio_path)
                st.session_state["audio_vtt_path"] = str(vtt_path)
                st.success("¡Audio generado!")
            except Exception as exc:
                st.error(f"Error al generar audio: {exc}")

    st.divider()

    # ================================================================
    # PASO 4: ESCUCHAR, DESCARGAR Y KARAOKE
    # ================================================================
    gen_audio = st.session_state.get("audio_generated_path")
    if gen_audio and Path(gen_audio).exists():
        st.markdown("### Paso 4: Escuchar y descargar")

        st.audio(gen_audio, format="audio/mp3")

        col_d1, col_d2, col_k = st.columns(3)
        with col_d1:
            with open(gen_audio, "rb") as f:
                st.download_button(
                    label="📥 Descargar MP3",
                    data=f.read(),
                    file_name=f"resumen_{timestamp}.mp3",
                    mime="audio/mpeg",
                    use_container_width=True,
                )
        with col_d2:
            gen_vtt = st.session_state.get("audio_vtt_path")
            if gen_vtt and Path(gen_vtt).exists():
                with open(gen_vtt, "rb") as f:
                    st.download_button(
                        label="📥 Descargar subtítulos (VTT)",
                        data=f.read(),
                        file_name=f"resumen_{timestamp}.vtt",
                        mime="text/vtt",
                        use_container_width=True,
                    )
        with col_k:
            if st.button("🎤 Ver modo Karaoke", use_container_width=True, key="btn_karaoke"):
                try:
                    gen_vtt = st.session_state.get("audio_vtt_path")
                    if gen_vtt and Path(gen_vtt).exists():
                        html = build_karaoke_html(Path(gen_audio), Path(gen_vtt))
                        st.session_state["audio_karaoke_html"] = html
                    else:
                        st.warning("No se encontraron subtítulos VTT.")
                except Exception as exc:
                    st.error(f"Error al generar karaoke: {exc}")

        karaoke_html = st.session_state.get("audio_karaoke_html")
        if karaoke_html:
            st.markdown("---")
            st.markdown("#### 🎤 Modo Karaoke")
            st.components.v1.html(karaoke_html, height=500, scrolling=True)
