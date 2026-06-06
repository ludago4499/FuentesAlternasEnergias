"""
Jensen (isotropic diffuse) irradiance model wrapper using pvlib.
Reference: Jensen et al. (2023) pvlib iotools. Solar Energy, 266, 112092.
DOI: 10.1016/j.solener.2023.112092

Energy formula (per lecture):
    Pow [kW] = POA × AreaPanel × η_panel
    E_anual [kWh] = Σ(Pow_i × Δt)   where Δt = 15/60 h (quinceminutal) or 1 h (horario)
    N = 35,040 periodos quinceminutales/año  |  N = 8,760 periodos horarios/año
"""
# Puto el que lo lea

import numpy as np
import pandas as pd
import pvlib
from pvlib.location import Location
from pvlib import irradiance

FREQ_DT = {"15min": 0.25, "h": 1.0, "1h": 1.0}


def get_location(lat: float, lon: float, tz: str = "America/Monterrey", altitude: float = 500.0) -> Location:
    return Location(latitude=lat, longitude=lon, tz=tz, altitude=altitude, name="Site")


def _build_poa_df(ghi, dni, dhi, solar_pos: pd.DataFrame, tilt: float, azimuth: float, index) -> pd.DataFrame:
    poa = irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=solar_pos["apparent_zenith"],
        solar_azimuth=solar_pos["azimuth"],
        dni=np.asarray(dni),
        ghi=np.asarray(ghi),
        dhi=np.asarray(dhi),
        model="isotropic",
        albedo=0.25,
    )
    df = pd.DataFrame(
        {
            "ghi": np.asarray(ghi),
            "dni": np.asarray(dni),
            "dhi": np.asarray(dhi),
            "poa_global": poa["poa_global"].values,
            "poa_direct": poa["poa_direct"].values,
            "poa_diffuse": poa["poa_diffuse"].values,
            "poa_sky_diffuse": poa["poa_sky_diffuse"].values,
            "poa_ground_diffuse": poa["poa_ground_diffuse"].values,
            "zenith": solar_pos["apparent_zenith"].values,
            "azimuth_sun": solar_pos["azimuth"].values,
        },
        index=index,
    )
    return df.clip(lower=0)


def _apply_ar1_cloud_model(
    clearsky_df: pd.DataFrame,
    solar_pos: pd.DataFrame,
    tilt: float,
    azimuth: float,
    phi: float = 0.92,
    sigma: float = 0.10,
    kt_min: float = 0.05,
    kt_max: float = 1.0,
    seed: int | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(clearsky_df)

    dates = sorted(set(clearsky_df.index.date))
    n_days = len(dates)
    mu = 0.65

    kt_daily = np.empty(n_days)
    kt_daily[0] = mu
    for i in range(1, n_days):
        kt_daily[i] = mu + phi * (kt_daily[i - 1] - mu) + sigma * rng.standard_normal()
    kt_daily = np.clip(kt_daily, kt_min, kt_max)

    date_to_kt = {d: k for d, k in zip(dates, kt_daily)}
    kt_background = np.array([date_to_kt[ts.date()] for ts in clearsky_df.index])

    phi_fast = 0.55
    sigma_fast = 0.18
    anomaly = np.zeros(n)
    for i in range(1, n):
        anomaly[i] = phi_fast * anomaly[i - 1] + sigma_fast * rng.standard_normal()

    daytime = (clearsky_df["zenith"].values < 87).astype(float)
    anomaly = anomaly * daytime

    kt = np.clip(kt_background + anomaly, kt_min, kt_max)

    ghi_c = clearsky_df["ghi"].values * kt
    dni_c = clearsky_df["dni"].values * kt
    dhi_c = clearsky_df["dhi"].values * kt + (1.0 - kt) * clearsky_df["ghi"].values * 0.15

    df = _build_poa_df(ghi_c, dni_c, dhi_c, solar_pos, tilt, azimuth, clearsky_df.index)
    df["cloud_cover_kt"] = kt
    return df


def fetch_nsrdb_data(
    lat: float,
    lon: float,
    api_key: str,
    email: str,
    start_date: str,
    end_date: str,
    tz: str = "America/Monterrey",
    tilt: float = 20.0,
    azimuth: float = 180.0,
    freq: str = "h",
) -> pd.DataFrame:
    try:
        from pvlib.iotools import get_nsrdb_psm4_tmy as _get_tmy
    except ImportError:
        raise RuntimeError(
            "pvlib >= 0.11 con soporte PSM4 es requerido para datos NSRDB. "
            "Ejecuta: pip install --upgrade pvlib"
        )

    try:
        tmy_df, meta = _get_tmy(
            latitude=lat,
            longitude=lon,
            api_key=api_key,
            email=email,
            map_variables=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Error al obtener datos NSRDB. Verifica API key, email y conexión.\n{exc}"
        ) from exc

    tmy_df.columns = [c.lower().replace(" ", "_") for c in tmy_df.columns]

    if tmy_df.index.tz is None:
        import pytz
        utc_offset = float(meta.get("Time Zone", meta.get("timezone", 0)))
        fixed_tz = pytz.FixedOffset(int(utc_offset * 60))
        tmy_df.index = tmy_df.index.tz_localize(fixed_tz)
    tmy_df = tmy_df.tz_convert(tz)

    if freq == "15min":
        tmy_df = tmy_df.resample("15min").interpolate("linear")

    use_minute = freq == "15min"
    lookup: dict = {}
    for ts, row in tmy_df.iterrows():
        key = (ts.month, ts.day, ts.hour, ts.minute) if use_minute else (ts.month, ts.day, ts.hour)
        lookup[key] = row

    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    target_times = pd.date_range(
        start=start_date, end=end_exclusive, freq=freq, tz=tz, inclusive="left"
    )

    rows = []
    for ts in target_times:
        key = (ts.month, ts.day, ts.hour, ts.minute) if use_minute else (ts.month, ts.day, ts.hour)
        if key in lookup:
            rows.append(lookup[key])
        else:
            fallback = (ts.month, 28, ts.hour, ts.minute) if use_minute else (ts.month, 28, ts.hour)
            rows.append(lookup.get(fallback, pd.Series(0.0, index=tmy_df.columns)))

    aligned = pd.DataFrame(rows, index=target_times)

    ghi = aligned.get("ghi", pd.Series(0.0, index=target_times)).values
    dni = aligned.get("dni", pd.Series(0.0, index=target_times)).values
    dhi = aligned.get("dhi", pd.Series(0.0, index=target_times)).values

    loc = get_location(lat, lon, tz)
    solar_pos = loc.get_solarposition(target_times)

    df = _build_poa_df(ghi, dni, dhi, solar_pos, tilt, azimuth, target_times)

    temp_col = aligned.get("temp_air", None)
    if temp_col is not None:
        df["ambient_temp_c"] = temp_col.values

    return df


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
    weather_source: str = "clearsky",
    nsrdb_api_key: str | None = None,
    nsrdb_email: str | None = None,
    stochastic_seed: int | None = None,
    ar1_phi: float = 0.92,
    ar1_sigma: float = 0.10,
    kt_min: float = 0.05,
    kt_max: float = 1.0,
    soiling_loss_frac: float = 0.02,
    wiring_loss_frac: float = 0.015,
    return_clearsky_baseline: bool = False,
) -> "pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]":
    loc = get_location(lat, lon, tz, altitude)

    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    times = pd.date_range(start=start_date, end=end_exclusive, freq=freq, tz=tz, inclusive="left")

    solar_pos = loc.get_solarposition(times)
    clearsky = loc.get_clearsky(times, model="ineichen")

    df_clearsky = _build_poa_df(
        clearsky["ghi"], clearsky["dni"], clearsky["dhi"],
        solar_pos, tilt, azimuth, times,
    )

    if weather_source == "clearsky":
        df_actual = df_clearsky.copy()

    elif weather_source == "stochastic":
        df_actual = _apply_ar1_cloud_model(
            df_clearsky, solar_pos, tilt, azimuth,
            phi=ar1_phi, sigma=ar1_sigma, kt_min=kt_min, kt_max=kt_max,
            seed=stochastic_seed,
        )

    elif weather_source == "nsrdb":
        if not nsrdb_api_key or not nsrdb_email:
            raise ValueError("nsrdb_api_key y nsrdb_email son requeridos para weather_source='nsrdb'.")
        df_actual = fetch_nsrdb_data(
            lat=lat, lon=lon, api_key=nsrdb_api_key, email=nsrdb_email,
            start_date=start_date, end_date=end_date,
            tz=tz, tilt=tilt, azimuth=azimuth, freq=freq,
        )

    else:
        raise ValueError(f"weather_source desconocido: {weather_source!r}.")

    dt_h = FREQ_DT.get(freq, 1.0)
    for df in (df_actual, df_clearsky):
        df.attrs["dt_h"] = dt_h
        df.attrs["freq"] = freq
        df.attrs["soiling_loss_frac"] = soiling_loss_frac
        df.attrs["wiring_loss_frac"] = wiring_loss_frac
    df_actual.attrs["weather_source"] = weather_source
    df_clearsky.attrs["weather_source"] = "clearsky"

    if return_clearsky_baseline:
        return df_actual, df_clearsky
    return df_actual


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
    _n = n_panels if n_panels is not None else int((system_kwp * 1000) / panel_wp)
    if panel_area_m2 is not None and panel_area_m2 > 0:
        total_area_m2 = _n * panel_area_m2
    else:
        total_area_m2 = _n * (panel_wp / (1000.0 * panel_efficiency / 100.0))

    poa = irradiance_df["poa_global"].copy()

    if "ambient_temp_c" in irradiance_df.columns:
        t_amb = irradiance_df["ambient_temp_c"].values
    else:
        t_amb = float(ambient_temp_c)

    t_cell = t_amb + (noct - 20.0) * (poa / 800.0)
    derate = 1.0 + (temp_coeff_pmax / 100.0) * (t_cell - 25.0)
    derate = derate.clip(lower=0.5)

    p_ac_kw = (poa * total_area_m2 * (panel_efficiency / 100.0) * derate * 0.96) / 1000.0
    return p_ac_kw.clip(lower=0)


def compute_losses_breakdown(
    df_actual: pd.DataFrame,
    df_clearsky: pd.DataFrame,
    system_kwp: float,
    panel_efficiency: float,
    panel_wp: float,
    panel_area_m2: float | None = None,
    n_panels: int | None = None,
    temp_coeff_pmax: float = -0.30,
    noct: float = 43.0,
    ambient_temp_c: float = 25.0,
    soiling_loss_frac: float = 0.02,
    wiring_loss_frac: float = 0.015,
) -> dict:
    dt_h = df_actual.attrs.get("dt_h", 1.0)

    _n = n_panels if n_panels is not None else int((system_kwp * 1000) / panel_wp)
    if panel_area_m2 and panel_area_m2 > 0:
        total_area = _n * panel_area_m2
    else:
        total_area = _n * (panel_wp / (1000.0 * panel_efficiency / 100.0))

    if "ambient_temp_c" in df_actual.columns:
        t_amb = df_actual["ambient_temp_c"].values
    else:
        t_amb = float(ambient_temp_c)

    eta = panel_efficiency / 100.0

    p_cs = (df_clearsky["poa_global"] * total_area * eta / 1000.0).clip(lower=0)
    e_clearsky = float(p_cs.sum() * dt_h)

    p_cloud = (df_actual["poa_global"] * total_area * eta / 1000.0).clip(lower=0)
    e_after_cloud = float(p_cloud.sum() * dt_h)

    poa = df_actual["poa_global"]
    t_cell = t_amb + (noct - 20.0) * (poa / 800.0)
    derate = (1.0 + (temp_coeff_pmax / 100.0) * (t_cell - 25.0)).clip(lower=0.5)
    daytime = poa > 10
    avg_derate = float(derate[daytime].mean()) if daytime.any() else 1.0
    p_temp = (p_cloud * derate).clip(lower=0)
    e_after_temp = float(p_temp.sum() * dt_h)

    e_after_soiling = float((p_temp * (1.0 - soiling_loss_frac)).sum() * dt_h)

    p_wiring = p_temp * (1.0 - soiling_loss_frac) * (1.0 - wiring_loss_frac)
    e_after_wiring = float(p_wiring.sum() * dt_h)

    e_ac = float((p_wiring * 0.96).sum() * dt_h)

    ref = e_clearsky if e_clearsky > 0.0 else 1.0

    poa_vals = df_actual["poa_global"].values
    poa_cs = df_clearsky["poa_global"].values
    dt_a = poa_vals[poa_vals > 10]
    dt_c = poa_cs[poa_cs > 10]

    return {
        "e_clearsky_kwh": e_clearsky,
        "e_after_cloud_kwh": e_after_cloud,
        "e_after_temp_kwh": e_after_temp,
        "e_after_soiling_kwh": e_after_soiling,
        "e_after_wiring_kwh": e_after_wiring,
        "e_ac_kwh": e_ac,
        "loss_cloud_kwh": e_clearsky - e_after_cloud,
        "loss_temp_kwh": e_after_cloud - e_after_temp,
        "loss_soiling_kwh": e_after_temp - e_after_soiling,
        "loss_wiring_kwh": e_after_soiling - e_after_wiring,
        "loss_inverter_kwh": e_after_wiring - e_ac,
        "loss_cloud_pct": (e_clearsky - e_after_cloud) / ref * 100.0,
        "loss_temp_pct": (e_after_cloud - e_after_temp) / ref * 100.0,
        "loss_soiling_pct": (e_after_temp - e_after_soiling) / ref * 100.0,
        "loss_wiring_pct": (e_after_soiling - e_after_wiring) / ref * 100.0,
        "loss_inverter_pct": (e_after_wiring - e_ac) / ref * 100.0,
        "panel_efficiency_pct": panel_efficiency,
        "avg_temp_derate_factor": avg_derate,
        "soiling_loss_frac": soiling_loss_frac,
        "wiring_loss_frac": wiring_loss_frac,
        "inverter_efficiency_pct": 96.0,
        "overall_system_efficiency_pct": e_ac / ref * 100.0,
        "poa_p50_wm2": float(np.percentile(dt_a, 50)) if len(dt_a) > 0 else 0.0,
        "poa_p90_wm2": float(np.percentile(dt_a, 10)) if len(dt_a) > 0 else 0.0,
        "poa_clearsky_p50_wm2": float(np.percentile(dt_c, 50)) if len(dt_c) > 0 else 0.0,
        "poa_clearsky_p90_wm2": float(np.percentile(dt_c, 10)) if len(dt_c) > 0 else 0.0,
    }


def energy_kwh(power_kw: pd.Series, irradiance_df: pd.DataFrame | None = None,
               dt_h: float | None = None) -> float:
    _dt = dt_h or (irradiance_df.attrs.get("dt_h", 1.0) if irradiance_df is not None else 1.0)
    return float(power_kw.sum() * _dt)


def capacity_factor(generation_kw: pd.Series, system_kwp: float,
                    irradiance_df: pd.DataFrame | None = None) -> float:
    n = len(generation_kw)
    if n == 0 or system_kwp == 0:
        return 0.0
    dt_h = irradiance_df.attrs.get("dt_h", 1.0) if irradiance_df is not None else 1.0
    total_hours = n * dt_h
    return float(energy_kwh(generation_kw, dt_h=dt_h) / (system_kwp * total_hours))


def peak_sun_hours(irradiance_df: pd.DataFrame) -> float:
    dt_h = irradiance_df.attrs.get("dt_h", 1.0)
    return float(irradiance_df["ghi"].sum() * dt_h / 1000.0)