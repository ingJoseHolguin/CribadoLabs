"""Pestaña: Selección Manual — Cribado interactivo tipo tarjeta (estilo Tinder)."""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.client_tts import build_client_tts_html
from services.config import load_manual_screening_state, save_manual_screening_state
from services.persistence import MASTER_FILENAME, OUTPUT_FOLDER, load_master_dataframe
from tabs import safe_save_master_dataframe
from tabs.telegram_view import render_telegram_config_panel


def manual_screening_tab():
    st.subheader("Selección Manual de Artículos (Cribado Rápido)")
    st.caption("Revisión ágil tipo tarjeta optimizada para computadora y móvil.")

    df_master = st.session_state.get("master_df")
    if df_master is None or df_master.empty:
        master_file = OUTPUT_FOLDER / MASTER_FILENAME
        if master_file.exists():
            df_master = load_master_dataframe(master_file)
            st.session_state["master_df"] = df_master
        else:
            df_master = pd.DataFrame()

    if df_master.empty:
        st.warning("No hay registros en la tabla maestra. Ve a la pestaña 'Tabla maestra' y procesa o carga los datos.")
        return

    # Asegurar que la columna Seleccion_Manual exista y sea entera
    if "Seleccion_Manual" not in df_master.columns:
        df_master["Seleccion_Manual"] = 0
    df_master["Seleccion_Manual"] = (
        pd.to_numeric(df_master["Seleccion_Manual"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    # Asegurar que la columna Comentarios exista y sea de tipo texto/object
    if "Comentarios" not in df_master.columns:
        df_master["Comentarios"] = ""
    df_master["Comentarios"] = df_master["Comentarios"].fillna("").astype(object)
    st.session_state["master_df"] = df_master

    # Cargar estado guardado de la sesión anterior (JSON en disco)
    saved_state = load_manual_screening_state()

    # Controles superiores: Ordenación, Filtros y Modo de avance
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1.3, 1.3, 1.4])

    with col_ctrl1:
        sort_options = []
        if "F0_Score" in df_master.columns:
            sort_options.append("F0_Score (Mayor a menor)")
        if "Total Score" in df_master.columns:
            sort_options.append("Total Score (Mayor a menor)")
        if "Año" in df_master.columns:
            sort_options.append("Año (Más reciente)")
        sort_options.append("Orden original")

        default_sort = saved_state.get("sort_by", "F0_Score (Mayor a menor)")
        if default_sort not in sort_options:
            default_sort = sort_options[0]

        selected_sort = st.selectbox(
            "Ordenar registros por:",
            sort_options,
            index=sort_options.index(default_sort) if default_sort in sort_options else 0,
            key="ms_sort_opt",
            help="Por defecto ordena por F0_Score de mayor a menor incidencia.",
        )

    with col_ctrl2:
        filter_options = [
            "Todos los registros",
            "Solo pendientes de decisión (0)",
            "Solo incluidos (1)",
            "Solo excluidos (-1)",
        ]
        default_filter = saved_state.get("filter_by", "Todos los registros")
        if default_filter not in filter_options:
            default_filter = filter_options[0]

        selected_filter = st.selectbox(
            "Filtrar vista:",
            filter_options,
            index=filter_options.index(default_filter) if default_filter in filter_options else 0,
            key="ms_filter_opt",
        )

    with col_ctrl3:
        st.write("")
        st.write("")
        auto_advance = st.checkbox(
            "⚡ Auto-avanzar al decidir",
            value=saved_state.get("auto_advance", True),
            key="ms_auto_advance",
            help="Si está activado, pasa al siguiente registro inmediatamente tras hacer clic en Incluir o No Incluir. Si lo desactivas, podrás ver la tarjeta con su nuevo estado antes de pulsar Siguiente.",
        )

    # Aplicar ordenación
    if selected_sort == "F0_Score (Mayor a menor)":
        df_sorted = df_master.sort_values(by="F0_Score", ascending=False, kind="stable")
    elif selected_sort == "Total Score (Mayor a menor)":
        df_sorted = df_master.sort_values(by="Total Score", ascending=False, kind="stable")
    elif selected_sort == "Año (Más reciente)":
        df_sorted = df_master.sort_values(by="Año", ascending=False, na_position="last", kind="stable")
    else:
        df_sorted = df_master.copy()

    # Aplicar filtro
    if selected_filter == "Solo pendientes de decisión (0)":
        df_view = df_sorted[df_sorted["Seleccion_Manual"] == 0]
    elif selected_filter == "Solo incluidos (1)":
        df_view = df_sorted[df_sorted["Seleccion_Manual"] == 1]
    elif selected_filter == "Solo excluidos (-1)":
        df_view = df_sorted[df_sorted["Seleccion_Manual"] == -1]
    else:
        df_view = df_sorted

    # Métricas globales
    tot_master = len(df_master)
    count_incl = int((df_master["Seleccion_Manual"] == 1).sum())
    count_excl = int((df_master["Seleccion_Manual"] == -1).sum())
    count_pend = int((df_master["Seleccion_Manual"] == 0).sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total en base", f"{tot_master:,}")
    m2.metric("🟢 Incluidos (1)", f"{count_incl:,}")
    m3.metric("🔴 Excluidos (-1)", f"{count_excl:,}")
    m4.metric("⚪ Pendientes", f"{count_pend:,}")

    # Panel del Bot de Telegram (Cribado Remoto)
    render_telegram_config_panel()

    total_view = len(df_view)
    if total_view == 0:
        st.info("🎉 No hay registros que coincidan con el filtro seleccionado.")
        return

    # Restauración inteligente del índice al cargar o recargar (F5)
    if "ms_index" not in st.session_state:
        last_doi = str(saved_state.get("last_doi", "")).strip()
        last_titulo = str(saved_state.get("last_titulo", "")).strip()
        restored_idx = None

        if last_doi or last_titulo:
            for i, (_, row) in enumerate(df_view.iterrows()):
                r_doi = str(row.get("DOI", "")).strip()
                r_tit = str(row.get("Titulo", "")).strip()
                if (last_doi and r_doi and r_doi.lower() == last_doi.lower()) or (
                    last_titulo and r_tit and r_tit.lower() == last_titulo.lower()
                ):
                    restored_idx = i
                    break

        if restored_idx is not None:
            st.session_state["ms_index"] = restored_idx
        else:
            # Si no hay registro previo en la vista, buscar el primer pendiente
            pend_indices = [i for i, (_, r) in enumerate(df_view.iterrows()) if r.get("Seleccion_Manual", 0) == 0]
            if pend_indices:
                st.session_state["ms_index"] = pend_indices[0]
            else:
                st.session_state["ms_index"] = 0

    if st.session_state["ms_index"] >= total_view:
        st.session_state["ms_index"] = total_view - 1
    if st.session_state["ms_index"] < 0:
        st.session_state["ms_index"] = 0

    cur_idx = st.session_state["ms_index"]

    # Barra de navegación rápida y selector numérico
    nav_col1, nav_col2 = st.columns([2, 1])
    with nav_col1:
        st.progress(
            (cur_idx + 1) / total_view,
            text=f"Registro **{cur_idx + 1}** de **{total_view}** en esta vista",
        )
    with nav_col2:
        jump_idx = st.number_input(
            "Saltar al registro #",
            min_value=1,
            max_value=total_view,
            value=cur_idx + 1,
            step=1,
            key=f"ms_jump_input_{cur_idx}_{total_view}",
            label_visibility="collapsed",
        )
        if jump_idx - 1 != cur_idx:
            st.session_state["ms_index"] = jump_idx - 1
            new_r = df_view.iloc[jump_idx - 1]
            save_manual_screening_state({
                "last_doi": str(new_r.get("DOI", "")).strip(),
                "last_titulo": str(new_r.get("Titulo", "")).strip(),
                "last_index": jump_idx - 1,
                "sort_by": selected_sort,
                "filter_by": selected_filter,
                "auto_advance": auto_advance,
            })
            st.rerun()

    # Botones de navegación contextual rápida
    c_nav1, c_nav2, c_nav3, c_nav4 = st.columns([1.5, 1.5, 1, 1])
    with c_nav1:
        if st.button("▶️ Continuar donde me quedé", use_container_width=True, help="Salta al último artículo modificado"):
            last_doi = str(saved_state.get("last_doi", "")).strip()
            last_tit = str(saved_state.get("last_titulo", "")).strip()
            target_pos = None
            if last_doi or last_tit:
                for i, (_, r) in enumerate(df_view.iterrows()):
                    r_doi = str(r.get("DOI", "")).strip()
                    r_tit = str(r.get("Titulo", "")).strip()
                    if (last_doi and r_doi and r_doi.lower() == last_doi.lower()) or (
                        last_tit and r_tit and r_tit.lower() == last_tit.lower()
                    ):
                        target_pos = i
                        break
            if target_pos is not None:
                st.session_state["ms_index"] = target_pos
                st.rerun()
            else:
                st.toast("El último registro no está presente en el filtro actual.", icon="ℹ️")

    with c_nav2:
        if st.button("🔍 Siguiente pendiente", use_container_width=True, help="Salta al siguiente registro aún sin decidir"):
            next_pend = None
            for i in range(cur_idx + 1, total_view):
                if df_view.iloc[i].get("Seleccion_Manual", 0) == 0:
                    next_pend = i
                    break
            if next_pend is None:
                for i in range(0, cur_idx):
                    if df_view.iloc[i].get("Seleccion_Manual", 0) == 0:
                        next_pend = i
                        break
            if next_pend is not None:
                st.session_state["ms_index"] = next_pend
                st.rerun()
            else:
                st.toast("¡No hay más registros pendientes en esta vista!", icon="🎉")

    with c_nav3:
        if st.button("⏮️ Primero", use_container_width=True):
            st.session_state["ms_index"] = 0
            st.rerun()

    with c_nav4:
        if st.button("⏭️ Último", use_container_width=True):
            st.session_state["ms_index"] = total_view - 1
            st.rerun()

    # Obtener el registro actual
    current_row = df_view.iloc[cur_idx]
    real_idx = current_row.name  # Índice original en df_master

    # Datos del registro
    titulo_orig = str(current_row.get("Titulo", "")).strip()
    titulo_es = str(current_row.get("Titulo ES", "")).strip()
    abstract_orig = str(current_row.get("Abstract", "")).strip()
    abstract_es = str(current_row.get("Abstract ES", "")).strip()
    autor = str(current_row.get("Autor", "")).strip()
    revista = str(current_row.get("Revista", "")).strip()
    tipo_doc = str(current_row.get("TipoDocumento", "")).strip()
    keywords = str(current_row.get("Keywords", "")).strip()
    fuente = str(current_row.get("Fuente", "")).strip()
    anio = str(current_row.get("Año", "")).strip()
    doi = str(current_row.get("DOI", "")).strip()
    url = str(current_row.get("URL", "")).strip()
    archivo_origen = str(current_row.get("ArchivoOrigen", "")).strip()
    f0_score = current_row.get("F0_Score", None)
    current_decision = int(current_row.get("Seleccion_Manual", 0))

    # TARJETA TIPO TINDER
    with st.container(border=True):
        # BANNER DESTACADO DE ESTADO DE LA DECISIÓN (GRANDE Y CLARO)
        if current_decision == 1:
            st.success("### ✅ ARTÍCULO INCLUIDO EN LA REVISIÓN (Valor: 1)")
        elif current_decision == -1:
            st.error("### ❌ ARTÍCULO EXCLUIDO DE LA REVISIÓN (Valor: -1)")
        else:
            st.warning("### ⏳ REGISTRO PENDIENTE DE EVALUACIÓN (Valor: 0)")

        # Insignias y metadatos superiores
        b1, b2, b3 = st.columns([1.5, 1, 1.2])
        with b1:
            st.markdown(f"**🏛️ Fuente:** `{fuente}`")
        with b2:
            st.markdown(f"**📅 Año:** `{anio}`")
        with b3:
            if pd.notna(f0_score) and f0_score != "":
                st.markdown(f"**⭐ Score F0:** `{f0_score}`")
            else:
                st.markdown("**⭐ Score:** `N/A`")

        st.divider()

        # TÍTULOS
        if titulo_es and titulo_es.lower() != "nan" and titulo_es != titulo_orig:
            st.markdown(f"### 🇪🇸 {titulo_es}")
            st.markdown(f"**🇬🇧 Original:** *{titulo_orig}*")
        else:
            st.markdown(f"### 🇬🇧 {titulo_orig}")
            if not titulo_es or titulo_es.lower() == "nan":
                st.caption("*(Traducción al español pendiente)*")

        # METADATOS: AUTORES, REVISTA/PUBLICACIÓN, TIPO DE DOCUMENTO
        if autor and autor.lower() != "nan":
            st.markdown(f"**👥 Autores:** {autor}")

        sub_meta = []
        if revista and revista.lower() != "nan":
            sub_meta.append(f"**📖 Revista / Publicación:** *{revista}*")
        if tipo_doc and tipo_doc.lower() != "nan":
            sub_meta.append(f"**🏷️ Tipo:** `{tipo_doc}`")
        if sub_meta:
            st.markdown(" &bull; ".join(sub_meta))

        if keywords and keywords.lower() != "nan":
            st.caption(f"**🔑 Palabras clave:** {keywords}")

        footer_links = []
        if url or doi:
            link_target = url if url.startswith("http") else (f"https://doi.org/{doi}" if doi else "")
            doi_display = doi if doi else "Enlace al artículo"
            if link_target:
                footer_links.append(f"🔗 [DOI: {doi_display}]({link_target})")
        if archivo_origen and archivo_origen.lower() != "nan":
            footer_links.append(f"📁 Archivo: `{archivo_origen}`")
        if footer_links:
            st.caption(" &bull; ".join(footer_links))

        st.markdown("---")

        # ABSTRACT / RESUMEN
        idioma_view = st.radio(
            "Ver abstract en:",
            ["🇪🇸 Español", "🇬🇧 Inglés", "Ambos"],
            horizontal=True,
            key=f"ms_lang_opt_{real_idx}",
        )

        has_abstract_es = bool(abstract_es and abstract_es.lower() != "nan")
        has_abstract_orig = bool(abstract_orig and abstract_orig.lower() != "nan")

        if idioma_view == "🇪🇸 Español":
            if has_abstract_es:
                st.markdown(abstract_es)
            else:
                st.info("Resumen en español no disponible para este registro. Mostrando versión original:")
                st.markdown(abstract_orig if has_abstract_orig else "*Sin abstract disponible.*")
        elif idioma_view == "🇬🇧 Inglés":
            st.markdown(abstract_orig if has_abstract_orig else "*Sin abstract disponible.*")
        else:
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                st.markdown("**🇪🇸 Español:**")
                st.markdown(abstract_es if has_abstract_es else "*Traducción pendiente.*")
            with col_a2:
                st.markdown("**🇬🇧 Original:**")
                st.markdown(abstract_orig if has_abstract_orig else "*Sin abstract disponible.*")

        # REPRODUCTOR DE VOZ EN EL NAVEGADOR (WEB SPEECH API)
        with st.expander("🔊 Escuchar lectura con seguimiento de cursor (0 datos móviles)", expanded=False):
            tts_html = build_client_tts_html(
                title_es=titulo_es if (titulo_es and titulo_es.lower() != "nan" and titulo_es != titulo_orig) else "",
                abstract_es=abstract_es if has_abstract_es else "",
                title_en=titulo_orig if (titulo_orig and titulo_orig.lower() != "nan") else "",
                abstract_en=abstract_orig if has_abstract_orig else "",
                default_lang="es" if has_abstract_es else "en",
            )
            components.html(tts_html, height=275, scrolling=False)

        # CASILLA DE COMENTARIOS / ANOTACIONES
        comentario_actual = str(current_row.get("Comentarios", "")).strip()
        if comentario_actual.lower() == "nan":
            comentario_actual = ""

        if comentario_actual:
            st.info(f"📝 **Nota guardada previamente:** {comentario_actual}")

        c_com_txt, c_com_btn = st.columns([3.5, 1])
        with c_com_txt:
            comentario_input = st.text_area(
                "📝 Comentarios / Notas de revisión:",
                value=comentario_actual,
                height=70,
                placeholder="Escribe notas, observaciones o justificación de tu decisión...",
                key=f"ms_comm_{real_idx}",
            )
        with c_com_btn:
            st.write("")
            st.write("")
            if st.button("💾 Guardar nota", key=f"btn_save_note_{real_idx}", use_container_width=True):
                user_comment = st.session_state.get(f"ms_comm_{real_idx}", comentario_input).strip()
                df_master.loc[real_idx, "Comentarios"] = user_comment
                st.session_state["master_df"] = df_master
                st.session_state["master_df_version"] = st.session_state.get("master_df_version", 0) + 1
                safe_save_master_dataframe(df_master)
                save_manual_screening_state({
                    "last_doi": doi,
                    "last_titulo": titulo_orig,
                    "last_index": cur_idx,
                    "sort_by": selected_sort,
                    "filter_by": selected_filter,
                    "auto_advance": auto_advance,
                })
                st.toast("💾 Nota guardada con éxito", icon="✅")
                st.rerun()

        st.divider()

        # BOTONES DE ACCIÓN (ESTILO TINDER CON CONFIRMACIÓN CLARA)
        # ⬅️ Anterior | 🔴 No incluir (-1) | ⚪ Omitir / Siguiente | 🟢 Incluir (1)
        b_prev, b_excl, b_skip, b_incl = st.columns([1, 1.5, 1.2, 1.5])

        def advance_after_action():
            if selected_filter == "Solo pendientes de decisión (0)":
                if cur_idx >= total_view - 1 and cur_idx > 0:
                    st.session_state["ms_index"] = cur_idx - 1
            else:
                if cur_idx < total_view - 1:
                    st.session_state["ms_index"] = cur_idx + 1

        def apply_decision(new_decision_val, should_advance=True):
            user_comment = st.session_state.get(f"ms_comm_{real_idx}", comentario_input).strip()
            df_master.loc[real_idx, "Seleccion_Manual"] = new_decision_val
            df_master.loc[real_idx, "Comentarios"] = user_comment
            st.session_state["master_df"] = df_master
            st.session_state["master_df_version"] = st.session_state.get("master_df_version", 0) + 1
            safe_save_master_dataframe(df_master)

            save_manual_screening_state({
                "last_doi": doi,
                "last_titulo": titulo_orig,
                "last_index": cur_idx,
                "sort_by": selected_sort,
                "filter_by": selected_filter,
                "auto_advance": auto_advance,
            })

            if should_advance:
                advance_after_action()
            st.rerun()

        # Textos contextuales según decisión actual
        if current_decision == 1:
            lbl_incl = "✅ INCLUIDO (1)"
            lbl_excl = "🔴 Cambiar a EXCLUIDO (-1)"
            lbl_skip = "Siguiente ➡️"
        elif current_decision == -1:
            lbl_incl = "🟢 Cambiar a INCLUIDO (1)"
            lbl_excl = "❌ EXCLUIDO (-1)"
            lbl_skip = "Siguiente ➡️"
        else:
            lbl_incl = "🟢 INCLUIR (1)"
            lbl_excl = "🔴 NO INCLUIR (-1)"
            lbl_skip = "⚪ Omitir ➡️"

        with b_prev:
            if st.button("⬅️ Anterior", use_container_width=True, key=f"btn_prev_{cur_idx}"):
                if cur_idx > 0:
                    prev_r = df_view.iloc[cur_idx - 1]
                    st.session_state["ms_index"] = cur_idx - 1
                    save_manual_screening_state({
                        "last_doi": str(prev_r.get("DOI", "")).strip(),
                        "last_titulo": str(prev_r.get("Titulo", "")).strip(),
                        "last_index": cur_idx - 1,
                        "sort_by": selected_sort,
                        "filter_by": selected_filter,
                        "auto_advance": auto_advance,
                    })
                    st.rerun()

        with b_excl:
            if st.button(
                lbl_excl,
                use_container_width=True,
                type="secondary" if current_decision != -1 else "primary",
                key=f"btn_excl_{cur_idx}",
            ):
                st.toast("🔴 Excluido (-1)", icon="❌")
                apply_decision(-1, should_advance=auto_advance)

        with b_skip:
            if st.button(lbl_skip, use_container_width=True, key=f"btn_skip_{cur_idx}"):
                user_comment = st.session_state.get(f"ms_comm_{real_idx}", comentario_input).strip()
                if user_comment != comentario_actual:
                    df_master.loc[real_idx, "Comentarios"] = user_comment
                    st.session_state["master_df"] = df_master
                    st.session_state["master_df_version"] = st.session_state.get("master_df_version", 0) + 1
                    safe_save_master_dataframe(df_master)

                if cur_idx < total_view - 1:
                    next_r = df_view.iloc[cur_idx + 1]
                    st.session_state["ms_index"] = cur_idx + 1
                    save_manual_screening_state({
                        "last_doi": str(next_r.get("DOI", "")).strip(),
                        "last_titulo": str(next_r.get("Titulo", "")).strip(),
                        "last_index": cur_idx + 1,
                        "sort_by": selected_sort,
                        "filter_by": selected_filter,
                        "auto_advance": auto_advance,
                    })
                    st.rerun()

        with b_incl:
            if st.button(
                lbl_incl,
                use_container_width=True,
                type="primary",
                key=f"btn_incl_{cur_idx}",
            ):
                st.toast("🟢 Incluido (1)", icon="✅")
                apply_decision(1, should_advance=auto_advance)
