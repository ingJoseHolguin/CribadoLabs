"""Pipeline de audio: limpieza LLM, TTS con edge-tts, y generador de karaoke HTML."""

import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from services.llm_client import ollama_chat


SPANISH_VOICES = [
    {"id": "es-MX-JorgeNeural", "name": "Jorge (México, Masculino)"},
    {"id": "es-MX-DaliaNeural", "name": "Dalia (México, Femenino)"},
    {"id": "es-ES-AlvaroNeural", "name": "Álvaro (España, Masculino)"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (España, Femenino)"},
    {"id": "es-AR-ElenaNeural", "name": "Elena (Argentina, Femenino)"},
    {"id": "es-CL-LorenzoNeural", "name": "Lorenzo (Chile, Masculino)"},
    {"id": "es-CO-SalomeNeural", "name": "Salomé (Colombia, Femenino)"},
    {"id": "es-PE-CamilaNeural", "name": "Camila (Perú, Femenino)"},
]


def list_spanish_voices() -> list[dict]:
    return SPANISH_VOICES.copy()


def clean_and_summarize_for_audio(text: str, llm_config: dict, max_input_chars: int = 10000) -> str:
    """Limpia y resume texto para audiolibro usando Ollama local."""
    endpoint = llm_config.get("endpoint", "http://localhost:11434")
    model = llm_config.get("model", "llama3.1")

    truncated = text[:max_input_chars]
    if len(text) > max_input_chars:
        truncated += "\n\n[Texto truncado por límite de longitud para el modelo.]"

    prompt = f"""Eres un editor experto en preparación de textos para audiolibros y podcasts científicos.

Recibirás el texto extraído de un artículo académico en PDF. Tu trabajo es transformarlo en un texto fluido, narrativo y apto para ser leído en voz alta.

REGLAS ESTRICTAS:
1. Elimina completamente: números de página, encabezados, pies de página, lista de referencias bibliográficas, notas al pie, anuncios, y cualquier texto que no sea contenido principal del artículo.
2. Resume las tablas en 1-2 frases descriptivas en lenguaje natural. NO leas fila por fila.
3. Resume las ecuaciones matemáticas en lenguaje natural breve. NO narres símbolos matemáticos letra por letra.
4. Omite leyendas de figuras sueltas. Si una figura es importante, descríbela en 1 frase.
5. Elimina citas entre corchetes como [1], [2,3], etc. No las leas en voz alta.
6. Elimina URLs y DOIs. No los leas.
7. Genera un texto continuo, fluido y narrativo en español.
8. El resultado debe ser un solo párrafo o varios párrafos conectados, sin listas numeradas innecesarias.
9. Usa lenguaje claro y natural, como si lo estuvieras contando a alguien.
10. Si el texto está en inglés, traduce y resume simultáneamente al español.

TEXTO EXTRAÍDO DEL PDF:
{truncated}

TEXTO LIMPIO Y APTO PARA AUDIO:
"""

    options = {
        "num_ctx": 8192,
        "temperature": 0.3,
        "top_p": 0.9,
        "repeat_penalty": 1.1,
        "num_predict": 4096,
    }

    raw = ollama_chat(endpoint, model, prompt, options=options, force_json=False)
    return raw.strip()


def generate_speech(text: str, voice: str, output_audio_path: Path, output_vtt_path: Path) -> None:
    """Genera audio MP3 y subtítulos VTT usando edge-tts CLI."""
    output_audio_path = Path(output_audio_path)
    output_vtt_path = Path(output_vtt_path)
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        text_file = f.name

    try:
        subprocess.run(
            [
                sys.executable, "-m", "edge_tts",
                "--file", text_file,
                "--voice", voice,
                "--write-media", str(output_audio_path),
                "--write-subtitles", str(output_vtt_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"edge-tts falló: {exc.stderr}") from exc
    finally:
        Path(text_file).unlink()


def _parse_vtt(vtt_path: Path) -> list[dict]:
    """Parsea un archivo VTT generado por edge-tts."""
    content = vtt_path.read_text(encoding="utf-8")
    cues = []
    # Regex para capturar cue de WebVTT: start --> end\ntext
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\n(.*?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(content):
        start, end, text = match.groups()
        cues.append({
            "start": start,
            "end": end,
            "text": text.strip().replace("\n", " "),
        })
    return cues


def _vtt_time_to_seconds(ts: str) -> float:
    """Convierte '00:00:05.250' a segundos."""
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def build_karaoke_html(audio_path: Path, vtt_path: Path) -> str:
    """Genera HTML auto-contenido con reproductor de audio y modo karaoke sincronizado."""
    audio_path = Path(audio_path)
    vtt_path = Path(vtt_path)

    # Embeber audio en base64
    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode()
    cues = _parse_vtt(vtt_path)
    cues_js = json.dumps(cues)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{
    margin: 0;
    padding: 20px;
    background: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 100vh;
  }}
  audio {{
    width: 100%;
    max-width: 600px;
    margin-bottom: 24px;
  }}
  #karaoke-container {{
    width: 100%;
    max-width: 800px;
    text-align: center;
    line-height: 1.8;
    font-size: 1.4rem;
  }}
  .cue {{
    display: inline;
    padding: 2px 6px;
    border-radius: 4px;
    transition: color 0.3s, background 0.3s;
    color: #888;
  }}
  .cue.active {{
    color: #ffd700;
    background: rgba(255, 215, 0, 0.15);
    font-weight: 600;
  }}
  .cue.past {{
    color: #ccc;
  }}
</style>
</head>
<body>
<audio id="player" controls>
  <source src="data:audio/mp3;base64,{audio_b64}" type="audio/mpeg">
</audio>
<div id="karaoke-container"></div>

<script>
  const cues = {cues_js};
  const container = document.getElementById('karaoke-container');
  const player = document.getElementById('player');

  // Renderizar spans
  cues.forEach((cue, i) => {{
    const span = document.createElement('span');
    span.className = 'cue';
    span.id = 'cue-' + i;
    span.textContent = cue.text + ' ';
    container.appendChild(span);
  }});

  function timeToSeconds(ts) {{
    const [h, m, s] = ts.split(':');
    return parseInt(h)*3600 + parseInt(m)*60 + parseFloat(s);
  }}

  player.ontimeupdate = function() {{
    const t = player.currentTime;
    let activeIdx = -1;
    for (let i = 0; i < cues.length; i++) {{
      const s = timeToSeconds(cues[i].start);
      const e = timeToSeconds(cues[i].end);
      if (t >= s && t <= e) {{
        activeIdx = i;
        break;
      }} else if (t > e) {{
        activeIdx = -2; // signal past
      }}
    }}

    for (let i = 0; i < cues.length; i++) {{
      const el = document.getElementById('cue-' + i);
      const s = timeToSeconds(cues[i].start);
      const e = timeToSeconds(cues[i].end);
      el.classList.remove('active', 'past');
      if (t >= s && t <= e) {{
        el.classList.add('active');
        el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
      }} else if (t > e) {{
        el.classList.add('past');
      }}
    }}
  }};
</script>
</body>
</html>"""
    return html
