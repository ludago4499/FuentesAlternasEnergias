# GDMTH Solar Analyzer
**Herramienta de análisis económico solar para tarifa CFE GDMTH**
Tecnológico de Monterrey — Programación para Ingeniería

---

## Descripción

Aplicación Streamlit para evaluar la viabilidad económica de un sistema fotovoltaico (FV) para clientes industriales bajo la tarifa **GDMTH (Gran Demanda en Media Tensión Horaria)** de la Comisión Federal de Electricidad (CFE) de México.

### Características principales
- Modelo de irradiancia **Jensen (isótropo)** vía pvlib
- Catálogo de paneles Tier 1: Jinko, LONGi, Trina, Canadian Solar
- Estructura tarifaria GDMTH completa: Energía + Capacidad + Distribución
- Carga de curva de demanda industrial real (CSV)
- Análisis de peak shaving y autoconsumo
- Proyección financiera multi-año con VPN, ROI y payback
- Exportación a **Excel** y **PDF** (reportlab)

---

## Instalación y ejecución

### Requisitos previos
- Python 3.11+
- Git

### Windows (PowerShell)
```powershell
cd Streger
.\run.ps1
```

### Linux / macOS
```bash
cd Streger
bash run.sh
```

### Manual (cualquier plataforma)
```bash
# 1. Crear entorno virtual
python -m venv .venv

# 2. Activar
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar
streamlit run app/main.py
```

La app abre en **http://localhost:8501**

---

## Estructura del proyecto

```
Streger/
├── app/
│   ├── main.py                  # Entrada Streamlit (página de inicio + sidebar)
│   ├── pages/
│   │   ├── 1_team.py            # Información del equipo + abstract
│   │   ├── 2_config.py          # Configuración panel / batería / ubicación
│   │   ├── 3_solar.py           # Modelo Jensen, POA, generación FV
│   │   ├── 4_demand.py          # Curva de carga + inyección solar
│   │   └── 5_economics.py       # Tarifas GDMTH + ahorros + PDF
│   ├── core/
│   │   ├── jensen.py            # Wrapper pvlib modelo isótropo
│   │   ├── gdmth.py             # Calculadora tarifa GDMTH
│   │   └── plots.py             # Constructores Plotly
│   └── data/
│       ├── panels.json          # Catálogo paneles Tier 1
│       ├── batteries.json       # Catálogo baterías
│       ├── tariff_gdmth.json    # Tarifas CFE por región y temporada
│       └── sample_load.csv      # Curva de carga industrial de muestra
├── requirements.txt
├── run.sh                       # Script de inicio Linux/Mac
├── run.ps1                      # Script de inicio Windows
└── README.md
```

---

## Metodología

### Modelo de irradiancia Jensen (isótropo difuso)

El modelo asume distribución uniforme (isótropa) de la radiación difusa del cielo. La irradiancia en el plano del panel (POA) se calcula como:

$$G_{POA} = G_b \cdot R_b + G_{dh} \cdot \frac{1+\cos\beta}{2} + G_{gh} \cdot \rho \cdot \frac{1-\cos\beta}{2}$$

donde:
- $G_b$ = irradiancia directa (beam) horizontal
- $R_b$ = factor geométrico beam (función del ángulo solar y orientación del panel)
- $G_{dh}$ = irradiancia difusa horizontal
- $\beta$ = ángulo de inclinación del panel
- $G_{gh}$ = irradiancia global horizontal
- $\rho$ = albedo del suelo (default 0.25)

**Cielo claro:** Modelo Ineichen-Perez implementado en pvlib.

**Referencia:** Jensen, A. R., Sánchez-González, A., Poulsen, P. B., Deline, C., & Holmgren, W. F. (2022). *pvlib python: A python package for modeling solar energy systems.* SoftwareX, 20, 101070.
[DOI: 10.1016/j.softx.2022.101070](https://doi.org/10.1016/j.softx.2022.101070)

### Temperatura de celda

$$T_{cell} = T_{amb} + (NOCT - 20) \cdot \frac{G_{POA}}{800}$$

La potencia se derata por temperatura usando el coeficiente $\alpha_{Pmax}$ del fabricante:

$$P_{dc} = G_{POA} \cdot A_{total} \cdot \eta_{panel} \cdot [1 + \alpha_{Pmax}(T_{cell} - 25)]$$

### Tarifa GDMTH

La tarifa tiene tres componentes:

| Cargo | Base de facturación | Unidad |
|-------|---------------------|--------|
| **Energía Punta** | kWh consumidos 18:00–22:00 (L–V) | MXN/kWh |
| **Energía Intermedia** | kWh consumidos en horario intermedio | MXN/kWh |
| **Energía Base** | kWh consumidos en horario base (nocturno) | MXN/kWh |
| **Capacidad** | Máx. demanda media en Punta (12 meses) | MXN/kW/mes |
| **Distribución** | Máx. demanda integrada del período | MXN/kW/mes |

Existen dos temporadas tarifarias:
- **Alta:** febrero a septiembre
- **Baja:** octubre a enero

---

## Datos de entrada requeridos

### Curva de carga (CSV)
```csv
timestamp,demand_kw
2024-01-01 00:00:00,185.3
2024-01-01 01:00:00,172.1
...
```
- Resolución: **horaria**
- Valores: potencia activa en kW
- Mínimo recomendado: 1 mes (744 filas)

---

## Dependencias principales

| Paquete | Versión | Uso |
|---------|---------|-----|
| streamlit | ≥1.35 | Interfaz web |
| pvlib | ≥0.11 | Modelo solar Jensen |
| pandas | ≥2.2 | Procesamiento de datos |
| plotly | ≥5.22 | Visualizaciones interactivas |
| openpyxl | ≥3.1 | Exportación Excel |
| reportlab | ≥4.2 | Generación de PDF |

---

## Licencia

Proyecto académico — Tecnológico de Monterrey. Solo para fines educativos.
