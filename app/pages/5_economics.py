import sys
from pathlib import Path
import io
import datetime

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.gdmth import GDMTHCalculator, classify_period, get_season
from core.plots import savings_waterfall, energy_pie, monthly_savings_bar

st.set_page_config(page_title="Economía GDMTH — Solar", page_icon="💰", layout="wide")

st.markdown("<h1 style='color:#0039A6;font-weight:700'>Análisis Económico GDMTH</h1>",
            unsafe_allow_html=True)
st.caption("Cargo por Energía (Punta / Intermedia / Base) + Cargo por Capacidad + Cargo por Distribución")

# ── Check prerequisites ───────────────────────────────────────────────────────
region = st.session_state.get("region", "Noreste")
usd_mxn = st.session_state.get("usd_mxn", 17.5)
system_kwp = st.session_state.get("system_kwp", 50.0)
panel_capex_usd = st.session_state.get("panel_capex_usd", 0.0)
panel = st.session_state.get("panel", {})

demand_df = st.session_state.get("demand_df")
solar_kw = st.session_state.get("solar_aligned")
net_demand = st.session_state.get("net_demand")

# ── Sidebar settings ──────────────────────────────────────────────────────────
st.sidebar.markdown("### Parámetros económicos")
bat_capex_usd = st.sidebar.number_input("CAPEX baterías (USD)", min_value=0.0,
                                         value=st.session_state.get("battery_kwh", 0.0) *
                                         (st.session_state.get("battery", {}) or {}).get("usd_per_kwh", 350)
                                         if st.session_state.get("use_battery") else 0.0,
                                         step=1000.0)
install_factor = st.sidebar.slider("Factor instalación sobre CAPEX (%)", 10, 40, 20)
opex_pct = st.sidebar.slider("OPEX anual (% del CAPEX total)", 1, 5, 2)
inflation_pct = st.sidebar.slider("Inflación tarifaria anual (%)", 0.0, 15.0, 5.0, step=0.5)
project_life = st.sidebar.slider("Vida útil del proyecto (años)", 10, 30, 25)

# ── CAPEX summary ─────────────────────────────────────────────────────────────
total_capex_usd = (panel_capex_usd + bat_capex_usd) * (1 + install_factor / 100)
total_capex_mxn = total_capex_usd * usd_mxn

st.markdown("### CAPEX del sistema")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Paneles FV", f"${panel_capex_usd:,.0f} USD")
c2.metric("Baterías", f"${bat_capex_usd:,.0f} USD")
c3.metric("CAPEX total (c/instalación)", f"${total_capex_usd:,.0f} USD")
c4.metric("CAPEX total (MXN)", f"${total_capex_mxn:,.0f} MXN")

# ── Monthly calculation ───────────────────────────────────────────────────────
st.divider()
st.markdown("### Cálculo mensual de la tarifa GDMTH")

if demand_df is None:
    st.warning("Carga la curva de demanda en la página **Demanda e Inyección** primero.")
    st.stop()

calc = GDMTHCalculator(region=region)

# Group demand by month and compute bill
demand_series = demand_df["demand"].copy()
if solar_kw is not None:
    solar_series = solar_kw.copy()
else:
    solar_series = pd.Series(0.0, index=demand_series.index)

monthly_results = []
months_available = demand_series.groupby(demand_series.index.month).groups.keys()

for month_num in sorted(months_available):
    mask = demand_series.index.month == month_num
    d_month = demand_series[mask]
    s_month = solar_series[mask] if mask.any() else pd.Series(0.0, index=d_month.index)
    result = calc.compute_bill(d_month, solar_kw=s_month)
    if result:
        monthly_results.append(result)

if not monthly_results:
    st.error("No se pudieron calcular los cargos. Verifica los datos de demanda.")
    st.stop()

st.session_state["monthly_results"] = monthly_results

# ── Monthly table ─────────────────────────────────────────────────────────────
month_names = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

table_rows = []
for r in monthly_results:
    table_rows.append({
        "Mes": month_names[r["month"] - 1],
        "Temporada": "Alta" if r["season"] == "temporada_alta" else "Baja",
        "kWh Punta": f"{r['orig_punta_kwh']:,.0f}",
        "kWh Inter.": f"{r['orig_inter_kwh']:,.0f}",
        "kWh Base": f"{r['orig_base_kwh']:,.0f}",
        "Cargo Energía (MXN)": f"${r['orig_charge_punta']+r['orig_charge_inter']+r['orig_charge_base']:,.0f}",
        "Cargo Capacidad (MXN)": f"${r['orig_charge_capacidad']:,.0f}",
        "Cargo Dist. (MXN)": f"${r['orig_charge_distribucion']:,.0f}",
        "Total sin FV (MXN)": f"${r['orig_total_mxn']:,.0f}",
        "Total con FV (MXN)": f"${r['total_mxn']:,.0f}",
        "Ahorro (MXN)": f"${r['savings_mxn']:,.0f}",
    })

df_table = pd.DataFrame(table_rows)
st.dataframe(df_table, use_container_width=True, hide_index=True)

# ── Annual aggregates ─────────────────────────────────────────────────────────
annual = calc.annual_savings(monthly_results)
st.divider()
st.markdown("### Resumen anual")

a1, a2, a3, a4 = st.columns(4)
a1.metric("Generación FV total", f"{annual['solar_generated_kwh']:,.0f} kWh")
a2.metric("Factura sin FV", f"${annual['orig_total_mxn']:,.0f} MXN")
a3.metric("Factura con FV", f"${annual['total_mxn']:,.0f} MXN")
a4.metric("Ahorro anual total", f"${annual['savings_mxn']:,.0f} MXN",
           delta=f"{annual['savings_mxn']/annual['orig_total_mxn']*100:.1f}%")

a5, a6, a7, a8 = st.columns(4)
a5.metric("Ahorro energía", f"${annual['savings_energy_mxn']:,.0f} MXN")
a6.metric("Ahorro capacidad", f"${annual['savings_capacidad_mxn']:,.0f} MXN")
a7.metric("Ahorro distribución", f"${annual['savings_distribucion_mxn']:,.0f} MXN")
payback = calc.payback_period(total_capex_mxn, annual["savings_mxn"])
a8.metric("Payback simple", f"{payback:.1f} años" if payback < 100 else ">100 años")

# ── Waterfall for first month ─────────────────────────────────────────────────
st.divider()
st.markdown("### Desglose de ahorro mensual (waterfall)")
month_sel = st.selectbox("Selecciona mes",
                          [month_names[r["month"] - 1] for r in monthly_results],
                          index=0)
sel_result = monthly_results[[month_names[r["month"] - 1] for r in monthly_results].index(month_sel)]
fig_wf = savings_waterfall(sel_result)
st.plotly_chart(fig_wf, use_container_width=True)

col_pie, col_bar = st.columns(2)
with col_pie:
    st.markdown("#### Consumo por período (con FV)")
    fig_pie = energy_pie(sel_result)
    st.plotly_chart(fig_pie, use_container_width=True)

with col_bar:
    if len(monthly_results) > 1:
        st.markdown("#### Comparación mensual")
        fig_monthly = monthly_savings_bar(monthly_results)
        st.plotly_chart(fig_monthly, use_container_width=True)

# ── Multi-year projection ─────────────────────────────────────────────────────
st.divider()
st.markdown("### Proyección multi-año")

annual_savings_base = annual["savings_mxn"]
opex_annual_mxn = total_capex_mxn * (opex_pct / 100)
inflation = inflation_pct / 100

years = list(range(1, project_life + 1))
cumulative_net = []
annual_net_savings = []
cumulative = -total_capex_mxn
for yr in years:
    savings_yr = annual_savings_base * ((1 + inflation) ** (yr - 1))
    net_yr = savings_yr - opex_annual_mxn
    annual_net_savings.append(net_yr)
    cumulative += net_yr
    cumulative_net.append(cumulative)

import plotly.graph_objects as go

fig_proj = go.Figure()
fig_proj.add_trace(go.Bar(x=years, y=annual_net_savings, name="Ahorro neto anual",
                           marker_color="#FFB300"))
fig_proj.add_trace(go.Scatter(x=years, y=cumulative_net, name="Flujo acumulado",
                               line=dict(color="#0039A6", width=2.5), yaxis="y2"))
fig_proj.add_hline(y=0, line_dash="dash", line_color="gray")
fig_proj.update_layout(
    template="plotly_white",
    xaxis_title="Año",
    yaxis_title="Ahorro neto (MXN/año)",
    yaxis2=dict(title="Flujo acumulado (MXN)", overlaying="y", side="right",
                showgrid=False),
    height=380,
    legend=dict(orientation="h", y=-0.15),
    margin=dict(t=10, b=60),
    hovermode="x unified",
)
st.plotly_chart(fig_proj, use_container_width=True)

npv = sum(net / (1 + 0.10) ** yr for yr, net in zip(years, annual_net_savings)) - total_capex_mxn
roi_pct = (sum(annual_net_savings) / total_capex_mxn * 100) if total_capex_mxn > 0 else 0

fin1, fin2, fin3 = st.columns(3)
fin1.metric("VPN (10% WACC)", f"${npv:,.0f} MXN", delta="Positivo" if npv > 0 else "Negativo")
fin2.metric("ROI total", f"{roi_pct:.0f} %")
fin3.metric("CAPEX / kWp instalado", f"${total_capex_usd/system_kwp:,.0f} USD/kWp" if system_kwp > 0 else "—")

# ── Export ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### Exportar resultados")

col_x1, col_x2, col_x3 = st.columns(3)

# Excel export
with col_x1:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_table.to_excel(writer, sheet_name="Resumen mensual", index=False)
        pd.DataFrame([{
            "Generación FV (kWh/año)": annual["solar_generated_kwh"],
            "Factura sin FV (MXN/año)": annual["orig_total_mxn"],
            "Factura con FV (MXN/año)": annual["total_mxn"],
            "Ahorro anual (MXN)": annual["savings_mxn"],
            "Payback (años)": payback,
            "VPN (MXN)": npv,
            "ROI (%)": roi_pct,
            "CAPEX total (MXN)": total_capex_mxn,
        }]).to_excel(writer, sheet_name="Indicadores", index=False)
        pd.DataFrame({"Año": years, "Ahorro neto (MXN)": annual_net_savings,
                      "Flujo acumulado (MXN)": cumulative_net}).to_excel(
            writer, sheet_name="Proyección multi-año", index=False)
    buf.seek(0)
    st.download_button("Descargar Excel", data=buf, file_name="analisis_gdmth.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# PDF export
with col_x2:
    if st.button("Generar reporte PDF", type="primary"):
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.lib.units import inch

            pdf_buf = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buf, pagesize=letter,
                                     leftMargin=0.75*inch, rightMargin=0.75*inch,
                                     topMargin=0.75*inch, bottomMargin=0.75*inch)
            styles = getSampleStyleSheet()
            tec_blue = colors.HexColor("#0039A6")
            solar_yellow = colors.HexColor("#FFB300")

            title_style = ParagraphStyle("title", parent=styles["Title"],
                                          textColor=tec_blue, fontSize=18)
            h2_style = ParagraphStyle("h2", parent=styles["Heading2"],
                                       textColor=tec_blue, fontSize=13)
            normal = styles["Normal"]

            story = []

            # Title
            story.append(Paragraph("Análisis Económico Solar — Tarifa GDMTH", title_style))
            story.append(Paragraph("Tecnológico de Monterrey", normal))
            story.append(Spacer(1, 0.15*inch))

            # Team info
            members = st.session_state.get("members", [])
            team_no = st.session_state.get("team_number", "—")
            story.append(Paragraph(f"Equipo #{team_no}", h2_style))
            for m in members:
                if m.get("name"):
                    story.append(Paragraph(f"• {m['name']} ({m.get('student_id','—')}) — {m.get('role','—')}", normal))
            story.append(Spacer(1, 0.1*inch))

            # System config
            story.append(Paragraph("Configuración del sistema", h2_style))
            story.append(Paragraph(
                f"Ubicación: {st.session_state.get('city','—')} | "
                f"Latitud: {st.session_state.get('lat','—')}°N | "
                f"Longitud: {st.session_state.get('lon','—')}°E", normal))
            if panel:
                story.append(Paragraph(
                    f"Panel: {panel.get('brand','')} {panel.get('model','')} | "
                    f"{panel.get('wp',0)}Wp | {panel.get('efficiency_pct',0)}% eficiencia", normal))
            story.append(Paragraph(
                f"Sistema: {system_kwp:.2f} kWp | "
                f"CAPEX total: ${total_capex_mxn:,.0f} MXN (${total_capex_usd:,.0f} USD)", normal))
            story.append(Spacer(1, 0.1*inch))

            # Financial indicators
            story.append(Paragraph("Indicadores financieros", h2_style))
            indicators = [
                ["Indicador", "Valor"],
                ["Generación FV (kWh/año)", f"{annual['solar_generated_kwh']:,.0f}"],
                ["Ahorro anual (MXN)", f"${annual['savings_mxn']:,.0f}"],
                ["Factura sin FV (MXN/año)", f"${annual['orig_total_mxn']:,.0f}"],
                ["Factura con FV (MXN/año)", f"${annual['total_mxn']:,.0f}"],
                ["Payback simple", f"{payback:.1f} años"],
                ["VPN (10% WACC)", f"${npv:,.0f} MXN"],
                ["ROI total", f"{roi_pct:.0f} %"],
            ]
            t = Table(indicators, colWidths=[3.5*inch, 2.5*inch])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), tec_blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.1*inch))

            # Monthly table
            story.append(Paragraph("Desglose mensual de cargos GDMTH", h2_style))
            monthly_data = [["Mes", "Sin FV (MXN)", "Con FV (MXN)", "Ahorro (MXN)"]]
            for r in monthly_results:
                monthly_data.append([
                    month_names[r["month"] - 1],
                    f"${r['orig_total_mxn']:,.0f}",
                    f"${r['total_mxn']:,.0f}",
                    f"${r['savings_mxn']:,.0f}",
                ])
            mt = Table(monthly_data, colWidths=[1.5*inch, 2*inch, 2*inch, 2*inch])
            mt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), tec_blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(mt)
            story.append(Spacer(1, 0.15*inch))

            # Abstract
            abstract = st.session_state.get("abstract", "")
            if abstract:
                story.append(Paragraph("Resumen metodológico", h2_style))
                story.append(Paragraph(abstract, normal))
                story.append(Spacer(1, 0.1*inch))

            story.append(Paragraph(
                f"Generado: {datetime.date.today()} | Modelo: Jensen isótropo (pvlib) | "
                f"Región CFE: {region}",
                ParagraphStyle("footer", parent=normal, textColor=colors.gray, fontSize=8)
            ))

            doc.build(story)
            pdf_buf.seek(0)
            st.session_state["report_pdf"] = pdf_buf.getvalue()
            st.success("PDF generado exitosamente.")
        except ImportError:
            st.error("Instala reportlab: `pip install reportlab`")
        except Exception as e:
            st.error(f"Error generando PDF: {e}")

if "report_pdf" in st.session_state:
    with col_x3:
        st.download_button(
            "Descargar PDF",
            data=st.session_state["report_pdf"],
            file_name="reporte_gdmth_solar.pdf",
            mime="application/pdf",
        )
