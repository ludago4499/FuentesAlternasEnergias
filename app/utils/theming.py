"""Inyección del tema visual "editorial cortante" (solo estética).

Tres piezas, todas opcionales y desactivables sin afectar la lógica:
  • inject_theme()       — lee assets/styles.css y lo inyecta + watermark.
  • custom_metric()      — métrica en HTML con esquina cortada (clip-path).
  • apply_plotly_theme() — pinta una figura Plotly con la paleta del tema.

Si el CSS no existe o algo falla, las funciones degradan en silencio y la app
sigue funcionando igual que sin tema.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "styles.css"

# Paleta (espejo de styles.css / config.toml)
CREAM = "#F5F0E1"
INK = "#15151A"
ACCENT = "#FFD400"
MUTED = "#88826F"
CARD = "#FAF6EB"


# ── 1) Inyección del CSS + watermark ──────────────────────────────────────────
def inject_theme(page_number: str | int | None = None, *, enabled: bool = True) -> None:
    """Inyecta el tema. ``enabled=False`` lo desactiva por completo.

    ``page_number`` dibuja el número grande (watermark) en la esquina superior
    derecha; pásalo como "03" para conservar el cero a la izquierda.
    """
    if not enabled:
        return
    try:
        css = _CSS_PATH.read_text(encoding="utf-8")
    except Exception:
        return  # sin CSS, la app sigue intacta
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    if page_number is not None:
        st.markdown(
            f'<div class="page-watermark">{html.escape(str(page_number))}</div>',
            unsafe_allow_html=True,
        )


# ── 2) Métrica personalizada (reemplaza st.metric) ────────────────────────────
def custom_metric(container, label, value, delta=None, *,
                  help: str | None = None, delta_color: str = "normal", **_ignored) -> None:
    """Dibuja una métrica con la estética del tema (esquina amarilla cortada).

    Firma pensada como reemplazo directo de ``col.metric(...)``:
    ``col.metric(a, b)`` → ``custom_metric(col, a, b)``. ``container`` puede ser
    cualquier contenedor de Streamlit (una columna, ``st``...). Acepta y
    descarta argumentos extra de st.metric para no romper llamadas existentes.
    """
    tgt = container if container is not None else st

    label_h = html.escape(str(label))
    value_h = html.escape(str(value))

    delta_html = ""
    if delta is not None and str(delta).strip() != "":
        d = str(delta).strip()
        if delta_color == "off":
            cls = "flat"
        else:
            negative = d[:1] in ("-", "−")
            if delta_color == "inverse":
                cls = "down" if not negative else "up"
            else:  # normal
                cls = "down" if negative else "up"
        delta_html = f'<div class="pmetric-delta {cls}">{html.escape(d)}</div>'

    title = f' title="{html.escape(str(help))}"' if help else ""
    tgt.markdown(
        f'<div class="pmetric"{title}>'
        f'<span class="pmetric-label">{label_h}</span>'
        f'<span class="pmetric-value">{value_h}</span>'
        f'{delta_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── 3) Tema para figuras Plotly ───────────────────────────────────────────────
def apply_plotly_theme(fig, *, enabled: bool = True):
    """Aplica fondo/fuente/grid del tema a una figura Plotly y afina las barras.

    Conserva los colores con significado (waterfalls, pies, multi-serie): solo
    añade borde negro fino a las barras y fija una paleta por defecto cuyo primer
    color es el amarillo de acento (para series sin color explícito).
    Devuelve la misma figura.
    """
    if not enabled or fig is None:
        return fig
    try:
        fig.update_layout(
            paper_bgcolor=CREAM,
            plot_bgcolor=CARD,
            font=dict(color=INK, family="Inter, Segoe UI, system-ui, sans-serif"),
            colorway=[ACCENT, INK, MUTED, "#2E7D32", "#C62828", "#90CAF9"],
        )
        grid = "rgba(21,21,26,0.35)"
        fig.update_xaxes(gridcolor=grid, gridwidth=0.3, zerolinecolor=grid,
                         zerolinewidth=0.3, linecolor=INK, linewidth=0.5)
        fig.update_yaxes(gridcolor=grid, gridwidth=0.3, zerolinecolor=grid,
                         zerolinewidth=0.3, linecolor=INK, linewidth=0.5)
        # Barras: borde negro fino (sin tocar el color de relleno → conserva semántica)
        fig.update_traces(
            selector=dict(type="bar"),
            marker_line_color=INK,
            marker_line_width=0.3,
        )
    except Exception:
        pass
    return fig
