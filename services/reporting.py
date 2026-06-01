"""Reportes PRISMA, figuras y exportación por etapa."""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

from services.persistence import atomic_save_excel


OUTPUT_DIR = Path("output")


def generar_reporte_prisma_por_criterio(
    df_f0: pd.DataFrame,
    df_f1: pd.DataFrame | None = None,
    df_f2: pd.DataFrame | None = None,
    df_f3: pd.DataFrame | None = None,
) -> dict:
    """Genera dict consolidado con métricas PRISMA detalladas por criterio."""
    total = len(df_f0)
    f0_pasan = int(df_f0.get("F0_Pasa", pd.Series(False, index=df_f0.index)).sum())
    f0_dud = int(df_f0.get("F0_Dudoso", pd.Series(False, index=df_f0.index)).sum())
    f0_exc = total - f0_pasan - f0_dud

    reporte = {
        "total_registros": total,
        "f0_pasan": f0_pasan,
        "f0_dudosos": f0_dud,
        "f0_excluidos": f0_exc,
        "f1_incluir": 0,
        "f1_excluir": 0,
        "f1_dudoso": 0,
        "f2_include": 0,
        "f2_exclude": 0,
        "f2_borderline": 0,
        "f3_extraidos": 0,
        "por_criterio_f1": {},
    }

    if df_f1 is not None and not df_f1.empty:
        mask_f0 = df_f1.get("F0_Pasa", False) | df_f1.get("F0_Dudoso", False)
        reporte["f1_incluir"] = int((mask_f0 & (df_f1.get("F1_Decision", "") == "INCLUIR")).sum())
        reporte["f1_excluir"] = int((mask_f0 & (df_f1.get("F1_Decision", "") == "EXCLUIR")).sum())
        reporte["f1_dudoso"] = int((mask_f0 & (df_f1.get("F1_Decision", "") == "DUDOSO")).sum())

        por_criterio = {}
        from services.screening import CRITERIOS_INCLUSION, CRITERIOS_EXCLUSION
        all_cids = list(CRITERIOS_INCLUSION.keys()) + list(CRITERIOS_EXCLUSION.keys())
        for cid in all_cids:
            cumple = int(df_f1.get(f"F1_{cid}_cumple", pd.Series(False, index=df_f1.index)).sum())
            no_cumple = mask_f0.sum() - cumple
            por_criterio[cid] = {"cumple": int(cumple), "no_cumple": int(no_cumple)}
        reporte["por_criterio_f1"] = por_criterio

    if df_f2 is not None and not df_f2.empty:
        reporte["f2_include"] = int((df_f2.get("F2_Decision", "") == "INCLUDE").sum())
        reporte["f2_exclude"] = int((df_f2.get("F2_Decision", "") == "EXCLUDE").sum())
        reporte["f2_borderline"] = int((df_f2.get("F2_Decision", "") == "BORDERLINE").sum())

    if df_f3 is not None and not df_f3.empty:
        mask_incluido = (
            (df_f3.get("F1_Decision", "") == "INCLUIR") |
            (df_f3.get("F2_Decision", "") == "INCLUDE")
        )
        reporte["f3_extraidos"] = int(mask_incluido.sum())

    return reporte


def exportar_excel_por_etapa(df: pd.DataFrame, etapa_nombre: str, output_dir: Path | str = OUTPUT_DIR) -> Path:
    """Exporta un DataFrame a Excel con nombre basado en la etapa."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{etapa_nombre}_detalle.xlsx"
    path = output_dir / filename
    atomic_save_excel(df, path)
    return path


def exportar_resumen_excel(reporte: dict, etapa_nombre: str, output_dir: Path | str = OUTPUT_DIR) -> Path:
    """Exporta un dict de reporte como tabla resumen en Excel."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    flat: dict[str, Any] = {}
    for k, v in reporte.items():
        if isinstance(v, dict):
            for subk, subv in v.items():
                if isinstance(subv, dict):
                    for ssk, ssv in subv.items():
                        flat[f"{k}_{subk}_{ssk}"] = ssv
                else:
                    flat[f"{k}_{subk}"] = subv
        else:
            flat[k] = v

    df = pd.DataFrame([flat])
    path = output_dir / f"{etapa_nombre}_resumen.xlsx"
    atomic_save_excel(df, path)
    return path


def generar_figura_prisma(reporte: dict, output_path: Path | str) -> Path:
    """Dibuja un diagrama de flujo PRISMA estilo cajas y flechas."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 14))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 16)
    ax.axis("off")

    def box(x, y, w, h, text, color="#e8f4f8", fontsize=9):
        rect = mpatches.FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=0.02",
            facecolor=color, edgecolor="#333", linewidth=1.2
        )
        ax.add_patch(rect)
        ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, wrap=True)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))

    total = reporte.get("total_registros", 0)
    f0_pasan = reporte.get("f0_pasan", 0)
    f0_dud = reporte.get("f0_dudosos", 0)
    f0_exc = reporte.get("f0_excluidos", 0)
    f1_inc = reporte.get("f1_incluir", 0)
    f1_exc = reporte.get("f1_excluir", 0)
    f1_dud = reporte.get("f1_dudoso", 0)
    f2_inc = reporte.get("f2_include", 0)
    f2_exc = reporte.get("f2_exclude", 0)
    f2_dud = reporte.get("f2_borderline", 0)
    f3_ext = reporte.get("f3_extraidos", 0)

    box(6, 15, 5, 0.8, f"Registros identificados\n(n = {total})", color="#d0e8f2")
    arrow(6, 14.6, 6, 14.0)

    box(6, 13.6, 5, 0.8, f"Fase 0: Pre-filtrado keywords\nPasan={f0_pasan} | Dudoso={f0_dud}", color="#d0e8f2")
    if f0_exc > 0:
        box(9.8, 13.6, 3.5, 0.8, f"Excluidos F0\n(n = {f0_exc})", color="#f8d7da")
        arrow(8.5, 13.6, 9.05, 13.6)

    arrow(6, 13.2, 6, 12.6)

    box(6, 12.2, 5, 0.8, f"Fase 1: Cribado por criterio\nIncluir={f1_inc} | Excluir={f1_exc} | Dudoso={f1_dud}", color="#d0e8f2")
    if f1_exc > 0:
        box(9.8, 12.2, 3.5, 0.8, f"Excluidos F1\n(n = {f1_exc})", color="#f8d7da")
        arrow(8.5, 12.2, 9.05, 12.2)

    arrow(6, 11.8, 6, 11.2)

    box(6, 10.8, 5, 0.8, f"Fase 2: Revisión dudosos\nInclude={f2_inc} | Exclude={f2_exc}", color="#d0e8f2")
    if f2_exc > 0 or f2_dud > 0:
        box(9.8, 10.8, 3.5, 0.8, f"Exclude={f2_exc}\nBorderline={f2_dud}", color="#f8d7da")
        arrow(8.5, 10.8, 9.05, 10.8)

    arrow(6, 10.4, 6, 9.8)

    box(6, 9.4, 5, 0.8, f"Fase 3: Extracción PIs\nExtraídos={f3_ext}", color="#d4edda")

    ax.set_title("Diagrama de flujo PRISMA-ScR - Cribado por Criterio", fontsize=14, fontweight="bold", pad=20)
    plt.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def generar_reporte_md(reporte: dict, output_path: Path | str) -> Path:
    """Genera un reporte markdown con tablas resumen por fase."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Reporte de Cribado por Criterio Individual")
    lines.append("")
    lines.append("## Resumen PRISMA-ScR")
    lines.append("")
    lines.append(f"- **Total registros**: {reporte.get('total_registros', 0)}")
    lines.append(f"- **F0 - Pasan keywords**: {reporte.get('f0_pasan', 0)}")
    lines.append(f"- **F0 - Dudoso keywords**: {reporte.get('f0_dudosos', 0)}")
    lines.append(f"- **F0 - Excluidos keywords**: {reporte.get('f0_excluidos', 0)}")
    lines.append(f"- **F1 - Incluir**: {reporte.get('f1_incluir', 0)}")
    lines.append(f"- **F1 - Excluir**: {reporte.get('f1_excluir', 0)}")
    lines.append(f"- **F1 - Dudoso**: {reporte.get('f1_dudoso', 0)}")
    lines.append(f"- **F2 - Include**: {reporte.get('f2_include', 0)}")
    lines.append(f"- **F2 - Exclude**: {reporte.get('f2_exclude', 0)}")
    lines.append(f"- **F2 - Borderline**: {reporte.get('f2_borderline', 0)}")
    lines.append(f"- **F3 - Extraídos**: {reporte.get('f3_extraidos', 0)}")
    lines.append("")

    por_criterio = reporte.get("por_criterio_f1", {})
    if por_criterio:
        lines.append("## Fase 1 - Resultados por criterio")
        lines.append("")
        lines.append("| Criterio | Cumple | No cumple |")
        lines.append("|----------|--------|-----------|")
        for cid, vals in por_criterio.items():
            lines.append(f"| {cid} | {vals.get('cumple', 0)} | {vals.get('no_cumple', 0)} |")
        lines.append("")

    lines.append("---")
    lines.append("*Generado automáticamente por CribadoLabs*")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
