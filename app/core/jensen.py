"""
Jensen (isotropic diffuse) irradiance model wrapper using pvlib.
Reference: Jensen et al. (2023) pvlib iotools. Solar Energy, 266, 112092.
DOI: 10.1016/j.solener.2023.112092

Energy formula (per lecture):
    Pow [kW] = POA × AreaPanel × η_panel
    E_anual [kWh] = Σ(Pow_i × Δt)   where Δt = 15/60 h (quinceminutal) or 1 h (horario)
    N = 35,040 periodos quinceminutales/año  |  N = 8,760 periodos horarios/año
"""

import numpy as np
import pandas as pd
import pvlib
from pvlib.location import Location
from pvlib import irradiance

# Time-step in hours for each supported frequency
FREQ_DT = {"15min": 0.25, "h": 1.0, "1h": 1.0}


def get_location(lat: float, lon: float, tz: str = "America/Monterrey", altitude: float = 500.0) -> Location:
    return Location(latitude=lat, longitude=lon, tz=tz, altitude=altitude, name="Site")


def run_jensen_model(
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    start_date: str,
    end_date: str,
    tz: str = "America/Monterrey",
    altitude: float = 500.0,
    freq: str = "h",
) -> pd.DataFrame:
    """
    Compute POA irradiance using pvlib's isotropic diffuse transposition
    (Jensen/isotropic sky model).

    Parameters
    ----------
    lat, lon      : site coordinates
    tilt          : panel tilt angle (degrees from horizontal)
    azimuth       : panel azimuth (degrees; 180 = south)
    start_date    : 'YYYY-MM-DD'
    end_date      : 'YYYY-MM-DD'
    tz            : pytz timezone string
    altitude      : metres above sea level
    freq          : time resolution — '15min' (quinceminutal, N=35040/yr)
                    or 'h' (hourly, N=8760/yr)

    Returns
    -------
    DataFrame with columns: ghi, dni, dhi, poa_global, poa_direct,
    poa_diffuse, poa_sky_diffuse, poa_ground_diffuse, zenith, azimuth_sun
    DataFrame.attrs['dt_h'] contains the time-step in hours.
    """
    location = get_location(lat, lon, tz, altitude)

    # Generate times covering full days from start_date through end_date.
    # end_date is inclusive so we extend to the next day and then trim.
    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    times = pd.date_range(start=start_date, end=end_exclusive, freq=freq, tz=tz, inclusive="left")

    solar_pos = location.get_solarposition(times)
    clearsky = location.get_clearsky(times, model="ineichen")  # Ineichen clear-sky

    ghi = clearsky["ghi"]
    dni = clearsky["dni"]
    dhi = clearsky["dhi"]

    # Jensen isotropic diffuse transposition
    poa_components = irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=solar_pos["apparent_zenith"],
        solar_azimuth=solar_pos["azimuth"],
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        model="isotropic",
        albedo=0.25,
    )

    df = pd.DataFrame(
        {
            "ghi": ghi.values,
            "dni": dni.values,
            "dhi": dhi.values,
            "poa_global": poa_components["poa_global"].values,
            "poa_direct": poa_components["poa_direct"].values,
            "poa_diffuse": poa_components["poa_diffuse"].values,
            "poa_sky_diffuse": poa_components["poa_sky_diffuse"].values,
            "poa_ground_diffuse": poa_components["poa_ground_diffuse"].values,
            "zenith": solar_pos["apparent_zenith"].values,
            "azimuth_sun": solar_pos["azimuth"].values,
        },
        index=times,
    )

    df = df.clip(lower=0)
    df.attrs["dt_h"] = FREQ_DT.get(freq, 1.0)
    df.attrs["freq"] = freq
    return df


def compute_pv_generation(
    irradiance_df: pd.DataFrame,
    system_kwp: float,
    panel_efficiency: float,
    panel_wp: float,
    panel_area_m2: float | None = None,
    n_panels: int | None = None,
    temp_coeff_pmax: float = -0.30,
    noct: float = 43.0,
    ambient_temp_c: float = 25.0,
) -> pd.Series:
    """
    Estimate AC power output (kW) per time-step using the lecture formula:

        Pow [kW] = POA [W/m²] × AreaTotal [m²] × η_panel / 1000

    with NOCT temperature derating and inverter efficiency (0.96).

    To obtain energy: E [kWh] = Σ(Pow_i × dt_h)
    where dt_h = irradiance_df.attrs.get('dt_h', 1.0)

    Parameters
    ----------
    panel_area_m2  : physical area of one panel (m²). If None, derived from Wp/η.
    n_panels       : override number of panels (if None, derived from system_kwp/panel_wp).
    """
    _n = n_panels if n_panels is not None else int((system_kwp * 1000) / panel_wp)
    if panel_area_m2 is not None and panel_area_m2 > 0:
        total_area_m2 = _n * panel_area_m2
    else:
        # Derive from Wp and efficiency: Area = Wp / (1000 × η)
        total_area_m2 = _n * (panel_wp / (1000.0 * panel_efficiency / 100.0))

    poa = irradiance_df["poa_global"].copy()

    # NOCT cell temperature model
    t_cell = ambient_temp_c + (noct - 20.0) * (poa / 800.0)

    # Temperature derating: Pow *= [1 + α_Pmax/100 × (T_cell - 25)]
    derate = 1.0 + (temp_coeff_pmax / 100.0) * (t_cell - 25.0)
    derate = derate.clip(lower=0.5)

    # Pow [kW] = POA × A_total × η × derate × η_inverter
    p_ac_kw = (poa * total_area_m2 * (panel_efficiency / 100.0) * derate * 0.96) / 1000.0
    p_ac_kw = p_ac_kw.clip(lower=0)

    return p_ac_kw


def energy_kwh(power_kw: pd.Series, irradiance_df: pd.DataFrame | None = None,
               dt_h: float | None = None) -> float:
    """
    E [kWh] = Σ(Pow_i × dt_h)
    Per lecture formula with quinceminutal (dt_h=0.25, N=35040) or hourly (dt_h=1, N=8760).
    """
    _dt = dt_h or (irradiance_df.attrs.get("dt_h", 1.0) if irradiance_df is not None else 1.0)
    return float(power_kw.sum() * _dt)


def capacity_factor(generation_kw: pd.Series, system_kwp: float,
                    irradiance_df: pd.DataFrame | None = None) -> float:
    """CF = E_actual / (kWp × total_hours)."""
    n = len(generation_kw)
    if n == 0 or system_kwp == 0:
        return 0.0
    dt_h = irradiance_df.attrs.get("dt_h", 1.0) if irradiance_df is not None else 1.0
    total_hours = n * dt_h
    return float(energy_kwh(generation_kw, dt_h=dt_h) / (system_kwp * total_hours))


def peak_sun_hours(irradiance_df: pd.DataFrame) -> float:
    """PSH = Σ(GHI × dt_h) / 1000"""
    dt_h = irradiance_df.attrs.get("dt_h", 1.0)
    return float(irradiance_df["ghi"].sum() * dt_h / 1000.0)
