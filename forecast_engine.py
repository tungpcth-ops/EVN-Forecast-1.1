import re
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

MONTH_RE = re.compile(r"điện\s*năng\s*tháng\s*(\d+)", re.I)


def _read_excel(fileobj):
    return pd.read_excel(fileobj)


def parse_customer_file(fileobj, year):
    df = _read_excel(fileobj)
    cols = list(df.columns)
    month_map = {}
    for c in cols:
        m = MONTH_RE.search(str(c))
        if m:
            month_map[c] = int(m.group(1))
    if not month_map:
        raise ValueError("Không tìm thấy các cột 'Điện năng tháng 1...'.")

    # Resolve common identity columns
    id_candidates = ["MA_KHANG", "Mã khách hàng", "MA_KH", "Mã KH"]
    name_candidates = ["TEN_KHANG", "Tên khách hàng", "TEN_KH", "Tên KH"]
    cid = next((c for c in id_candidates if c in df.columns), None)
    cname = next((c for c in name_candidates if c in df.columns), None)
    if cid is None:
        cid = "_row_id"
        df[cid] = np.arange(len(df)).astype(str)
    if cname is None:
        cname = cid

    rows = []
    for col, month in month_map.items():
        vals = pd.to_numeric(df[col], errors="coerce").fillna(0)
        tmp = pd.DataFrame({
            "customer_id": df[cid].astype(str),
            "customer_name": df[cname].astype(str),
            "date": pd.to_datetime({"year": year, "month": month, "day": 1}),
            "kwh": vals,
        })
        # preserve optional metadata
        for meta in ["MA_NN", "LOAI_HDONG", "DIA_CHI", "TEN_TBA"]:
            if meta in df.columns:
                tmp[meta] = df[meta].astype(str)
        rows.append(tmp)
    return pd.concat(rows, ignore_index=True)


def aggregate_monthly(customer_long):
    if customer_long.empty:
        return pd.DataFrame(columns=["date","actual"])
    x = customer_long.groupby("date", as_index=False)["kwh"].sum().rename(columns={"kwh":"actual"})
    return x.sort_values("date")


def build_total_series(history, monthly_from_customers):
    parts = []
    if history is not None and not history.empty:
        h = history.copy()
        # infer date/value columns
        date_col = h.columns[0]
        val_col = h.columns[1] if len(h.columns) > 1 else None
        if val_col:
            h = h[[date_col, val_col]].copy()
            h.columns = ["date", "actual"]
            h["date"] = pd.to_datetime(h["date"], errors="coerce", dayfirst=True)
            h["actual"] = pd.to_numeric(h["actual"], errors="coerce")
            parts.append(h.dropna())
    if monthly_from_customers is not None and not monthly_from_customers.empty:
        parts.append(monthly_from_customers[["date","actual"]].copy())
    if not parts:
        return pd.DataFrame(columns=["date","actual"])
    s = pd.concat(parts, ignore_index=True)
    s = s.sort_values("date").drop_duplicates("date", keep="last")
    s = s[s["actual"] > 0].reset_index(drop=True)
    return s


def detect_top_influence(customer_long, top_n=100):
    if customer_long.empty:
        return pd.DataFrame()
    dates = sorted(customer_long["date"].unique())
    latest = dates[-1]
    prev = dates[-2] if len(dates) >= 2 else None
    latest_df = customer_long[customer_long["date"] == latest].copy()
    base = latest_df[["customer_id","customer_name","kwh"]].rename(columns={"kwh":"latest_kwh"})
    if prev is not None:
        prev_df = customer_long[customer_long["date"] == prev][["customer_id","kwh"]].rename(columns={"kwh":"prev_kwh"})
        base = base.merge(prev_df, on="customer_id", how="left")
    else:
        base["prev_kwh"] = 0
    base["prev_kwh"] = base["prev_kwh"].fillna(0)
    base["delta_kwh"] = base["latest_kwh"] - base["prev_kwh"]
    total = max(base["latest_kwh"].sum(), 1)
    scale = max(base["delta_kwh"].abs().max(), 1)
    base["share_pct"] = base["latest_kwh"] / total * 100
    base["influence_score"] = 0.6*(base["latest_kwh"]/total) + 0.4*(base["delta_kwh"].abs()/scale)
    base = base.sort_values("influence_score", ascending=False).head(top_n).copy()
    base.insert(0, "rank", range(1, len(base)+1))
    return base


def _mape(y, p):
    y = np.asarray(y, float); p = np.asarray(p, float)
    mask = y != 0
    return float(np.mean(np.abs((y[mask]-p[mask])/y[mask]))*100) if mask.any() else np.nan


def _fit_predict_one(train, model_name, steps=1):
    y = np.asarray(train, dtype=float)
    n = len(y)
    if model_name == "SeasonalNaive":
        vals = []
        for h in range(1, steps+1):
            idx = n + h - 1 - 12
            vals.append(y[idx] if idx >= 0 else y[-1])
        return np.array(vals)
    if model_name == "RollingLinear":
        k = min(6, n)
        x = np.arange(k)
        coef = np.polyfit(x, y[-k:], 1)
        return np.array([np.polyval(coef, k+h-1) for h in range(1, steps+1)])
    if model_name == "Ridge":
        if n < 8:
            return _fit_predict_one(train, "RollingLinear", steps)
        # Simple autoregression with month sin/cos proxy
        X=[]; Y=[]
        for i in range(3,n):
            month = (i % 12)+1
            X.append([y[i-1], y[i-2], y[i-3], np.sin(2*np.pi*month/12), np.cos(2*np.pi*month/12)])
            Y.append(y[i])
        model=Ridge(alpha=1.0).fit(X,Y)
        hist=list(y)
        out=[]
        for h in range(steps):
            i=len(hist)
            month=(i%12)+1
            feat=[[hist[-1],hist[-2],hist[-3],np.sin(2*np.pi*month/12),np.cos(2*np.pi*month/12)]]
            v=float(model.predict(feat)[0]); out.append(v); hist.append(v)
        return np.array(out)
    if model_name == "HoltWintersAdd":
        if n < 24:
            return _fit_predict_one(train, "RollingLinear", steps)
        fit=ExponentialSmoothing(y, trend="add", seasonal="add", seasonal_periods=12, initialization_method="estimated").fit(optimized=True)
        return np.asarray(fit.forecast(steps))
    if model_name == "HoltWintersMul":
        if n < 24 or np.any(y<=0):
            return _fit_predict_one(train, "HoltWintersAdd", steps)
        fit=ExponentialSmoothing(y, trend="add", seasonal="mul", seasonal_periods=12, initialization_method="estimated").fit(optimized=True)
        return np.asarray(fit.forecast(steps))
    if model_name == "SARIMA":
        if n < 24:
            return _fit_predict_one(train, "RollingLinear", steps)
        fit=SARIMAX(y, order=(1,1,1), seasonal_order=(1,1,0,12), enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        return np.asarray(fit.forecast(steps))
    raise ValueError(model_name)


def compare_models(series):
    if len(series) < 8:
        return pd.DataFrame()
    y=series["actual"].values.astype(float)
    models=["SeasonalNaive","RollingLinear","Ridge","HoltWintersAdd","HoltWintersMul","SARIMA"]
    rows=[]
    for m in models:
        a1=[];p1=[];a2=[];p2=[]
        # at most last 12 origins for speed
        start=max(6, len(y)-12)
        for i in range(start, len(y)):
            try:
                pr=_fit_predict_one(y[:i],m,steps=1)[0]
                a1.append(y[i]);p1.append(pr)
            except Exception:
                pass
            if i+1 < len(y):
                try:
                    pr2=_fit_predict_one(y[:i],m,steps=2)[1]
                    a2.append(y[i+1]);p2.append(pr2)
                except Exception:
                    pass
        if a1:
            rows.append({
                "model":m,
                "MAPE_1step":_mape(a1,p1),
                "MAE_1step":mean_absolute_error(a1,p1),
                "RMSE_1step":math.sqrt(mean_squared_error(a1,p1)),
                "MAPE_2step":_mape(a2,p2) if a2 else np.nan,
            })
    return pd.DataFrame(rows).sort_values("MAPE_1step")


def compute_error_metrics(actual, pred):
    return {
        "MAPE": _mape(actual,pred),
        "MAE": mean_absolute_error(actual,pred),
        "RMSE": math.sqrt(mean_squared_error(actual,pred)),
    }


def forecast_future(series, horizon=3, outage_days=0.0, outage_impact=0.5):
    s=series.copy()
    y=s["actual"].values.astype(float)
    # Correct last observation for outage as an analytical scenario, not a replacement of actual history
    y_adj=y.copy()
    if outage_days > 0 and len(y_adj):
        days=30.5
        lost_share=min(0.9, outage_days/days*outage_impact)
        if lost_share < 1:
            y_adj[-1]=y_adj[-1]/(1-lost_share)

    res=compare_models(pd.DataFrame({"date":s["date"],"actual":y_adj}))
    if res.empty:
        models=["RollingLinear"]
        weights={"RollingLinear":1.0}
    else:
        good=res.dropna(subset=["MAPE_1step"]).copy()
        good=good[good["MAPE_1step"]>0]
        if good.empty:
            models=["RollingLinear"];weights={"RollingLinear":1.0}
        else:
            good["raw_w"]=1/(good["MAPE_1step"]**2)
            good=good.head(4)
            good["w"]=good["raw_w"]/good["raw_w"].sum()
            models=good["model"].tolist();weights=dict(zip(good["model"],good["w"]))

    preds={}
    for m in models:
        try:
            preds[m]=_fit_predict_one(y_adj,m,horizon)
        except Exception:
            pass
    if not preds:
        preds={"RollingLinear":_fit_predict_one(y_adj,"RollingLinear",horizon)};weights={"RollingLinear":1.0}
    # normalize weights to successful models
    weights={m:weights.get(m,0) for m in preds}
    sw=sum(weights.values()) or 1
    weights={m:w/sw for m,w in weights.items()}
    ens=np.zeros(horizon)
    for m,p in preds.items():
        ens += weights[m]*p

    last_date=pd.to_datetime(s["date"].iloc[-1])
    dates=pd.date_range(last_date+pd.offsets.MonthBegin(1),periods=horizon,freq="MS")
    out=pd.DataFrame({"date":dates,"forecast":ens})
    for m,p in preds.items(): out[m]=p
    return out, weights
