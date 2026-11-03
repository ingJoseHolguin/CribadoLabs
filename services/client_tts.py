"""Generador de reproductor de síntesis de voz en el navegador (Web Speech API) con voz femenina y resaltado sincronizado."""

import html
import json
import re


def _build_article_spans(title: str, abstract: str, lang_prefix: str) -> tuple[str, str, str]:
    """Genera el texto plano para la síntesis de voz y los HTML spans con offsets continuos y unificados."""
    clean_title = (title or "").strip()
    clean_abstract = (abstract or "").strip()

    if clean_title and clean_abstract:
        sep = " " if clean_title.endswith((".", "?", "!", ":", ";")) else ". "
        full_text = f"{clean_title}{sep}{clean_abstract}"
        title_end_pos = len(clean_title)
        abstract_start_pos = len(clean_title) + len(sep)
    elif clean_title:
        full_text = clean_title
        title_end_pos = len(clean_title)
        abstract_start_pos = len(clean_title)
    elif clean_abstract:
        full_text = clean_abstract
        title_end_pos = 0
        abstract_start_pos = 0
    else:
        return "", "", ""

    tokens = list(re.finditer(r"\S+", full_text))
    t_spans = []
    a_spans = []

    last_end = 0
    for i, m in enumerate(tokens):
        w_start, w_end = m.start(), m.end()
        w_escaped = html.escape(m.group(0))
        span = f'<span class="r-word" id="{lang_prefix}_{i}" data-start="{w_start}" data-end="{w_end}">{w_escaped}</span>'

        if clean_title and w_end <= title_end_pos + 1:
            space = html.escape(full_text[last_end:w_start])
            t_spans.append(space + span)
            last_end = w_end
        else:
            if last_end < abstract_start_pos:
                last_end = abstract_start_pos
            space = html.escape(full_text[last_end:w_start])
            a_spans.append(space + span)
            last_end = w_end

    return full_text, "".join(t_spans), "".join(a_spans)


def build_client_tts_html(
    title_es: str = "",
    abstract_es: str = "",
    title_en: str = "",
    abstract_en: str = "",
    default_lang: str = "es",
) -> str:
    """Construye un widget HTML/JS/CSS independiente que usa la Web Speech API del navegador

    priorizando voz femenina local, sin consumo de datos móviles y con cursor sincronizado en tiempo real.
    """
    has_es = bool(title_es.strip() or abstract_es.strip())
    has_en = bool(title_en.strip() or abstract_en.strip())

    if not has_es and has_en:
        default_lang = "en"
    elif not has_en and has_es:
        default_lang = "es"

    # Generar textos unificados y spans continuos
    full_text_es, spans_title_es, spans_abstract_es = _build_article_spans(
        title_es, abstract_es, "es"
    )
    full_text_en, spans_title_en, spans_abstract_en = _build_article_spans(
        title_en, abstract_en, "en"
    )

    json_text_es = json.dumps(full_text_es)
    json_text_en = json.dumps(full_text_en)

    html_code = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
      :root {{
        --bg-box: #f8fafc;
        --border-box: #e2e8f0;
        --text-color: #1e293b;
        --primary: #0284c7;
        --primary-hover: #0369a1;
        --active-bg: #fde047;
        --active-text: #000000;
        --card-radius: 10px;
      }}
      @media (prefers-color-scheme: dark) {{
        :root {{
          --bg-box: #0f172a;
          --border-box: #334155;
          --text-color: #f1f5f9;
          --primary: #38bdf8;
          --primary-hover: #0ea5e9;
          --active-bg: #facc15;
          --active-text: #000000;
        }}
      }}
      * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }}
      body {{
        background: transparent;
        color: var(--text-color);
        padding: 6px;
      }}
      .reader-container {{
        background: var(--bg-box);
        border: 1px solid var(--border-box);
        border-radius: var(--card-radius);
        padding: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
      }}
      .controls-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border-box);
      }}
      .btn-group {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
      }}
      .btn {{
        background: var(--primary);
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        transition: all 0.15s ease;
      }}
      .btn:hover {{
        background: var(--primary-hover);
      }}
      .btn-secondary {{
        background: #64748b;
      }}
      .btn-secondary:hover {{
        background: #475569;
      }}
      .select-custom {{
        background: var(--bg-box);
        color: var(--text-color);
        border: 1px solid var(--border-box);
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        max-width: 170px;
      }}
      .badge-status {{
        font-size: 11px;
        color: #64748b;
        font-weight: 500;
        margin-left: auto;
      }}
      .text-display {{
        max-height: 160px;
        overflow-y: auto;
        padding: 8px 10px;
        background: rgba(0, 0, 0, 0.02);
        border-radius: 6px;
        border: 1px solid var(--border-box);
        line-height: 1.6;
        font-size: 14px;
        scroll-behavior: smooth;
      }}
      .text-title {{
        font-weight: 700;
        margin-bottom: 6px;
        display: block;
        color: var(--primary);
      }}
      .r-word {{
        cursor: pointer;
        border-radius: 3px;
        padding: 0 1px;
        transition: background-color 0.1s ease;
      }}
      .r-word:hover {{
        background-color: rgba(253, 224, 71, 0.3);
      }}
      .reading-active {{
        background-color: var(--active-bg) !important;
        color: var(--active-text) !important;
        font-weight: 700;
        border-radius: 3px;
        padding: 1px 3px;
        box-shadow: 0 0 6px rgba(250, 204, 21, 0.85);
      }}
      .helper-note {{
        font-size: 11px;
        color: #94a3b8;
        margin-top: 6px;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        justify-content: space-between;
      }}
    </style>
    </head>
    <body>
    <div class="reader-container">
      <div class="controls-bar">
        <div class="btn-group">
          <button id="btnPlay" class="btn" onclick="togglePlay()">
            <span id="playIcon">▶️</span> <span id="playText">Escuchar</span>
          </button>
          <button id="btnStop" class="btn btn-secondary" onclick="stopSpeech()">
            ⏹️ Detener
          </button>
        </div>

        <div class="btn-group">
          <label style="font-size: 12px; font-weight:600;">Idioma:</label>
          <select id="selLang" class="select-custom" onchange="changeLanguage()">
            {'<option value="es"' + (' selected' if default_lang == 'es' else '') + '>🇪🇸 Español</option>' if has_es else ''}
            {'<option value="en"' + (' selected' if default_lang == 'en' else '') + '>🇬🇧 Inglés</option>' if has_en else ''}
          </select>

          <label style="font-size: 12px; font-weight:600; margin-left: 2px;">Voz:</label>
          <select id="selVoice" class="select-custom" onchange="changeVoice()">
            <option value="">Cargando voces...</option>
          </select>

          <label style="font-size: 12px; font-weight:600; margin-left: 2px;">Vel:</label>
          <select id="selRate" class="select-custom" onchange="updateRate()" style="max-width: 75px;">
            <option value="0.85">0.85x</option>
            <option value="1.0" selected>1.0x</option>
            <option value="1.15">1.15x</option>
            <option value="1.3">1.3x</option>
          </select>
        </div>

        <div id="statusBadge" class="badge-status">Listo</div>
      </div>

      <div id="displayES" class="text-display" style="display: {'block' if default_lang == 'es' else 'none'};">
        <span class="text-title">{spans_title_es if spans_title_es else '*(Sin título)*'}</span>
        <div class="text-body">{spans_abstract_es if spans_abstract_es else '*(Sin resumen traducido disponible)*'}</div>
      </div>

      <div id="displayEN" class="text-display" style="display: {'block' if default_lang == 'en' else 'none'};">
        <span class="text-title">{spans_title_en if spans_title_en else '*(No title)*'}</span>
        <div class="text-body">{spans_abstract_en if spans_abstract_en else '*(No abstract available)*'}</div>
      </div>

      <div class="helper-note">
        <span>👩 Prioriza voz de mujer &bull; Toca cualquier palabra para saltar a ella.</span>
        <span>⚡ 100% sintetizado en tu dispositivo (0 datos móviles).</span>
      </div>
    </div>

    <script>
      const textES = {json_text_es};
      const textEN = {json_text_en};

      let currentLang = '{default_lang}';
      let synth = window.speechSynthesis;
      let utterance = null;
      let isPlaying = false;
      let isPaused = false;
      let currentWordEl = null;

      let wordsES = [];
      let wordsEN = [];

      function isFemaleVoice(voice) {{
        const name = voice.name.toLowerCase();
        const femaleNames = [
          "sabina", "helena", "laura", "monica", "paulina", "sofia", "lucia", "maria",
          "paloma", "carmen", "elvira", "rosa", "zira", "jenny", "samantha", "victoria",
          "karen", "fiona", "moira", "tessa", "ava", "susan", "emma", "penelope", "female",
          "mujer", "femenina", "natural"
        ];
        return femaleNames.some(kw => name.includes(kw));
      }}

      function initWords() {{
        const elsES = document.querySelectorAll('#displayES .r-word');
        wordsES = Array.from(elsES).map(el => ({{
          el: el,
          start: parseInt(el.getAttribute('data-start') || '0'),
          end: parseInt(el.getAttribute('data-end') || '0')
        }}));

        const elsEN = document.querySelectorAll('#displayEN .r-word');
        wordsEN = Array.from(elsEN).map(el => ({{
          el: el,
          start: parseInt(el.getAttribute('data-start') || '0'),
          end: parseInt(el.getAttribute('data-end') || '0')
        }}));

        // Click en palabra para saltar
        document.querySelectorAll('.r-word').forEach(el => {{
          el.addEventListener('click', function() {{
            const wordStart = parseInt(this.getAttribute('data-start') || '0');
            seekToChar(wordStart);
          }});
        }});

        populateVoiceList();
      }}

      function populateVoiceList() {{
        if (!synth) return;
        const allVoices = synth.getVoices();
        const selVoice = document.getElementById('selVoice');
        if (!selVoice) return;
        selVoice.innerHTML = '';

        const prefix = currentLang.toLowerCase().slice(0, 2);
        const langVoices = allVoices.filter(v => v.lang.toLowerCase().replace('_', '-').startsWith(prefix));

        if (langVoices.length === 0) {{
          const opt = document.createElement('option');
          opt.value = '';
          opt.text = 'Voz predeterminada';
          selVoice.appendChild(opt);
          return;
        }}

        // Ordenar colocando voces femeninas primero
        langVoices.sort((a, b) => {{
          const aFem = isFemaleVoice(a) ? 0 : 1;
          const bFem = isFemaleVoice(b) ? 0 : 1;
          return aFem - bFem;
        }});

        let selectedSet = false;
        langVoices.forEach(v => {{
          const opt = document.createElement('option');
          opt.value = v.name;
          const isFem = isFemaleVoice(v);
          opt.text = (isFem ? '👩 ' : '👤 ') + v.name + (isFem ? ' (Femenina)' : '');

          if (!selectedSet && isFem) {{
            opt.selected = true;
            selectedSet = true;
          }}
          selVoice.appendChild(opt);
        }});

        if (!selectedSet && langVoices.length > 0) {{
          selVoice.options[0].selected = true;
        }}
      }}

      function getSelectedVoice() {{
        if (!synth) return null;
        const selVoice = document.getElementById('selVoice');
        if (!selVoice || !selVoice.value) return null;
        const voices = synth.getVoices();
        return voices.find(v => v.name === selVoice.value) || null;
      }}

      function clearHighlight() {{
        if (currentWordEl) {{
          currentWordEl.classList.remove('reading-active');
          currentWordEl = null;
        }}
      }}

      function highlightAtChar(charIndex) {{
        const wordList = currentLang === 'es' ? wordsES : wordsEN;
        if (!wordList.length) return;

        let match = null;
        for (let i = 0; i < wordList.length; i++) {{
          const w = wordList[i];
          const nextStart = (i + 1 < wordList.length) ? wordList[i + 1].start : Infinity;
          if (charIndex >= w.start && charIndex < nextStart) {{
            match = w.el;
            break;
          }}
        }}

        if (!match && charIndex >= wordList[wordList.length - 1].start) {{
          match = wordList[wordList.length - 1].el;
        }}

        if (match && match !== currentWordEl) {{
          clearHighlight();
          match.classList.add('reading-active');
          currentWordEl = match;
          match.scrollIntoView({{ behavior: 'smooth', block: 'nearest', inline: 'nearest' }});
        }}
      }}

      function togglePlay() {{
        if (!synth) {{
          alert("Tu navegador no soporta síntesis de voz (Web Speech API).");
          return;
        }}

        if (isPlaying && !isPaused) {{
          synth.pause();
          isPaused = true;
          document.getElementById('playIcon').innerText = '▶️';
          document.getElementById('playText').innerText = 'Reanudar';
          document.getElementById('statusBadge').innerText = 'Pausado';
          return;
        }}

        if (isPlaying && isPaused) {{
          synth.resume();
          isPaused = false;
          document.getElementById('playIcon').innerText = '⏸️';
          document.getElementById('playText').innerText = 'Pausar';
          document.getElementById('statusBadge').innerText = 'Leyendo...';
          return;
        }}

        startSpeech(0);
      }}

      function startSpeech(startIndex = 0) {{
        synth.cancel();
        clearHighlight();

        const fullText = currentLang === 'es' ? textES : textEN;
        if (!fullText) {{
          alert("No hay texto para leer en este idioma.");
          return;
        }}

        const subText = fullText.slice(startIndex);
        utterance = new SpeechSynthesisUtterance(subText);
        utterance.lang = currentLang === 'es' ? 'es-ES' : 'en-US';

        const chosenVoice = getSelectedVoice();
        if (chosenVoice) {{
          utterance.voice = chosenVoice;
        }}

        const rateVal = parseFloat(document.getElementById('selRate').value) || 1.0;
        utterance.rate = rateVal;

        utterance.onboundary = function(e) {{
          const adjustedChar = startIndex + e.charIndex;
          highlightAtChar(adjustedChar);
        }};

        utterance.onend = function() {{
          isPlaying = false;
          isPaused = false;
          clearHighlight();
          document.getElementById('playIcon').innerText = '▶️';
          document.getElementById('playText').innerText = 'Escuchar';
          document.getElementById('statusBadge').innerText = 'Finalizado';
        }};

        utterance.onerror = function(err) {{
          console.error("Speech error:", err);
          stopSpeech();
        }};

        synth.speak(utterance);
        isPlaying = true;
        isPaused = false;
        document.getElementById('playIcon').innerText = '⏸️';
        document.getElementById('playText').innerText = 'Pausar';
        document.getElementById('statusBadge').innerText = 'Leyendo...';
      }}

      function stopSpeech() {{
        if (synth) synth.cancel();
        isPlaying = false;
        isPaused = false;
        clearHighlight();
        document.getElementById('playIcon').innerText = '▶️';
        document.getElementById('playText').innerText = 'Escuchar';
        document.getElementById('statusBadge').innerText = 'Detenido';
      }}

      function seekToChar(charIndex) {{
        startSpeech(charIndex);
      }}

      function updateRate() {{
        if (isPlaying) {{
          const currentOffset = currentWordEl ? parseInt(currentWordEl.getAttribute('data-start') || '0') : 0;
          startSpeech(currentOffset);
        }}
      }}

      function changeVoice() {{
        if (isPlaying) {{
          const currentOffset = currentWordEl ? parseInt(currentWordEl.getAttribute('data-start') || '0') : 0;
          startSpeech(currentOffset);
        }}
      }}

      function changeLanguage() {{
        stopSpeech();
        currentLang = document.getElementById('selLang').value;
        if (currentLang === 'es') {{
          document.getElementById('displayES').style.display = 'block';
          document.getElementById('displayEN').style.display = 'none';
        }} else {{
          document.getElementById('displayES').style.display = 'none';
          document.getElementById('displayEN').style.display = 'block';
        }}
        populateVoiceList();
      }}

      window.addEventListener('beforeunload', () => {{
        if (synth) synth.cancel();
      }});

      if (synth && synth.onvoiceschanged !== undefined) {{
        synth.onvoiceschanged = populateVoiceList;
      }}

      window.onload = initWords;
    </script>
    </body>
    </html>
    """
    return html_code
