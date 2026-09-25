import calendar
from datetime import date, timedelta
import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import Ridge

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "sunshine_duration",
]


def _json_to_daily(js):
    daily = js.get("daily", {}) if isinstance(js, dict) else {}
    if not daily or not daily.get("time"):
        return pd.DataFrame(columns=["date","tmax","tmin","tavg","rain_mm","sunshine_h"])
    out = pd.DataFrame({
        "date": pd.to_datetime(daily.get("time", [])),
        "tmax": pd.to_numeric(pd.Series(daily.get("temperature_2m_max", [])), errors="coerce"),
        "tmin": pd.to_numeric(pd.Series(daily.get("temperature_2m_min", [])), errors="coerce"),
        "rain_mm": pd.to_numeric(pd.Series(daily.get("precipitation_sum", [])), errors="coerce"),
        "sunshine_sec": pd.to_numeric(pd.Series(daily.get("sunshine_duration", [])), errors="coerce"),
    })
    out["tavg"] = (out["tmax"] + out["tmin"]) / 2.0
    out["sunshine_h"] = out["sunshine_sec"].fillna(0) / 3600.0
    return out.drop(columns=["sunshine_sec"])


def fetch_history(lat, lon, start_date, end_date, timeout=30):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "start_date": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
        "end_date": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
        "daily": ",".join(DAILY_VARS),
        "timezone": "Asia/Ho_Chi_Minh",
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return _json_to_daily(r.json())


def fetch_forecast(lat, lon, forecast_days=16, timeout=20):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "daily": ",".join(DAILY_VARS),
        "forecast_days": int(forecast_days),
        "timezone": "Asia/Ho_Chi_Minh",
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return _json_to_daily(r.json())


def apply_overrides(daily_df, overrides):
    if daily_df is None or daily_df.empty or not overrides:
        return daily_df.copy() if daily_df is not None else pd.DataFrame()
    out = daily_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    ov = pd.DataFrame(overrides).copy()
    if ov.empty or "date" not in ov.columns:
        return out
    ov["date"] = pd.to_datetime(ov["date"], errors="coerce")
    for _, row in ov.dropna(subset=["date"]).iterrows():
        mask = out["date"].dt.normalize() == pd.Timestamp(row["date"]).normalize()
        if not mask.any():
            continue
        for col in ["tmax", "tmin", "rain_mm", "sunshine_h"]:
            if col in row and pd.notna(row[col]):
                out.loc[mask, col] = float(row[col])
    out["tavg"] = (out["tmax"] + out["tmin"]) / 2.0
    return out


def monthly_features(daily_df):
    cols = ["date","temp_avg","temp_max","temp_min","hot35","hot37","rain_mm","rain_days","sunshine_h","days_obs"]
    if daily_df is None or daily_df.empty:
        return pd.DataFrame(columns=cols)
    x = daily_df.copy()
    x["date"] = pd.to_datetime(x["date"])
    x["month"] = x["date"].dt.to_period("M").dt.to_timestamp()
    x["hot35_flag"] = (x["tmax"] >= 35).astype(int)
    x["hot37_flag"] = (x["tmax"] >= 37).astype(int)
    x["rain_flag"] = (x["rain_mm"].fillna(0) >= 1.0).astype(int)
    g = x.groupby("month").agg(
        temp_avg=("tavg","mean"),
        temp_max=("tmax","max"),
        temp_min=("tmin","min"),
        hot35=("hot35_flag","sum"),
        hot37=("hot37_flag","sum"),
        rain_mm=("rain_mm","sum"),
        rain_days=("rain_flag","sum"),
        sunshine_h=("sunshine_h","sum"),
        days_obs=("date","count"),
    ).reset_index().rename(columns={"month":"date"})
    return g[cols]


def _climatology_by_calendar_month(hist_daily):
    mf = monthly_features(hist_daily)
    if mf.empty:
        return pd.DataFrame()
    mf["cal_month"] = pd.to_datetime(mf["date"]).dt.month
    metrics = ["temp_avg","temp_max","temp_min","hot35","hot37","rain_mm","rain_days","sunshine_h","days_obs"]
    return mf.groupby("cal_month")[metrics].mean().reset_index()


def future_month_features(hist_daily, forecast_daily, origin_date, horizon=3):
    clim = _climatology_by_calendar_month(hist_daily)
    if clim.empty:
        return pd.DataFrame()
    f = forecast_daily.copy() if forecast_daily is not None else pd.DataFrame()
    if not f.empty:
        f["date"] = pd.to_datetime(f["date"])
    out = []
    origin = pd.Timestamp(origin_date).to_period("M").to_timestamp()
    for h in range(1, horizon + 1):
        month_start = origin + pd.offsets.MonthBegin(h)
        cm = int(month_start.month)
        days = calendar.monthrange(int(month_start.year), cm)[1]
        base = clim.loc[clim["cal_month"] == cm]
        if base.empty:
            continue
        base = base.iloc[0].to_dict()
        row = {
            "date": month_start,
            "temp_avg": float(base["temp_avg"]),
            "temp_max": float(base["temp_max"]),
            "temp_min": float(base["temp_min"]),
            "hot35": float(base["hot35"]),
            "hot37": float(base["hot37"]),
            "rain_mm": float(base["rain_mm"]),
            "rain_days": float(base["rain_days"]),
            "sunshine_h": float(base["sunshine_h"]),
            "days_obs": float(days),
            "source": "khí hậu lịch sử",
        }
        if not f.empty:
            mask = (f["date"].dt.year == month_start.year) & (f["date"].dt.month == month_start.month)
            fm = f.loc[mask]
            if not fm.empty:
                known = len(fm)
                share = min(1.0, known / days)
                ffeat = monthly_features(fm).iloc[0]
                # Blend means; counts/sums combine known forecast + climatological missing-day rates.
                row["temp_avg"] = share*float(ffeat["temp_avg"]) + (1-share)*row["temp_avg"]
                row["temp_max"] = max(float(ffeat["temp_max"]), row["temp_max"])
                row["temp_min"] = min(float(ffeat["temp_min"]), row["temp_min"])
                row["hot35"] = float(ffeat["hot35"]) + (days-known)*(float(base["hot35"])/max(float(base["days_obs"]),1))
                row["hot37"] = float(ffeat["hot37"]) + (days-known)*(float(base["hot37"])/max(float(base["days_obs"]),1))
                row["rain_mm"] = float(ffeat["rain_mm"]) + (days-known)*(float(base["rain_mm"])/max(float(base["days_obs"]),1))
                row["rain_days"] = float(ffeat["rain_days"]) + (days-known)*(float(base["rain_days"])/max(float(base["days_obs"]),1))
                row["sunshine_h"] = float(ffeat["sunshine_h"]) + (days-known)*(float(base["sunshine_h"])/max(float(base["days_obs"]),1))
                row["source"] = f"dự báo {known} ngày + khí hậu lịch sử"
        out.append(row)
    return pd.DataFrame(out)


def _design_table(series, weather_monthly):
    s = series[["date","actual"]].copy()
    s["date"] = pd.to_datetime(s["date"]).dt.to_period("M").dt.to_timestamp()
    w = weather_monthly.copy()
    w["date"] = pd.to_datetime(w["date"]).dt.to_period("M").dt.to_timestamp()
    x = s.merge(w, on="date", how="inner").sort_values("date")
    x["lag1"] = x["actual"].shift(1)
    x["lag2"] = x["actual"].shift(2)
    m = x["date"].dt.month
    x["sin12"] = np.sin(2*np.pi*m/12)
    x["cos12"] = np.cos(2*np.pi*m/12)
    return x.dropna().reset_index(drop=True)


def weather_ridge_backtest(series, hist_daily, max_origins=12):
    wm = monthly_features(hist_daily)
    x = _design_table(series, wm)
    if len(x) < 12:
        return np.nan
    feats = ["lag1","lag2","temp_avg","temp_max","hot35","hot37","rain_mm","rain_days","sunshine_h","sin12","cos12"]
    errors=[]
    start=max(8, len(x)-max_origins)
    for i in range(start, len(x)):
        tr=x.iloc[:i]
        te=x.iloc[i:i+1]
        if len(tr)<8: continue
        model=Ridge(alpha=1.0)
        model.fit(tr[feats], tr["actual"])
        pred=float(model.predict(te[feats])[0])
        act=float(te["actual"].iloc[0])
        if act!=0: errors.append(abs((act-pred)/act)*100)
    return float(np.mean(errors)) if errors else np.nan


def weather_ridge_forecast(series, hist_daily, forecast_daily, horizon=3):
    wm = monthly_features(hist_daily)
    x = _design_table(series, wm)
    if len(x) < 12:
        return pd.DataFrame(), np.nan
    feats = ["lag1","lag2","temp_avg","temp_max","hot35","hot37","rain_mm","rain_days","sunshine_h","sin12","cos12"]
    model=Ridge(alpha=1.0)
    model.fit(x[feats], x["actual"])
    fut = future_month_features(hist_daily, forecast_daily, series["date"].iloc[-1], horizon=horizon)
    if fut.empty:
        return pd.DataFrame(), np.nan
    hist_vals=list(series["actual"].astype(float).values)
    preds=[]
    for _,r in fut.iterrows():
        m=pd.Timestamp(r["date"]).month
        row={
            "lag1":hist_vals[-1],
            "lag2":hist_vals[-2] if len(hist_vals)>1 else hist_vals[-1],
            "temp_avg":r["temp_avg"],"temp_max":r["temp_max"],"hot35":r["hot35"],"hot37":r["hot37"],
            "rain_mm":r["rain_mm"],"rain_days":r["rain_days"],"sunshine_h":r["sunshine_h"],
            "sin12":np.sin(2*np.pi*m/12),"cos12":np.cos(2*np.pi*m/12),
        }
        pred=float(model.predict(pd.DataFrame([row])[feats])[0])
        preds.append(pred); hist_vals.append(pred)
    out=fut.copy(); out["forecast_weather_ridge"]=preds
    return out, weather_ridge_backtest(series,hist_daily)
