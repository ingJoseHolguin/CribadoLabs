# Script de Extracción y Normalización de Datos Bibliográficos

Este script procesa archivos bibliográficos en diferentes formatos (BibTeX, CSV, Excel) desde múltiples fuentes, normaliza los datos y genera un archivo maestro consolidado.

## Requisitos del Sistema

- Python 3.8 o superior
- pip (gestor de paquetes de Python)

## Librerías Requeridas

Las dependencias están listadas en `requirements.txt`:
- **pandas**: Manipulación y análisis de datos
- **bibtexparser**: Parseo de archivos BibTeX
- **openpyxl**: Lectura/escritura de archivos Excel (.xlsx)

---

## Instalación y Despliegue

### 🪟 Windows

#### 1. Abrir PowerShell o CMD como Administrador

```powershell
# Verificar que Python está instalado
python --version

# Si no está instalado, descargar desde https://www.python.org/downloads/
```

#### 2. Crear Entorno Virtual (Recomendado)

```powershell
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
venv\Scripts\activate
```

#### 3. Instalar Dependencias

```powershell
# Instalar todas las librerías requeridas
pip install -r requirements.txt
```

#### 4. Ejecutar el Script

```powershell
# Asegurarse de tener la carpeta 'data' con los archivos a procesar
python script.py
```

#### 5. Ver Resultados

El archivo de salida se generará en: `output/scoping_master.xlsx`

---

### 🍎 macOS

#### 1. Abrir Terminal

```bash
# Verificar que Python está instalado
python3 --version

# Si no está instalado, instalar con Homebrew:
# /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# brew install python
```

#### 2. Crear Entorno Virtual (Recomendado)

```bash
# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
source venv/bin/activate
```

#### 3. Instalar Dependencias

```bash
# Instalar todas las librerías requeridas
pip install -r requirements.txt
```

#### 4. Ejecutar el Script

```bash
# Asegurarse de tener la carpeta 'data' con los archivos a procesar
python3 script.py
```

#### 5. Ver Resultados

El archivo de salida se generará en: `output/scoping_master.xlsx`

---

## Estructura de Carpetas

```
/workspace
├── script.py              # Script principal
├── requirements.txt       # Dependencias de Python
├── README.md             # Este archivo
├── data/                 # Carpeta de entrada (archivos a procesar)
│   ├── fuente1/
│   │   ├── archivo.bib
│   │   └── archivo.csv
│   └── fuente2/
│       └── archivo.xlsx
└── output/               # Carpeta de salida (generada automáticamente)
    └── scoping_master.xlsx
```

## Formatos Soportados

| Extensión | Tipo | Fuente Típica |
|-----------|------|---------------|
| `.bib`, `.txt` | BibTeX | Scopus, Web of Science, Mendeley |
| `.csv` | CSV | Springer, IEEE |
| `.xls`, `.xlsx` | Excel | Web of Science, Scopus |

## Campos Normalizados

El script genera un archivo Excel con las siguientes columnas:

- **Fuente**: Nombre de la carpeta de origen
- **Titulo**: Título del artículo/documento
- **Autor**: Autores del documento
- **Año**: Año de publicación
- **Abstract**: Resumen del documento
- **TipoDocumento**: Tipo de documento (Artículo, Conferencia, Libro, etc.)
- **DOI**: Identificador DOI
- **Keywords**: Palabras clave
- **URL**: URL del documento
- **ArchivoOrigen**: Nombre del archivo original

## Notas Importantes

1. **Carpeta `data`**: Debe existir y contener los archivos a procesar organizados por subcarpetas (cada subcarpeta representa una fuente)
2. **Duplicados**: El script elimina automáticamente duplicados basándose en el campo DOI
3. **Ordenamiento**: Los resultados se ordenan por año (descendente)
4. **Entorno Virtual**: Se recomienda usar un entorno virtual para aislar las dependencias

## Solución de Problemas

### Error: `ModuleNotFoundError`
```bash
# Reinstalar dependencias
pip install -r requirements.txt --force-reinstall
```

### Error: `Permission Denied` (macOS/Linux)
```bash
# Dar permisos de ejecución
chmod +x script.py
```

### Error: Python no encontrado
- **Windows**: Asegurarse de que Python esté agregado al PATH
- **macOS**: Usar `python3` en lugar de `python`

## Licencia

Este proyecto es de uso libre para fines académicos y de investigación.
