# CribadoLabs - Instrucciones para Claude

## Stack
- Python 3.10+, Streamlit, pandas
- Estructura: app.py como entry point, bibliographic_processor.py para lógica

## Patrones de código
- Usa pathlib para rutas
- Session_state para estado UI, JSON para persistencia
- Funciones pequeñas con docstrings

## Reglas para edits
- Siempre muestra el plan antes de editar
- Modifica solo lo necesario, no reescribas funciones enteras
- Mantén compatibilidad con código existente