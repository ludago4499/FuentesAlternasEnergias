"""Cross-page session-state persistence for the multipage Streamlit app.

Streamlit keeps ``st.session_state`` across page navigation, but it *garbage
collects* the state of widgets that are not rendered on the current page. That
is why, when the user fills a form on one page and switches tabs, the inputs
look "erased" on return: the underlying widget keys were dropped.

``keep_state()`` re-commits every stored key on each run, which pins the values
so they survive navigation. It is defensive: keys that cannot be written back
(button / download / file-uploader / chart widget state) are skipped silently.

Call it once, right after ``st.set_page_config(...)``, on every page.
"""

from __future__ import annotations

import streamlit as st

# Keys belonging to widgets whose value CANNOT be set via session_state
# (st.button, st.download_button, st.plotly_chart selections…). Re-committing
# them does not just fail silently — it makes Streamlit raise
# ``StreamlitValueAssignmentNotAllowedError`` when the widget is next created,
# which crashed the page. All such keys in this app come from core.exporting
# (``plot_``/``csv_``/``xlsx_`` prefixes), so they are skipped here.
_SKIP_PREFIXES = ("plot_", "csv_", "xlsx_")


def keep_state(exclude: tuple[str, ...] = ()) -> None:
    """Re-assign every (settable) session-state entry to itself so widget-keyed
    values are not garbage-collected when navigating between pages.

    Keys tied to non-settable widgets (download buttons, chart selections) are
    skipped, because writing them makes Streamlit raise on the widget's next
    instantiation.

    Parameters
    ----------
    exclude : extra keys to leave untouched.
    """
    for k in list(st.session_state.keys()):
        if k in exclude or k.startswith(_SKIP_PREFIXES):
            continue
        try:
            st.session_state[k] = st.session_state[k]
        except Exception:
            pass
