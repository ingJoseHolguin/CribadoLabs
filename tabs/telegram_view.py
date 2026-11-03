"""Componente UI para la configuración y control del Bot de Telegram en CribadoLabs."""

import streamlit as st

from services.config import load_telegram_config, save_telegram_config
from services.telegram_bot import telegram_bot


def render_telegram_config_panel():
    """Renderiza el panel de control y configuración del Bot de Telegram."""
    status = telegram_bot.get_status()
    is_running = status["running"]
    bot_username = status.get("bot_username")

    expander_title = (
        f"🤖 Bot de Telegram — Cribado Remoto Móvil (🟢 Activo: @{bot_username})"
        if is_running and bot_username
        else "🤖 Bot de Telegram — Cribado Remoto Móvil (Configuración y Control)"
    )

    with st.expander(expander_title, expanded=is_running):
        st.markdown(
            "Permite evaluar, incluir, excluir, agregar notas y consultar resúmenes de tus artículos "
            "directamente desde tu teléfono a través de **Telegram**, sincronizándose automáticamente "
            "con tu tabla maestra Excel."
        )

        config = load_telegram_config()

        # -------------------------------------------------------------
        # 1. ESTADO Y CONTROL DEL SERVICIO
        # -------------------------------------------------------------
        c_status, c_start, c_stop = st.columns([2, 1, 1])

        with c_status:
            if is_running:
                link_html = f"https://t.me/{bot_username}" if bot_username else "#"
                st.success(f"🟢 **Bot ACTIVO:** [{f'@{bot_username}' if bot_username else 'Bot en línea'}]({link_html})")
                if status.get("last_poll"):
                    st.caption(f"Última comprobación: {status['last_poll'].strftime('%H:%M:%S')}")
            else:
                st.warning("🔴 **Bot DETENIDO** (No está escuchando mensajes)")
                st.caption("Configura el token abajo y pulsa 'Iniciar Bot'.")

        with c_start:
            st.write("")
            if st.button("▶️ Iniciar Bot", disabled=is_running, use_container_width=True, type="primary"):
                token = config.get("bot_token", "").strip()
                if not token:
                    st.error("Primero debes guardar el Token de Telegram en el formulario inferior.")
                else:
                    with st.spinner("Conectando con Telegram..."):
                        ok, msg = telegram_bot.start()
                    if ok:
                        st.toast(msg, icon="🤖")
                        st.rerun()
                    else:
                        st.error(msg)

        with c_stop:
            st.write("")
            if st.button("⏹️ Detener Bot", disabled=not is_running, use_container_width=True):
                ok, msg = telegram_bot.stop()
                st.toast(msg, icon="🛑")
                st.rerun()

        if status.get("last_error"):
            st.warning(f"⚠️ Aviso del bot: {status['last_error']}")

        st.divider()

        # -------------------------------------------------------------
        # 2. CAMPOS DE CONFIGURACIÓN
        # -------------------------------------------------------------
        st.markdown("#### ⚙️ Parámetros de Conexión")

        current_token = config.get("bot_token", "")
        token_input = st.text_input(
            "🔑 Token del Bot (proporcionado por @BotFather):",
            value=current_token,
            type="password",
            placeholder="Ejemplo: 7123456789:AAHk1234567890abcdef...",
            help="Copia el token que te entregó @BotFather al crear el bot.",
        )

        allowed_ids_list = config.get("allowed_chat_ids", [])
        allowed_ids_default = ", ".join(map(str, allowed_ids_list))
        allowed_ids_input = st.text_input(
            "🛡️ IDs de Telegram Autorizados (Opcional por seguridad):",
            value=allowed_ids_default,
            placeholder="Ejemplo: 123456789, 987654321 (dejar vacío para permitir tu propio chat)",
            help=(
                "Lista de números ID de usuario separados por coma. Si lo dejas vacío, cualquier persona con el enlace podrá interactuar. "
                "Si no sabes tu ID, habla a tu bot con /start y él te mostrará tu ID para que lo pegues aquí."
            ),
        )

        col_opt1, col_opt2, col_opt3 = st.columns(3)
        with col_opt1:
            auto_adv = st.checkbox(
                "⚡ Auto-avanzar al decidir en Telegram",
                value=config.get("auto_advance", True),
                help="Al pulsar Incluir o Excluir en Telegram, envía inmediatamente la tarjeta del siguiente artículo.",
            )
        with col_opt2:
            lang_options = ["es", "en", "ambos"]
            curr_lang = config.get("default_lang", "es")
            lang_idx = lang_options.index(curr_lang) if curr_lang in lang_options else 0
            default_lang = st.selectbox(
                "🌐 Idioma del abstract:",
                lang_options,
                index=lang_idx,
                format_func=lambda x: "🇪🇸 Español" if x == "es" else ("🇬🇧 Inglés" if x == "en" else "🇪🇸/🇬🇧 Ambos"),
            )
        with col_opt3:
            voice_options = [
                ("es-ES-ElviraNeural", "Elvira (España, Femenino ⭐)"),
                ("es-MX-DaliaNeural", "Dalia (México, Femenino)"),
                ("es-CO-SalomeNeural", "Salomé (Colombia, Femenino)"),
                ("es-AR-ElenaNeural", "Elena (Argentina, Femenino)"),
                ("es-ES-AlvaroNeural", "Álvaro (España, Masculino)"),
                ("es-MX-JorgeNeural", "Jorge (México, Masculino)"),
            ]
            voice_ids = [v[0] for v in voice_options]
            curr_voice = config.get("tts_voice", "es-ES-ElviraNeural")
            v_idx = voice_ids.index(curr_voice) if curr_voice in voice_ids else 0
            selected_voice = st.selectbox(
                "🔊 Voz para audio en Telegram:",
                voice_ids,
                index=v_idx,
                format_func=lambda x: next((v[1] for v in voice_options if v[0] == x), x),
                help="Voz neural con la que el bot generará las notas de voz en Telegram.",
            )

        col_save, col_test = st.columns([1, 1.5])
        with col_save:
            if st.button("💾 Guardar Configuración", use_container_width=True, type="secondary"):
                parsed_ids = []
                if allowed_ids_input.strip():
                    for raw_id in allowed_ids_input.split(","):
                        clean_id = raw_id.strip()
                        if clean_id:
                            parsed_ids.append(clean_id)

                new_config = {
                    "bot_token": token_input.strip(),
                    "allowed_chat_ids": parsed_ids,
                    "auto_advance": auto_adv,
                    "default_lang": default_lang,
                    "tts_voice": selected_voice,
                }
                save_telegram_config(new_config)
                st.success("Configuración de Telegram guardada correctamente.")

        with col_test:
            test_chat_id = st.text_input(
                "Chat ID para mensaje de prueba (opcional):",
                value=allowed_ids_list[0] if allowed_ids_list else "",
                placeholder="ID numérico de tu chat",
                label_visibility="collapsed",
            )
            if st.button("🧪 Probar Conexión y Enviar Mensaje de Prueba", use_container_width=True):
                if not token_input.strip():
                    st.error("Ingresa primero el Token del bot.")
                else:
                    with st.spinner("Verificando token y enviando mensaje..."):
                        ok, msg, bot_info = telegram_bot.test_connection(token_input.strip(), test_chat_id.strip())
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")

        st.divider()

        # -------------------------------------------------------------
        # 3. GUÍA PASO A PASO E INSTRUCCIONES
        # -------------------------------------------------------------
        st.markdown("#### 📖 Instrucciones de Configuración y Comandos")

        tab_guide1, tab_guide2 = st.tabs(["🚀 Cómo crear tu Bot en 1 minuto", "⌨️ Comandos, Botones y Audio en Telegram"])

        with tab_guide1:
            st.markdown(
                """
                1. **Abre Telegram** y busca al usuario oficial **`@BotFather`** (tiene insignia de verificación azul).
                2. Envíale el comando **`/newbot`**.
                3. Escribe un **nombre** para tu bot (ejemplo: *Cribado Scoping Review*).
                4. Escribe un **nombre de usuario** único terminado en `bot` (ejemplo: *mi_cribado_review_bot*).
                5. BotFather te responderá felicitándote y te entregará tu **Token HTTP API** (una cadena como `7123456789:AAH...`).
                6. **Copia el Token**, pégalo arriba en el campo *"Token del Bot"* y haz clic en **💾 Guardar Configuración**.
                7. Entra a tu nuevo bot en Telegram (haz clic en su enlace `t.me/...`) y presiona el botón **INICIAR** o escribe **`/start`**.
                8. Haz clic en **`▶️ Iniciar Bot`** arriba en este panel. ¡Ya puedes hacer el cribado desde tu móvil!
                """
            )

        with tab_guide2:
            st.markdown(
                """
                **Botonera interactiva en cada mensaje:**
                - `🟢 Incluir (+1)` / `🔴 Excluir (-1)`: Registra la decisión en la columna `Seleccion_Manual` de Excel.
                - `⬅️ Anterior` / `⚪ Omitir ➡️`: Navega entre artículos sin perder tu lugar.
                - `🎧 Escuchar Audio`: Genera y envía una **nota de voz neural** con el título y resumen para escuchar mientras caminas o viajas.
                - `📝 Añadir Nota`: Te pide escribir un texto para guardarlo en la columna `Comentarios`.
                - `🌐 Idioma`: Alterna en tiempo real entre resumen en español, inglés o ambos.
                - `🔍 Sig. Pendiente`: Salta directamente al siguiente artículo que aún no tenga decisión.
                - `📊 Progreso`: Muestra el porcentaje evaluado y totales PRISMA.

                **Comandos de texto que puedes escribir en el chat:**
                | Comando | Descripción |
                |---|---|
                | `/start` | Abre el menú de bienvenida y teclado de acceso rápido |
                | `/audio` o `/escuchar` | **Genera y envía la nota de voz** del artículo actual |
                | `/audio 15` | Escucha la nota de voz del artículo #15 directamente |
                | `/siguiente` | Avanza al siguiente artículo |
                | `/anterior` | Retrocede al artículo previo |
                | `/pendiente` | Salta al próximo registro sin evaluar (`0`) |
                | `/ir 25` | Salta directamente al registro número 25 |
                | `/nota [texto]` | Guarda una nota o justificación en el artículo actual |
                | `/estado` | Muestra el resumen y porcentaje de avance |
                | `/ayuda` | Muestra la lista de atajos y ayuda |

                *Nota:* En Telegram puedes acelerar las notas de voz a **1.5x o 2x** y continuar escuchándolas en segundo plano con la pantalla bloqueada.
                """
            )
