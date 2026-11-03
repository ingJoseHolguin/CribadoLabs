"""Servicio del Bot de Telegram para Selección Manual (Cribado Remoto Móvil)."""

import asyncio
import html
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
import pandas as pd
import requests

from services.config import (
    load_manual_screening_state,
    load_telegram_config,
    save_manual_screening_state,
    save_telegram_config,
)
from services.persistence import (
    GLOBAL_EXCEL_LOCK as EXCEL_LOCK,
    MASTER_FILENAME,
    OUTPUT_FOLDER,
    load_master_dataframe,
    save_master_dataframe,
)

logger = logging.getLogger(__name__)


def escape_html(text: Any) -> str:
    """Escapa texto plano para uso seguro en modo HTML de Telegram."""
    if text is None:
        return ""
    s = str(text)
    if s.lower() == "nan":
        return ""
    return html.escape(s)


async def _synthesize_edge_tts(text: str, voice: str) -> bytes:
    """Genera audio en streaming directamente en memoria con edge-tts."""
    comm = edge_tts.Communicate(text, voice)
    audio_data = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    return bytes(audio_data)


def synthesize_speech_bytes(text: str, voice: str = "es-ES-ElviraNeural") -> bytes:
    """Invoca la síntesis neural de audio y retorna bytes MP3 en memoria."""
    try:
        return asyncio.run(_synthesize_edge_tts(text, voice))
    except Exception as e:
        logger.error(f"Error generando audio con edge-tts: {e}")
        return b""


def _build_speech_text(
    row: pd.Series, lang_mode: str = "es", voice_pref: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Construye el texto a narrar, la voz a usar y el título para la pista.
    Retorna: (narrative_text, voice_to_use, short_title)
    """
    titulo_es = str(row.get("Titulo ES", "")).strip()
    titulo_orig = str(row.get("Titulo", "")).strip()
    abstract_es = str(row.get("Abstract ES", "")).strip()
    abstract_orig = str(row.get("Abstract", "")).strip()
    autor = str(row.get("Autor", "")).strip()
    revista = str(row.get("Revista", "")).strip()
    anio = str(row.get("Año", "")).strip()

    has_es = bool(abstract_es and abstract_es.lower() != "nan")
    has_orig = bool(abstract_orig and abstract_orig.lower() != "nan")

    config = load_telegram_config()
    default_voice = voice_pref or config.get("tts_voice", "es-ES-ElviraNeural")

    parts = []
    short_title = titulo_es if has_es and titulo_es.lower() != "nan" else titulo_orig
    if len(short_title) > 60:
        short_title = short_title[:57] + "..."

    if lang_mode == "en" or (not has_es and has_orig):
        parts.append(f"Title: {titulo_orig}.")
        if autor and autor.lower() != "nan":
            parts.append(f"Authors: {autor}.")
        if revista and revista.lower() != "nan":
            parts.append(f"Journal: {revista}, year {anio}.")
        parts.append(f"Abstract: {abstract_orig if has_orig else 'No abstract available.'}")
        voice_to_use = "en-US-JennyNeural"
    elif lang_mode == "ambos" and has_orig and has_es:
        tit_es = titulo_es if titulo_es and titulo_es.lower() != "nan" else titulo_orig
        parts.append(f"Título: {tit_es}.")
        if revista and revista.lower() != "nan":
            parts.append(f"Publicado en: {revista}, año {anio}.")
        parts.append(f"Resumen en español: {abstract_es}.")
        parts.append(f"Original abstract in English: {abstract_orig}.")
        voice_to_use = default_voice
    else:  # Español
        tit_es = titulo_es if has_es and titulo_es.lower() != "nan" else titulo_orig
        parts.append(f"Título: {tit_es}.")
        if autor and autor.lower() != "nan":
            auts = [a.strip() for a in (autor.split(";") if ";" in autor else autor.split(","))]
            if len(auts) > 2:
                aut_text = f"{auts[0]} y colaboradores"
            else:
                aut_text = autor
            parts.append(f"Autores: {aut_text}.")
        if revista and revista.lower() != "nan":
            parts.append(f"Revista: {revista}.")
        if anio and anio.lower() != "nan":
            parts.append(f"Año: {anio}.")
        parts.append(f"Resumen: {abstract_es if has_es else abstract_orig}.")
        voice_to_use = default_voice

    narrative = " ".join(parts)
    return narrative, voice_to_use, short_title


class TelegramBotManager:
    """Administrador y controlador del servicio del Bot de Telegram."""

    _instance: Optional["TelegramBotManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.is_active = False
        self.last_error: Optional[str] = None
        self.bot_info: Optional[Dict[str, Any]] = None
        self.last_poll_time: Optional[datetime] = None
        # Estados por chat_id: {chat_id: {"index": int, "awaiting_note": bool, "lang": str}}
        self.chat_states: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> "TelegramBotManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---------------------------------------------------------
    # API DE TELEGRAM (MÉTODOS HTTP BÁSICOS)
    # ---------------------------------------------------------
    @staticmethod
    def _api_url(token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    def test_connection(self, token: str, test_chat_id: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """Verifica la validez del token y opcionalmente envía un mensaje de prueba."""
        token = token.strip()
        if not token:
            return False, "El token de Telegram no puede estar vacío.", {}

        try:
            resp = requests.get(self._api_url(token, "getMe"), timeout=10)
            data = resp.json()
            if not data.get("ok"):
                return False, f"Token inválido: {data.get('description', 'Error desconocido')}", {}

            bot_info = data.get("result", {})
            bot_name = bot_info.get("first_name", "Bot")
            bot_username = bot_info.get("username", "")

            if test_chat_id:
                test_chat_id = str(test_chat_id).strip()
                if test_chat_id:
                    msg_text = (
                        f"🤖 <b>¡Conexión Exitosa con CribadoLabs!</b>\n\n"
                        f"Hola, este es un mensaje de prueba enviado desde CribadoLabs.\n"
                        f"Bot: <b>@{bot_username}</b> ({bot_name})\n"
                        f"Fecha: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
                        f"Envía <code>/start</code> para abrir el menú de cribado manual."
                    )
                    send_resp = requests.post(
                        self._api_url(token, "sendMessage"),
                        json={"chat_id": test_chat_id, "text": msg_text, "parse_mode": "HTML"},
                        timeout=10,
                    )
                    send_data = send_resp.json()
                    if not send_data.get("ok"):
                        return False, (
                            f"El bot @{bot_username} es válido, pero no se pudo enviar el mensaje al Chat ID {test_chat_id}: "
                            f"{send_data.get('description')}. Asegúrate de haber iniciado conversación con el bot primero (/start)."
                        ), bot_info

            return True, f"Conexión exitosa con @{bot_username} ({bot_name})", bot_info

        except Exception as e:
            return False, f"Error de red o conexión: {str(e)}", {}

    def _send_message(
        self, token: str, chat_id: str, text: str, reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = requests.post(self._api_url(token, "sendMessage"), json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            logger.warning(f"Error sendMessage: {data.get('description')}")
        except Exception as e:
            logger.error(f"Excepción en _send_message: {e}")
        return None

    def _edit_message_text(
        self, token: str, chat_id: str, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = requests.post(self._api_url(token, "editMessageText"), json=payload, timeout=15)
            data = resp.json()
            return bool(data.get("ok"))
        except Exception as e:
            logger.error(f"Excepción en _edit_message_text: {e}")
            return False

    def _answer_callback(self, token: str, callback_id: str, text: str = "", alert: bool = False):
        try:
            requests.post(
                self._api_url(token, "answerCallbackQuery"),
                json={"callback_query_id": callback_id, "text": text, "show_alert": alert},
                timeout=10,
            )
        except Exception as e:
            logger.debug(f"Error respondiendo callback: {e}")

    def _send_voice(
        self, token: str, chat_id: str, audio_bytes: bytes, caption: str = ""
    ) -> bool:
        """Envía una nota de voz nativa de Telegram con waveform y velocidad 1x/1.5x/2x."""
        try:
            url = self._api_url(token, "sendVoice")
            files = {"voice": ("resumen.mp3", audio_bytes, "audio/mpeg")}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            resp = requests.post(url, data=data, files=files, timeout=40)
            res_json = resp.json()
            if not res_json.get("ok"):
                logger.warning(f"Error sendVoice: {res_json.get('description')}")
                # Fallback a sendAudio
                return self._send_audio(token, chat_id, audio_bytes, "Resumen", "CribadoLabs", caption)
            return True
        except Exception as e:
            logger.error(f"Excepción en _send_voice: {e}")
            return False

    def _send_audio(
        self, token: str, chat_id: str, audio_bytes: bytes, title: str, performer: str, caption: str = ""
    ) -> bool:
        """Envía una pista de audio MP3 para reproducción en segundo plano."""
        try:
            url = self._api_url(token, "sendAudio")
            files = {"audio": ("resumen.mp3", audio_bytes, "audio/mpeg")}
            data = {
                "chat_id": chat_id,
                "title": title,
                "performer": performer,
                "caption": caption,
                "parse_mode": "HTML",
            }
            resp = requests.post(url, data=data, files=files, timeout=40)
            return bool(resp.json().get("ok"))
        except Exception as e:
            logger.error(f"Excepción en _send_audio: {e}")
            return False

    # ---------------------------------------------------------
    # GESTIÓN DE DATOS Y ARTÍCULOS
    # ---------------------------------------------------------
    def _get_sorted_dataframe(self) -> pd.DataFrame:
        """Carga el DataFrame maestro y lo ordena por F0_Score descendente."""
        with EXCEL_LOCK:
            df = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
        if df.empty:
            return df
        if "Seleccion_Manual" not in df.columns:
            df["Seleccion_Manual"] = 0
        df["Seleccion_Manual"] = pd.to_numeric(df["Seleccion_Manual"], errors="coerce").fillna(0).astype(int)
        if "Comentarios" not in df.columns:
            df["Comentarios"] = ""
        df["Comentarios"] = df["Comentarios"].fillna("").astype(object)

        if "F0_Score" in df.columns:
            return df.sort_values(by="F0_Score", ascending=False, kind="stable")
        return df

    def _save_article_decision(self, real_idx: Any, decision: int, comment: Optional[str] = None):
        """Persiste la decisión y/o comentario del artículo de forma segura en Excel y JSON."""
        with EXCEL_LOCK:
            df = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
            if real_idx in df.index:
                df.loc[real_idx, "Seleccion_Manual"] = decision
                if comment is not None:
                    df.loc[real_idx, "Comentarios"] = comment.strip()
                save_master_dataframe(df)

                # Persistir estado global
                row = df.loc[real_idx]
                save_manual_screening_state({
                    "last_doi": str(row.get("DOI", "")).strip(),
                    "last_titulo": str(row.get("Titulo", "")).strip(),
                    "last_decision": int(decision),
                })

    def _save_article_comment(self, real_idx: Any, comment: str):
        """Persiste únicamente el comentario en el artículo."""
        with EXCEL_LOCK:
            df = load_master_dataframe(OUTPUT_FOLDER / MASTER_FILENAME)
            if real_idx in df.index:
                df.loc[real_idx, "Comentarios"] = comment.strip()
                save_master_dataframe(df)

    def _send_article_voice_helper(
        self, token: str, chat_id: str, row: pd.Series, idx: int, lang_mode: str = "es"
    ) -> bool:
        """Sintetiza y envía la nota de voz del artículo a un chat."""
        try:
            speech_text, voice_to_use, short_title = _build_speech_text(row, lang_mode=lang_mode)
            audio_bytes = synthesize_speech_bytes(speech_text, voice=voice_to_use)
            if audio_bytes:
                caption = (
                    f"🎧 <b>Audio del Registro #{idx + 1}</b>\n"
                    f"<i>{escape_html(short_title)}</i>\n\n"
                    f"🔊 Voz: <code>{voice_to_use}</code>"
                )
                return self._send_voice(token, chat_id, audio_bytes, caption=caption)
            return False
        except Exception as e:
            logger.error(f"Error en _send_article_voice_helper: {e}")
            return False

    def _build_article_card(
        self, row: pd.Series, view_idx: int, total: int, lang_mode: str = "es", auto_audio: bool = False
    ) -> Tuple[str, Dict[str, Any]]:
        """Construye el texto formateado HTML y el teclado inline de un artículo para Telegram."""
        titulo_orig = str(row.get("Titulo", "")).strip()
        titulo_es = str(row.get("Titulo ES", "")).strip()
        autor = str(row.get("Autor", "")).strip()
        revista = str(row.get("Revista", "")).strip()
        tipo_doc = str(row.get("TipoDocumento", "")).strip()
        fuente = str(row.get("Fuente", "")).strip()
        anio = str(row.get("Año", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        url = str(row.get("URL", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        f0_score = row.get("F0_Score", None)
        decision = int(row.get("Seleccion_Manual", 0))
        comentario = str(row.get("Comentarios", "")).strip()
        if comentario.lower() == "nan":
            comentario = ""

        # Indicador de estado
        if decision == 1:
            status_badge = "🟢 <b>INCLUIDO (1)</b>"
        elif decision == -1:
            status_badge = "🔴 <b>EXCLUIDO (-1)</b>"
        else:
            status_badge = "⏳ <b>PENDIENTE (0)</b>"

        score_badge = f"⭐ F0: <b>{f0_score}</b>" if pd.notna(f0_score) and f0_score != "" else "⭐ Score: N/A"

        # Encabezado
        lines = [
            f"📄 <b>Registro #{view_idx + 1} de {total}</b> &bull; {score_badge}",
            f"🏛️ <i>{escape_html(fuente)}</i> &bull; 📅 <i>{escape_html(anio)}</i> &bull; 🏷️ <i>{escape_html(tipo_doc)}</i>",
            f"Estado actual: {status_badge}",
            "",
        ]

        # Título principal
        has_es_title = bool(titulo_es and titulo_es.lower() != "nan" and titulo_es != titulo_orig)
        if has_es_title:
            lines.append(f"🇪🇸 <b>{escape_html(titulo_es)}</b>")
            lines.append(f"🇬🇧 <i>{escape_html(titulo_orig)}</i>")
        else:
            lines.append(f"🇬🇧 <b>{escape_html(titulo_orig)}</b>")

        lines.append("")

        # Metadatos
        if autor and autor.lower() != "nan":
            lines.append(f"👥 <b>Autores:</b> {escape_html(autor)}")
        if revista and revista.lower() != "nan":
            lines.append(f"📖 <b>Revista/Pub:</b> <i>{escape_html(revista)}</i>")
        if keywords and keywords.lower() != "nan":
            # recortar keywords si son demasiado largas
            kw_disp = keywords[:150] + "..." if len(keywords) > 150 else keywords
            lines.append(f"🔑 <b>Keywords:</b> <code>{escape_html(kw_disp)}</code>")

        # Abstract según modo de idioma
        abstract_orig = str(row.get("Abstract", "")).strip()
        abstract_es = str(row.get("Abstract ES", "")).strip()
        has_ab_es = bool(abstract_es and abstract_es.lower() != "nan")
        has_ab_orig = bool(abstract_orig and abstract_orig.lower() != "nan")

        lines.append("\n📝 <b>Resumen:</b>")
        if lang_mode == "en":
            ab_text = abstract_orig if has_ab_orig else "<i>(Sin abstract original disponible)</i>"
            lines.append(escape_html(ab_text[:1800]))
            if len(ab_text) > 1800:
                lines.append("<i>[...resumen recortado por longitud de Telegram]</i>")
        elif lang_mode == "ambos":
            if has_ab_es:
                lines.append(f"<b>[ES]</b> {escape_html(abstract_es[:900])}")
            if has_ab_orig:
                lines.append(f"<b>[EN]</b> <i>{escape_html(abstract_orig[:900])}</i>")
        else:  # 'es' por defecto
            if has_ab_es:
                lines.append(escape_html(abstract_es[:1800]))
                if len(abstract_es) > 1800:
                    lines.append("<i>[...resumen recortado por longitud de Telegram]</i>")
            elif has_ab_orig:
                lines.append(f"<i>(Traducción ES no disp.)</i>\n{escape_html(abstract_orig[:1800])}")
            else:
                lines.append("<i>(Sin abstract disponible)</i>")

        # Enlace DOI
        link_target = url if url.startswith("http") else (f"https://doi.org/{doi}" if doi else "")
        if link_target:
            lines.append(f"\n🔗 <a href='{link_target}'>Ver artículo original (DOI/Web)</a>")

        # Comentario si existe
        if comentario:
            lines.append(f"\n📌 <b>Nota guardada:</b> <i>{escape_html(comentario)}</i>")

        text = "\n".join(lines)

        # Teclado inline
        # Fila 1: Decisión
        btn_incl = "✅ INCLUIDO (1)" if decision == 1 else "🟢 Incluir (+1)"
        btn_excl = "❌ EXCLUIDO (-1)" if decision == -1 else "🔴 Excluir (-1)"
        btn_auto = "🎧 Auto-Audio: ON ✅" if auto_audio else "🎧 Auto-Audio: OFF ⚪"

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": btn_incl, "callback_data": f"dec_1_{view_idx}"},
                    {"text": btn_excl, "callback_data": f"dec_-1_{view_idx}"},
                ],
                [
                    {"text": "⬅️ Anterior", "callback_data": f"nav_prev_{view_idx}"},
                    {"text": "⚪ Omitir ➡️", "callback_data": f"nav_next_{view_idx}"},
                ],
                [
                    {"text": "🎧 Escuchar Audio", "callback_data": f"audio_{view_idx}"},
                    {"text": "📝 Añadir Nota", "callback_data": f"note_{view_idx}"},
                ],
                [
                    {"text": f"🌐 Idioma ({lang_mode.upper()})", "callback_data": f"lang_{view_idx}"},
                    {"text": "🔍 Sig. Pendiente", "callback_data": f"pend_{view_idx}"},
                ],
                [
                    {"text": btn_auto, "callback_data": f"toggleaudio_{view_idx}"},
                    {"text": "📊 Progreso", "callback_data": f"stats_{view_idx}"},
                ],
            ]
        }

        return text, keyboard

    def _get_stats_text(self, df: pd.DataFrame) -> str:
        """Genera mensaje de métricas globales del cribado."""
        tot = len(df)
        if tot == 0:
            return "📊 <b>Métricas de Cribado</b>\nNo hay registros cargados en la base."

        incl = int((df["Seleccion_Manual"] == 1).sum())
        excl = int((df["Seleccion_Manual"] == -1).sum())
        pend = int((df["Seleccion_Manual"] == 0).sum())
        revisados = incl + excl
        pct = (revisados / tot) * 100 if tot > 0 else 0

        bar_len = 10
        filled = int(round(pct / 10))
        bar = "🟩" * filled + "⬜" * (bar_len - filled)

        return (
            f"📊 <b>Estado del Cribado Manual (PRISMA)</b>\n\n"
            f"Progreso: <b>{pct:.1f}%</b> ({revisados:,} de {tot:,} evaluados)\n"
            f"{bar}\n\n"
            f"🟢 <b>Incluidos:</b> {incl:,}\n"
            f"🔴 <b>Excluidos:</b> {excl:,}\n"
            f"⏳ <b>Pendientes:</b> {pend:,}\n"
            f"📚 <b>Total registros:</b> {tot:,}"
        )

    # ---------------------------------------------------------
    # BUCLE PRINCIPAL DE POLLING EN SEGUNDO PLANO
    # ---------------------------------------------------------
    def start(self) -> Tuple[bool, str]:
        """Inicia el bot en un hilo en segundo plano."""
        if self.is_active and self.thread and self.thread.is_alive():
            return True, "El bot de Telegram ya se encuentra en ejecución."

        config = load_telegram_config()
        token = config.get("bot_token", "").strip()
        if not token:
            return False, "Falta configurar el Token del Bot de Telegram en CribadoLabs."

        # Probar token
        ok, msg, bot_info = self.test_connection(token)
        if not ok:
            return False, msg

        self.bot_info = bot_info
        self.stop_event.clear()
        self.is_active = True
        self.last_error = None

        self.thread = threading.Thread(target=self._polling_loop, args=(token,), daemon=True)
        self.thread.start()

        bot_user = bot_info.get("username", "")
        return True, f"Bot @{bot_user} iniciado con éxito en segundo plano."

    def stop(self) -> Tuple[bool, str]:
        """Detiene el bot de forma limpia."""
        if not self.is_active:
            return True, "El bot ya estaba detenido."

        self.stop_event.set()
        self.is_active = False
        return True, "Bot de Telegram detenido."

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado actual del bot."""
        running = self.is_active and self.thread is not None and self.thread.is_alive()
        return {
            "running": running,
            "bot_username": self.bot_info.get("username") if self.bot_info else None,
            "bot_name": self.bot_info.get("first_name") if self.bot_info else None,
            "last_poll": self.last_poll_time,
            "last_error": self.last_error,
            "active_chats_count": len(self.chat_states),
        }

    def _polling_loop(self, token: str):
        """Bucle de escucha de mensajes y callbacks de Telegram (Long-Polling)."""
        offset = 0
        logger.info("Iniciando bucle de polling de Telegram...")

        while not self.stop_event.is_set():
            try:
                self.last_poll_time = datetime.now()
                params = {"timeout": 15, "offset": offset}
                resp = requests.get(self._api_url(token, "getUpdates"), params=params, timeout=25)
                data = resp.json()

                if not data.get("ok"):
                    self.last_error = data.get("description", "Error getUpdates")
                    time.sleep(3)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    offset = max(offset, update["update_id"] + 1)
                    try:
                        self._handle_update(token, update)
                    except Exception as e:
                        logger.error(f"Error procesando update {update.get('update_id')}: {e}")

            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as e:
                self.last_error = f"Error de red: {e}"
                time.sleep(4)
            except Exception as e:
                self.last_error = f"Excepción general: {e}"
                time.sleep(3)

        self.is_active = False
        logger.info("Bucle de polling de Telegram finalizado.")

    def _is_chat_allowed(self, chat_id: str) -> bool:
        """Valida si el chat_id está autorizado según telegram_config.json."""
        config = load_telegram_config()
        allowed = config.get("allowed_chat_ids", [])
        if not allowed:
            # Si no hay lista restrictiva, se permite interacción
            return True
        allowed_str = [str(x).strip() for x in allowed if str(x).strip()]
        if not allowed_str:
            return True
        return str(chat_id).strip() in allowed_str

    def _handle_update(self, token: str, update: Dict[str, Any]):
        """Despacha mensajes de texto y callbacks interactivos."""
        if "message" in update:
            self._handle_message(token, update["message"])
        elif "callback_query" in update:
            self._handle_callback_query(token, update["callback_query"])

    def _handle_message(self, token: str, msg: Dict[str, Any]):
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        text = msg.get("text", "").strip()

        if not text:
            return

        # Verificación de seguridad de chat_id
        if not self._is_chat_allowed(chat_id):
            unauth_msg = (
                f"⛔ <b>Acceso no autorizado</b>\n\n"
                f"Tu Chat ID de Telegram es: <code>{chat_id}</code>\n\n"
                f"Por seguridad, agrégalo al campo <i>'IDs de Telegram permitidos'</i> en la pestaña de Selección Manual de CribadoLabs para comenzar."
            )
            self._send_message(token, chat_id, unauth_msg)
            return

        # Inicializar estado del chat si no existe
        config = load_telegram_config()
        if chat_id not in self.chat_states:
            self.chat_states[chat_id] = {
                "index": 0,
                "awaiting_note": False,
                "lang": config.get("default_lang", "es"),
                "auto_audio": config.get("auto_send_audio", False),
            }

        state = self.chat_states[chat_id]
        auto_audio = state.get("auto_audio", config.get("auto_send_audio", False))

        # Si el usuario estaba escribiendo una nota para el artículo actual
        if state.get("awaiting_note"):
            state["awaiting_note"] = False
            df = self._get_sorted_dataframe()
            cur_idx = state.get("index", 0)
            if not df.empty and 0 <= cur_idx < len(df):
                row = df.iloc[cur_idx]
                real_idx = row.name
                self._save_article_comment(real_idx, text)
                ack = (
                    f"💾 <b>Nota guardada para el registro #{cur_idx + 1}:</b>\n"
                    f"<i>{escape_html(text)}</i>"
                )
                self._send_message(token, chat_id, ack)
                # Volver a enviar la tarjeta actualizada
                df_updated = self._get_sorted_dataframe()
                row_upd = df_updated.iloc[cur_idx]
                card_text, kb = self._build_article_card(
                    row_upd, cur_idx, len(df_updated), state.get("lang", "es"), auto_audio=auto_audio
                )
                self._send_message(token, chat_id, card_text, kb)
                return

        cmd = text.split()[0].lower()

        if cmd in ("/start", "/menu", "/inicio"):
            welcome = (
                "👋 <b>¡Bienvenido al Bot de Cribado Manual de CribadoLabs!</b>\n\n"
                "Desde aquí puedes evaluar y clasificar tus artículos científicos directamente desde el móvil:\n\n"
                "• 🟢 <b>Incluir (+1)</b>: Marca como incluido en tu scoping review.\n"
                "• 🔴 <b>Excluir (-1)</b>: Descarta el artículo.\n"
                "• ⚪ <b>Omitir / Siguiente</b>: Pasa al siguiente sin alterar decisión.\n"
                "• 🎧 <b>Escuchar Audio</b>: Escucha el título y resumen narrado con voz neural.\n"
                "• ⚡ <b>Auto-Audio</b>: ON/OFF para narrar cada artículo nuevo automáticamente al avanzar.\n"
                "• 📝 <b>Añadir Nota</b>: Escribe justificación o comentarios.\n"
                "• 🌐 <b>Idioma</b>: Alterna entre abstract en español, inglés o ambos.\n\n"
                "<b>Comandos útiles:</b>\n"
                "• <code>/siguiente</code> — Ver el próximo artículo\n"
                "• <code>/anterior</code> — Volver al artículo previo\n"
                "• <code>/pendiente</code> — Saltar al siguiente registro sin evaluar\n"
                "• <code>/audio</code> — Escuchar el resumen del artículo actual\n"
                "• <code>/autoaudio</code> — Activar/Desactivar narración automática\n"
                "• <code>/estado</code> — Ver métricas y avance PRISMA\n"
                "• <code>/ir 15</code> — Saltar directamente al registro #15\n"
                "• <code>/nota [texto]</code> — Guardar nota rápida en el artículo actual"
            )
            # Teclado de inicio
            start_kb = {
                "inline_keyboard": [
                    [{"text": "🚀 Comenzar Evaluación", "callback_data": "start_eval"}],
                    [{"text": "🔍 Ir al Siguiente Pendiente", "callback_data": "pend_0"}],
                    [{"text": f"🎧 Auto-Audio: {'ON ✅' if auto_audio else 'OFF ⚪'}", "callback_data": "toggleaudio_0"}],
                    [{"text": "📊 Ver Métricas", "callback_data": "stats_0"}],
                ]
            }
            self._send_message(token, chat_id, welcome, start_kb)

        elif cmd in ("/autoaudio", "/auto_audio"):
            new_auto = not auto_audio
            state["auto_audio"] = new_auto
            status_str = "ACTIVADO ✅" if new_auto else "DESACTIVADO ⚪"
            expl = (
                "Cada vez que incluyas (+1), excluyas (-1) u omitas un artículo, "
                "el bot enviará automáticamente la nota de voz del siguiente registro para que ahorres tiempo."
                if new_auto
                else "Ya no se generarán notas de voz automáticas al avanzar. Puedes usar el botón '🎧 Escuchar Audio' cuando gustes."
            )
            msg = f"🎧 <b>Auto-Audio: {status_str}</b>\n\n{expl}"
            self._send_message(token, chat_id, msg)

        elif cmd in ("/audio", "/escuchar", "/voz", "/play"):
            df = self._get_sorted_dataframe()
            if df.empty:
                self._send_message(token, chat_id, "No hay artículos cargados en la base.")
                return

            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                target_idx = int(parts[1]) - 1
            else:
                target_idx = state.get("index", 0)

            if not (0 <= target_idx < len(df)):
                self._send_message(token, chat_id, f"Número de registro fuera de rango (1 a {len(df)}).")
                return

            row = df.iloc[target_idx]
            self._send_message(token, chat_id, f"🎧 <i>Generando audio neural para el registro #{target_idx + 1}...</i>")
            speech_text, voice_to_use, short_title = _build_speech_text(
                row, lang_mode=state.get("lang", "es")
            )
            audio_bytes = synthesize_speech_bytes(speech_text, voice=voice_to_use)
            if audio_bytes:
                caption = (
                    f"🎧 <b>Audio del Registro #{target_idx + 1}</b>\n"
                    f"<i>{escape_html(short_title)}</i>\n\n"
                    f"🔊 Voz: <code>{voice_to_use}</code>"
                )
                self._send_voice(token, chat_id, audio_bytes, caption=caption)
            else:
                self._send_message(token, chat_id, "❌ Error al generar el audio. Verifica tu conexión a internet.")

        elif cmd in ("/siguiente", "/next", "/n"):
            df = self._get_sorted_dataframe()
            if df.empty:
                self._send_message(token, chat_id, "No hay artículos cargados en la base.")
                return
            old_idx = state.get("index", 0)
            new_idx = min(old_idx + 1, len(df) - 1)
            state["index"] = new_idx
            row = df.iloc[new_idx]
            card_text, kb = self._build_article_card(
                row, new_idx, len(df), state.get("lang", "es"), auto_audio=auto_audio
            )
            self._send_message(token, chat_id, card_text, kb)
            if auto_audio and new_idx != old_idx:
                self._send_article_voice_helper(token, chat_id, row, new_idx, lang_mode=state.get("lang", "es"))

        elif cmd in ("/anterior", "/prev", "/p"):
            df = self._get_sorted_dataframe()
            if df.empty:
                self._send_message(token, chat_id, "No hay artículos cargados en la base.")
                return
            new_idx = max(state.get("index", 0) - 1, 0)
            state["index"] = new_idx
            row = df.iloc[new_idx]
            card_text, kb = self._build_article_card(
                row, new_idx, len(df), state.get("lang", "es"), auto_audio=auto_audio
            )
            self._send_message(token, chat_id, card_text, kb)

        elif cmd in ("/pendiente", "/pending"):
            df = self._get_sorted_dataframe()
            if df.empty:
                self._send_message(token, chat_id, "No hay artículos cargados.")
                return
            cur = state.get("index", 0)
            target = None
            for i in range(cur + 1, len(df)):
                if df.iloc[i].get("Seleccion_Manual", 0) == 0:
                    target = i
                    break
            if target is None:
                for i in range(0, cur):
                    if df.iloc[i].get("Seleccion_Manual", 0) == 0:
                        target = i
                        break
            if target is not None:
                state["index"] = target
                row = df.iloc[target]
                card_text, kb = self._build_article_card(
                    row, target, len(df), state.get("lang", "es"), auto_audio=auto_audio
                )
                self._send_message(token, chat_id, card_text, kb)
                if auto_audio:
                    self._send_article_voice_helper(token, chat_id, row, target, lang_mode=state.get("lang", "es"))
            else:
                self._send_message(token, chat_id, "🎉 ¡No hay más registros pendientes de evaluación!")

        elif cmd in ("/estado", "/stats", "/metricas"):
            df = self._get_sorted_dataframe()
            stats_text = self._get_stats_text(df)
            kb = {
                "inline_keyboard": [
                    [{"text": "📄 Ver Artículo Actual", "callback_data": f"show_{state.get('index', 0)}"}],
                    [{"text": "🔍 Siguiente Pendiente", "callback_data": f"pend_{state.get('index', 0)}"}],
                ]
            }
            self._send_message(token, chat_id, stats_text, kb)

        elif cmd.startswith("/ir"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                target_num = int(parts[1]) - 1
                df = self._get_sorted_dataframe()
                if 0 <= target_num < len(df):
                    state["index"] = target_num
                    row = df.iloc[target_num]
                    card_text, kb = self._build_article_card(
                        row, target_num, len(df), state.get("lang", "es"), auto_audio=auto_audio
                    )
                    self._send_message(token, chat_id, card_text, kb)
                    if auto_audio:
                        self._send_article_voice_helper(token, chat_id, row, target_num, lang_mode=state.get("lang", "es"))
                else:
                    self._send_message(token, chat_id, f"Número fuera de rango (1 a {len(df)}).")
            else:
                self._send_message(token, chat_id, "Uso: <code>/ir 15</code> para saltar al registro 15.")

        elif cmd.startswith("/nota"):
            note_content = text[5:].strip()
            df = self._get_sorted_dataframe()
            cur_idx = state.get("index", 0)
            if not df.empty and 0 <= cur_idx < len(df):
                row = df.iloc[cur_idx]
                real_idx = row.name
                if note_content:
                    self._save_article_comment(real_idx, note_content)
                    ack = f"💾 <b>Nota guardada para #{cur_idx + 1}:</b> <i>{escape_html(note_content)}</i>"
                    self._send_message(token, chat_id, ack)
                else:
                    state["awaiting_note"] = True
                    self._send_message(token, chat_id, f"✏️ Escribe el comentario para el artículo #{cur_idx + 1}:")

        elif cmd in ("/ayuda", "/help"):
            help_text = (
                "📖 <b>Guía de Comandos de CribadoLabs Bot</b>\n\n"
                "• <code>/start</code> — Menú principal e instrucciones\n"
                "• <code>/siguiente</code> — Avanzar al siguiente registro\n"
                "• <code>/anterior</code> — Retroceder al registro previo\n"
                "• <code>/pendiente</code> — Saltar al próximo pendiente\n"
                "• <code>/audio</code> — Escuchar nota de voz del artículo actual\n"
                "• <code>/audio [número]</code> — Escuchar audio de un artículo específico\n"
                "• <code>/estado</code> — Ver avance y estadísticas\n"
                "• <code>/ir [número]</code> — Saltar a un registro específico (ej. <code>/ir 42</code>)\n"
                "• <code>/nota [texto]</code> — Agregar nota al registro actual\n\n"
                "<i>También puedes usar directamente los botones táctiles debajo de cada mensaje.</i>"
            )
            self._send_message(token, chat_id, help_text)

        else:
            self._send_message(
                token,
                chat_id,
                "Comando no reconocido. Escribe <code>/ayuda</code> o <code>/siguiente</code>.",
            )

    def _handle_callback_query(self, token: str, query: Dict[str, Any]):
        query_id = query.get("id")
        data = query.get("data", "")
        msg = query.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id"))
        msg_id = msg.get("message_id")

        if not self._is_chat_allowed(chat_id):
            self._answer_callback(token, query_id, "Acceso no autorizado", alert=True)
            return

        config = load_telegram_config()
        if chat_id not in self.chat_states:
            self.chat_states[chat_id] = {
                "index": 0,
                "awaiting_note": False,
                "lang": config.get("default_lang", "es"),
                "auto_audio": config.get("auto_send_audio", False),
            }
        state = self.chat_states[chat_id]
        if "auto_audio" not in state:
            state["auto_audio"] = config.get("auto_send_audio", False)
        auto_audio = state.get("auto_audio", False)

        df = self._get_sorted_dataframe()
        total = len(df)
        if total == 0:
            self._answer_callback(token, query_id, "No hay artículos cargados.")
            return

        if data == "start_eval":
            self._answer_callback(token, query_id, "Iniciando evaluación")
            cur = state.get("index", 0)
            row = df.iloc[cur]
            card_text, kb = self._build_article_card(
                row, cur, total, state.get("lang", "es"), auto_audio=auto_audio
            )
            self._send_message(token, chat_id, card_text, kb)
            if auto_audio:
                self._send_article_voice_helper(token, chat_id, row, cur, lang_mode=state.get("lang", "es"))
            return

        # Formato de data: <accion>_<idx> o <accion>_<val>_<idx>
        parts = data.split("_")
        action = parts[0]

        if action == "toggleaudio":
            idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else state.get("index", 0)
            new_auto = not state.get("auto_audio", False)
            state["auto_audio"] = new_auto
            toast = "🎧 Auto-Audio: ACTIVADO ✅" if new_auto else "🎧 Auto-Audio: DESACTIVADO ⚪"
            self._answer_callback(token, query_id, toast)
            if 0 <= idx < total:
                row = df.iloc[idx]
                card_text, kb = self._build_article_card(
                    row, idx, total, state.get("lang", "es"), auto_audio=new_auto
                )
                self._edit_message_text(token, chat_id, msg_id, card_text, kb)

        elif action == "dec":
            # Decisión: dec_1_0 o dec_-1_0
            decision_val = int(parts[1])
            idx = int(parts[2])
            if 0 <= idx < total:
                row = df.iloc[idx]
                real_idx = row.name
                self._save_article_decision(real_idx, decision_val)

                # Feedback toast en Telegram
                toast_msg = "🟢 Incluido (+1)" if decision_val == 1 else "🔴 Excluido (-1)"
                self._answer_callback(token, query_id, toast_msg)

                # Auto-avanzar al siguiente artículo
                auto_adv = config.get("auto_advance", True)
                if auto_adv:
                    next_idx = min(idx + 1, total - 1)
                    state["index"] = next_idx
                    df_upd = self._get_sorted_dataframe()
                    row_next = df_upd.iloc[next_idx]
                    card_text, kb = self._build_article_card(
                        row_next, next_idx, total, state.get("lang", "es"), auto_audio=auto_audio
                    )
                    self._send_message(token, chat_id, card_text, kb)
                    if auto_audio and next_idx != idx:
                        self._send_article_voice_helper(
                            token, chat_id, row_next, next_idx, lang_mode=state.get("lang", "es")
                        )
                else:
                    # Actualizar el mismo mensaje
                    df_upd = self._get_sorted_dataframe()
                    row_curr = df_upd.iloc[idx]
                    card_text, kb = self._build_article_card(
                        row_curr, idx, total, state.get("lang", "es"), auto_audio=auto_audio
                    )
                    self._edit_message_text(token, chat_id, msg_id, card_text, kb)

        elif action == "nav":
            direction = parts[1]
            idx = int(parts[2])
            new_idx = idx
            if direction == "next":
                new_idx = min(idx + 1, total - 1)
                self._answer_callback(token, query_id, f"Registro #{new_idx + 1}")
            elif direction == "prev":
                new_idx = max(idx - 1, 0)
                self._answer_callback(token, query_id, f"Registro #{new_idx + 1}")

            state["index"] = new_idx
            row = df.iloc[new_idx]
            card_text, kb = self._build_article_card(
                row, new_idx, total, state.get("lang", "es"), auto_audio=auto_audio
            )
            self._edit_message_text(token, chat_id, msg_id, card_text, kb)
            if auto_audio and direction == "next" and new_idx != idx:
                self._send_article_voice_helper(
                    token, chat_id, row, new_idx, lang_mode=state.get("lang", "es")
                )

        elif action == "audio":
            idx = int(parts[1])
            if 0 <= idx < total:
                row = df.iloc[idx]
                self._answer_callback(token, query_id, "🎧 Generando audio...")
                self._send_message(
                    token,
                    chat_id,
                    f"🎧 <i>Generando nota de voz neural para el registro #{idx + 1}...</i>",
                )
                speech_text, voice_to_use, short_title = _build_speech_text(
                    row, lang_mode=state.get("lang", "es")
                )
                audio_bytes = synthesize_speech_bytes(speech_text, voice=voice_to_use)
                if audio_bytes:
                    caption = (
                        f"🎧 <b>Audio del Registro #{idx + 1}</b>\n"
                        f"<i>{escape_html(short_title)}</i>\n\n"
                        f"🔊 Voz: <code>{voice_to_use}</code>"
                    )
                    self._send_voice(token, chat_id, audio_bytes, caption=caption)
                else:
                    self._send_message(
                        token,
                        chat_id,
                        f"❌ No se pudo generar el audio para el registro #{idx + 1}.",
                    )

        elif action == "note":
            idx = int(parts[1])
            state["awaiting_note"] = True
            state["index"] = idx
            self._answer_callback(token, query_id, "Escribe tu comentario en el chat")
            self._send_message(
                token,
                chat_id,
                f"📝 <b>Añadir nota al registro #{idx + 1}:</b>\nEnvía tu comentario directamente como mensaje de texto.",
            )

        elif action == "lang":
            idx = int(parts[1])
            cur_lang = state.get("lang", "es")
            next_lang = "en" if cur_lang == "es" else ("ambos" if cur_lang == "en" else "es")
            state["lang"] = next_lang
            self._answer_callback(token, query_id, f"Idioma: {next_lang.upper()}")
            row = df.iloc[idx]
            card_text, kb = self._build_article_card(
                row, idx, total, next_lang, auto_audio=auto_audio
            )
            self._edit_message_text(token, chat_id, msg_id, card_text, kb)

        elif action == "pend":
            cur_idx = int(parts[1])
            target = None
            for i in range(cur_idx + 1, total):
                if df.iloc[i].get("Seleccion_Manual", 0) == 0:
                    target = i
                    break
            if target is None:
                for i in range(0, cur_idx):
                    if df.iloc[i].get("Seleccion_Manual", 0) == 0:
                        target = i
                        break

            if target is not None:
                self._answer_callback(token, query_id, f"Saltando a #{target + 1}")
                state["index"] = target
                row = df.iloc[target]
                card_text, kb = self._build_article_card(
                    row, target, total, state.get("lang", "es"), auto_audio=auto_audio
                )
                self._send_message(token, chat_id, card_text, kb)
                if auto_audio:
                    self._send_article_voice_helper(
                        token, chat_id, row, target, lang_mode=state.get("lang", "es")
                    )
            else:
                self._answer_callback(token, query_id, "¡No hay más pendientes!", alert=True)

        elif action == "stats":
            self._answer_callback(token, query_id, "Métricas")
            stats_text = self._get_stats_text(df)
            kb = {
                "inline_keyboard": [
                    [{"text": "📄 Volver al Artículo", "callback_data": f"show_{state.get('index', 0)}"}],
                    [{"text": "🔍 Siguiente Pendiente", "callback_data": f"pend_{state.get('index', 0)}"}],
                ]
            }
            self._send_message(token, chat_id, stats_text, kb)

        elif action == "show":
            idx = int(parts[1])
            if 0 <= idx < total:
                self._answer_callback(token, query_id)
                row = df.iloc[idx]
                card_text, kb = self._build_article_card(
                    row, idx, total, state.get("lang", "es"), auto_audio=auto_audio
                )
                self._send_message(token, chat_id, card_text, kb)


# Instancia global del bot
telegram_bot = TelegramBotManager.get_instance()
