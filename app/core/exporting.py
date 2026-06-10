"""Render Plotly charts together with CSV / Excel data-export buttons.

Every chart in the app is drawn through :func:`chart_with_export` so the user can
download the underlying data as CSV or Excel. The data is reconstructed from the
figure's traces, so it works for any chart type without bespoke wiring.
"""

from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st


def _slug(text: str) -> str:
    """Filesystem-safe slug for download file names."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(text)).strip("_").lower()
    return s or "grafica"


def figure_to_dataframe(fig) -> pd.DataFrame:
    """Flatten a Plotly figure's traces into a long-form tidy DataFrame.

    Handles scatter/line/bar/waterfall/box (x, y), pie (labels, values),
    heatmap (z grid) and table traces. Unknown traces are skipped gracefully.
    """
    frames: list[pd.DataFrame] = []

    for i, tr in enumerate(fig.data):
        name = getattr(tr, "name", None) or getattr(tr, "type", None) or f"serie_{i}"

        # Table trace → reconstruct from header + cells
        header = getattr(tr, "header", None)
        cells = getattr(tr, "cells", None)
        if header is not None and cells is not None and getattr(cells, "values", None) is not None:
            cols = list(header.values) if header.values is not None else None
            data = {str(c): list(v) for c, v in zip(cols or range(len(cells.values)), cells.values)}
            frames.append(pd.DataFrame(data))
            continue

        # Pie / donut
        values = getattr(tr, "values", None)
        if values is not None:
            labels = getattr(tr, "labels", None)
            frames.append(pd.DataFrame({
                "serie": name,
                "categoria": list(labels) if labels is not None else list(range(len(values))),
                "valor": list(values),
            }))
            continue

        # Heatmap / 2D z grid
        z = getattr(tr, "z", None)
        if z is not None:
            x = getattr(tr, "x", None)
            zdf = pd.DataFrame(
                [list(row) for row in z],
                columns=[str(c) for c in x] if x is not None else None,
            )
            y = getattr(tr, "y", None)
            if y is not None and len(y) == len(zdf):
                zdf.insert(0, "y", list(y))
            frames.append(zdf)
            continue

        # x / y based traces (scatter, bar, waterfall, box, histogram…)
        x = getattr(tr, "x", None)
        y = getattr(tr, "y", None)
        if x is None and y is None:
            continue
        n = max(len(x) if x is not None else 0, len(y) if y is not None else 0)
        frames.append(pd.DataFrame({
            "serie": name,
            "x": list(x) if x is not None else [None] * n,
            "y": list(y) if y is not None else [None] * n,
        }))

    if not frames:
        return pd.DataFrame()
    try:
        return pd.concat(frames, ignore_index=True)
    except Exception:
        return frames[0]


def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Excel can't store timezone-aware datetimes — make a safe copy."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            out[col] = s.dt.tz_localize(None)
        elif s.dtype == object:
            out[col] = s.map(
                lambda v: v.tz_localize(None)
                if isinstance(v, pd.Timestamp) and v.tzinfo is not None
                else v
            )
    return out


def _to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    out = _excel_safe(df) if not df.empty else pd.DataFrame({"info": ["sin datos exportables"]})
    try:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="datos")
    except Exception:
        # Last-resort fallback: stringify everything so export never breaks the page.
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            out.astype(str).to_excel(writer, index=False, sheet_name="datos")
    return buf.getvalue()


def chart_with_export(
    fig,
    *,
    key: str,
    filename: str | None = None,
    use_container_width: bool = True,
    df: pd.DataFrame | None = None,
):
    """Render ``fig`` and offer CSV / Excel downloads of its data.

    Parameters
    ----------
    fig : plotly figure
    key : unique key for this chart (must be unique across the page/run)
    filename : base name for the downloaded files (defaults to ``key``)
    df : optional explicit DataFrame to export instead of inferring from ``fig``
    """
    st.plotly_chart(fig, use_container_width=use_container_width, key=f"plot_{key}")

    data = df if df is not None else figure_to_dataframe(fig)
    fname = _slug(filename or key)

    with st.expander("⬇️ Guardar / exportar datos (CSV / Excel)", expanded=False):
        if data is None or data.empty:
            st.caption("Esta gráfica no tiene datos tabulares exportables.")
            return
        c1, c2 = st.columns(2)
        c1.download_button(
            "📄 Descargar CSV",
            data=data.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{fname}.csv",
            mime="text/csv",
            key=f"csv_{key}",
            use_container_width=True,
        )
        c2.download_button(
            "📊 Descargar Excel",
            data=_to_excel_bytes(data),
            file_name=f"{fname}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"xlsx_{key}",
            use_container_width=True,
        )
