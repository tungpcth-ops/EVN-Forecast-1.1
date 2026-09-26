import re, math, calendar
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

MONTH_YEAR_RE = re.compile(r"điện\s*năng\s*tháng\s*(\d{1,2})(?:\s*/\s*(\d{4}))?", re.I)

META_ALIASES = {
    "customer_id": ["MA_KHANG","Mã khách hàng","MA_KH","Mã KH"],
    "customer_name": ["TEN_KHANG","Tên khách hàng","TEN_KH","Tên KH"],
    "industry_code": ["MÃ NGÀNH NGHỀ","MA_NN","Mã ngành nghề","MÃ NGÀNH"],
    "industry_name": ["TÊN NGÀNH NGHỀ","TEN_NGANH_NGHE","Tên ngành nghề"],
    "customer_type": ["LOẠI KHÁCH HÀNG","LOAI_KHACH_HANG","LOAI_HDONG","Loại khách hàng"],
    "price_chain": ["CHUOI_GIA","Chuỗi giá"],
}

def _pick(df, aliases):
    return next((x for x in aliases if x in df.columns), None)

def parse_customer_workbook(fileobj, default_year=None):
    """Đọc được cả file gộp 2025-2026 (cột 'Điện năng tháng 1/2025') và file 1 năm."""
    df = pd.read_excel(fileobj)
    idcol = _pick(df, META_ALIASES["customer_id"])
    namecol = _pick(df, META_ALIASES["customer_name"])
    if idcol is None:
        df["_row_id"] = np.arange(len(df)).astype(str); idcol="_row_id"
    if namecol is None: namecol=idcol
    meta_cols={k:_pick(df,v) for k,v in META_ALIASES.items()}
    rows=[]
    for col in df.columns:
        m=MONTH_YEAR_RE.search(str(col))
        if not m: continue
        month=int(m.group(1)); year=int(m.group(2)) if m.group(2) else default_year
        if year is None: continue
        vals=pd.to_numeric(df[col],errors="coerce").fillna(0)
        tmp=pd.DataFrame({
            "customer_id":df[idcol].astype(str),
            "customer_name":df[namecol].astype(str),
            "date":pd.Timestamp(year=year,month=month,day=1),
            "kwh":vals.astype(float),
        })
        for out_key, src in meta_cols.items():
            if out_key in ["customer_id","customer_name"] or src is None: continue
            tmp[out_key]=df[src].fillna("").astype(str)
        rows.append(tmp)
    if not rows:
        raise ValueError("Không tìm thấy cột dạng 'Điện năng tháng 1/2026' hoặc 'Điện năng tháng 1'.")
    out=pd.concat(rows,ignore_index=True)
    return out.sort_values(["date","customer_id"]).reset_index(drop=True)

def aggregate_monthly(customer_long):
    if customer_long is None or customer_long.empty:
        return pd.DataFrame(columns=["date","actual"])
    return customer_long.groupby("date",as_index=False)["kwh"].sum().rename(columns={"kwh":"actual"}).sort_values("date")

def merge_total_history(history, monthly):
    parts=[]
    if history is not None and not history.empty:
        h=history.copy(); d=h.columns[0]; v=h.columns[1]
        h=h[[d,v]]; h.columns=["date","actual"]
        h["date"]=pd.to_datetime(h["date"],errors="coerce",dayfirst=True).dt.to_period("M").dt.to_timestamp()
        h["actual"]=pd.to_numeric(h["actual"],errors="coerce")
        parts.append(h.dropna())
    if monthly is not None and not monthly.empty:
        parts.append(monthly[["date","actual"]].copy())
    if not parts: return pd.DataFrame(columns=["date","actual"])
    x=pd.concat(parts,ignore_index=True).sort_values("date").drop_duplicates("date",keep="last")
    return x[x.actual>0].reset_index(drop=True)

def _mape(a,p):
    a=np.asarray(a,float); p=np.asarray(p,float); mask=a!=0
    return float(np.mean(np.abs((a[mask]-p[mask])/a[mask]))*100) if mask.any() else np.nan

def metrics(a,p):
    if not len(a): return {"MAPE":np.nan,"MAE":np.nan,"RMSE":np.nan}
    return {"MAPE":_mape(a,p),"MAE":float(mean_absolute_error(a,p)),"RMSE":float(math.sqrt(mean_squared_error(a,p)))}

def calendar_features(dates):
    ds=pd.to_datetime(pd.Series(dates))
    rows=[]
    # Số ngày nghỉ lễ chính thức theo tháng; Tết được gán cho giai đoạn thực tế 2025-2026.
    tet_days={(2025,1):5,(2025,2):4,(2026,2):9}
    for d in ds:
        y,m=int(d.year),int(d.month); days=calendar.monthrange(y,m)[1]
        weekends=sum(1 for day in range(1,days+1) if pd.Timestamp(y,m,day).weekday()>=5)
        fixed=0
        if m==1: fixed+=1
        if m==4: fixed+=1
        if m==5: fixed+=1
        if m==9: fixed+=2
        holidays=max(fixed,tet_days.get((y,m),0))
        rows.append({"date":pd.Timestamp(y,m,1),"days_in_month":days,"weekend_days":weekends,
                     "holiday_days":holidays,"work_days":max(0,days-weekends-holidays),
                     "month_sin":np.sin(2*np.pi*m/12),"month_cos":np.cos(2*np.pi*m/12)})
    return pd.DataFrame(rows)

def industry_summary(customer_long, latest_only=True):
    if customer_long is None or customer_long.empty: return pd.DataFrame()
    x=customer_long.copy(); x["date"]=pd.to_datetime(x["date"])
    if latest_only: x=x[x.date==x.date.max()]
    group_cols=[c for c in ["industry_code","industry_name","customer_type"] if c in x.columns]
    if not group_cols: return pd.DataFrame()
    g=x.groupby(group_cols,dropna=False).agg(customers=("customer_id","nunique"),kwh=("kwh","sum")).reset_index()
    total=max(g.kwh.sum(),1); g["share_pct"]=g.kwh/total*100
    return g.sort_values("kwh",ascending=False)

def top100_influence(customer_long, n=100):
    if customer_long is None or customer_long.empty:return pd.DataFrame()
    dates=sorted(pd.to_datetime(customer_long.date).unique()); latest=dates[-1]; prev=dates[-2] if len(dates)>1 else None
    cols=["customer_id","customer_name","kwh"]+[c for c in ["industry_code","industry_name","customer_type"] if c in customer_long.columns]
    a=customer_long[pd.to_datetime(customer_long.date)==latest][cols].copy().rename(columns={"kwh":"latest_kwh"})
    if prev is not None:
        b=customer_long[pd.to_datetime(customer_long.date)==prev][["customer_id","kwh"]].rename(columns={"kwh":"prev_kwh"})
        a=a.merge(b,on="customer_id",how="left")
    else:a["prev_kwh"]=0
    a["prev_kwh"]=a.prev_kwh.fillna(0); a["delta_kwh"]=a.latest_kwh-a.prev_kwh
    a["delta_pct"]=np.where(a.prev_kwh>0,a.delta_kwh/a.prev_kwh*100,np.nan)
    total=max(a.latest_kwh.sum(),1); delta_scale=max(a.delta_kwh.abs().quantile(.99),1)
    a["share_pct"]=a.latest_kwh/total*100
    a["influence_score"]=0.55*(a.latest_kwh/total)+0.45*np.minimum(a.delta_kwh.abs()/delta_scale,1)
    a=a.sort_values("influence_score",ascending=False).head(n).copy(); a.insert(0,"rank",range(1,len(a)+1))
    return a

def forecast_stat_trend(series, horizon=3):
    s=series.sort_values("date"); y=s.actual.astype(float).values; dates=pd.to_datetime(s.date)
    out=[]
    # Adaptive YoY growth from latest comparable 3-6 months, winsorized.
    yoy=[]
    vmap={pd.Timestamp(d).to_period("M"):float(v) for d,v in zip(dates,y)}
    for d,v in zip(dates[-6:],y[-6:]):
        prev=pd.Timestamp(d).to_period("M")-12
        if prev in vmap and vmap[prev]>0: yoy.append(v/vmap[prev]-1)
    g=float(np.clip(np.median(yoy),-0.25,0.35)) if yoy else 0.0
    k=min(6,len(y)); coef=np.polyfit(np.arange(k),y[-k:],1) if k>=2 else [0,y[-1]]
    last=dates.iloc[-1].to_period("M")
    for h in range(1,horizon+1):
        td=last+h; same=td-12
        seasonal=vmap.get(same,np.nan)
        p_yoy=seasonal*(1+g) if np.isfinite(seasonal) else np.nan
        p_trend=float(np.polyval(coef,k+h-1))
        p=0.7*p_yoy+0.3*p_trend if np.isfinite(p_yoy) else p_trend
        out.append(p)
    return np.array(out,float)

def forecast_hw(series,horizon=3):
    y=series.actual.astype(float).values
    if len(y)>=24 and np.all(y>0):
        fit=ExponentialSmoothing(y,trend="add",seasonal="mul",seasonal_periods=12,initialization_method="estimated").fit(optimized=True)
    elif len(y)>=24:
        fit=ExponentialSmoothing(y,trend="add",seasonal="add",seasonal_periods=12,initialization_method="estimated").fit(optimized=True)
    else:
        return forecast_stat_trend(series,horizon)
    return np.asarray(fit.forecast(horizon),float)

def forecast_sarima(series,horizon=3):
    y=series.actual.astype(float).values
    if len(y)<24:return forecast_stat_trend(series,horizon)
    fit=SARIMAX(y,order=(1,1,1),seasonal_order=(1,1,0,12),enforce_stationarity=False,enforce_invertibility=False).fit(disp=False,maxiter=100)
    return np.asarray(fit.forecast(horizon),float)

def make_regression_table(series,weather_monthly=None,outage_monthly=None):
    x=series[["date","actual"]].copy(); x["date"]=pd.to_datetime(x.date).dt.to_period("M").dt.to_timestamp()
    x=x.merge(calendar_features(x.date),on="date",how="left")
    if weather_monthly is not None and not weather_monthly.empty:
        w=weather_monthly.copy(); w["date"]=pd.to_datetime(w.date).dt.to_period("M").dt.to_timestamp(); x=x.merge(w,on="date",how="left")
    if outage_monthly is not None and not outage_monthly.empty:
        o=outage_monthly.copy(); o["date"]=pd.to_datetime(o.date).dt.to_period("M").dt.to_timestamp()
        keep=[c for c in ["date","lost_kwh","outage_hours","affected_customers"] if c in o.columns]
        x=x.merge(o[keep],on="date",how="left")
    for c in ["temp_avg","temp_max","hot35","hot37","rain_mm","rain_days","sunshine_h","lost_kwh","outage_hours","affected_customers"]:
        if c not in x:x[c]=0.0
        x[c]=pd.to_numeric(x[c],errors="coerce").fillna(0)
    x["lag1"]=x.actual.shift(1); x["lag2"]=x.actual.shift(2); x["lag12"]=x.actual.shift(12)
    return x

REG_FEATURES=["lag1","lag2","lag12","temp_avg","temp_max","hot35","rain_mm","rain_days","days_in_month","work_days","holiday_days","outage_hours","affected_customers","month_sin","month_cos"]

def forecast_multivariate(series, hist_weather_monthly, future_weather_monthly, outage_monthly=None, future_outage=None, horizon=3):
    x=make_regression_table(series,hist_weather_monthly,outage_monthly).dropna(subset=["lag1","lag2"]).copy()
    if len(x)<10:return forecast_stat_trend(series,horizon)
    feats=[c for c in REG_FEATURES if c in x.columns and not (c=="lag12" and x[c].isna().all())]
    # median-fill lag12 in short histories
    for c in feats:x[c]=x[c].fillna(x[c].median() if x[c].notna().any() else 0)
    model=make_pipeline(StandardScaler(),Ridge(alpha=2.0)).fit(x[feats],x.actual)
    hist=list(series.actual.astype(float).values); last=pd.to_datetime(series.date).iloc[-1].to_period("M")
    fw=future_weather_monthly.copy() if future_weather_monthly is not None else pd.DataFrame()
    if not fw.empty:fw["date"]=pd.to_datetime(fw.date).dt.to_period("M").dt.to_timestamp()
    fo=future_outage.copy() if future_outage is not None else pd.DataFrame()
    if not fo.empty:fo["date"]=pd.to_datetime(fo.date).dt.to_period("M").dt.to_timestamp()
    preds=[]
    for h in range(1,horizon+1):
        d=(last+h).to_timestamp(); row=calendar_features([d]).iloc[0].to_dict()
        row.update({"date":d,"lag1":hist[-1],"lag2":hist[-2] if len(hist)>1 else hist[-1],"lag12":hist[-12] if len(hist)>=12 else np.nan})
        if not fw.empty:
            z=fw[fw.date==d]
            if not z.empty: row.update(z.iloc[0].to_dict())
        row.setdefault("outage_hours",0);row.setdefault("affected_customers",0);row.setdefault("lost_kwh",0)
        if not fo.empty:
            z=fo[fo.date==d]
            if not z.empty:row.update(z.iloc[0].to_dict())
        vals=[]
        for c in feats:
            v=row.get(c,0)
            if pd.isna(v):v=x[c].median() if x[c].notna().any() else 0
            vals.append(float(v))
        p=float(model.predict(pd.DataFrame([vals],columns=feats))[0]); preds.append(max(0,p));hist.append(max(0,p))
    return np.array(preds)

def _customer_forecast_at_origin(hist, target_date):
    # hist contains customer rows strictly before target_date
    if hist.empty:return 0.0
    td=pd.Timestamp(target_date).to_period("M").to_timestamp(); prev=td-pd.DateOffset(years=1)
    latest_date=hist.date.max(); latest=hist[hist.date==latest_date][["customer_id","kwh"]].rename(columns={"kwh":"latest"})
    same=hist[hist.date==prev][["customer_id","kwh"]].rename(columns={"kwh":"same_year"})
    # customer-specific recent growth, capped; fall back aggregate YoY growth
    piv=hist.pivot_table(index="customer_id",columns="date",values="kwh",aggfunc="sum",fill_value=0)
    growth=[]
    dates=sorted(hist.date.unique())[-3:]
    for d in dates:
        py=pd.Timestamp(d)-pd.DateOffset(years=1)
        if py in piv.columns and d in piv.columns:
            den=piv[py].replace(0,np.nan); ratio=(piv[d]/den).replace([np.inf,-np.inf],np.nan)-1
            growth.append(ratio)
    if growth:
        g=pd.concat(growth,axis=1).median(axis=1).clip(-0.35,0.50)
    else:g=pd.Series(dtype=float)
    ids=set(latest.customer_id)|set(same.customer_id)
    agg_yoy=[]
    for d in dates:
        py=pd.Timestamp(d)-pd.DateOffset(years=1)
        a=hist[hist.date==d].kwh.sum();b=hist[hist.date==py].kwh.sum()
        if b>0:agg_yoy.append(a/b-1)
    fallback_g=float(np.clip(np.median(agg_yoy),-0.25,0.35)) if agg_yoy else 0
    same_map=dict(zip(same.customer_id,same.same_year)); latest_map=dict(zip(latest.customer_id,latest.latest))
    total=0
    for cid in ids:
        base=same_map.get(cid,np.nan); gg=float(g.get(cid,fallback_g)) if len(g) else fallback_g
        if np.isfinite(base) and base>0:pred=base*(1+gg)
        else:pred=latest_map.get(cid,0)
        total+=max(0,float(pred))
    return total

def forecast_bottom_up(customer_long, horizon=3):
    if customer_long is None or customer_long.empty:return np.array([np.nan]*horizon)
    x=customer_long.copy();x["date"]=pd.to_datetime(x.date).dt.to_period("M").dt.to_timestamp()
    last=x.date.max().to_period("M"); preds=[]; hist=x.copy()
    for h in range(1,horizon+1):
        td=(last+h).to_timestamp();p=_customer_forecast_at_origin(hist,td);preds.append(p)
        # For recursive months, append pseudo rows proportionally to latest month to preserve structure.
        latest=hist[hist.date==hist.date.max()].copy(); denom=max(latest.kwh.sum(),1);latest["kwh"]=latest.kwh/denom*p;latest["date"]=td;hist=pd.concat([hist,latest],ignore_index=True)
    return np.array(preds,float)

def backtest_five_models(series, customer_long=None, weather_monthly=None, outage_monthly=None, max_origins=10):
    s=series.sort_values("date").reset_index(drop=True); dates=pd.to_datetime(s.date); rows=[]
    models=["Thống kê & tăng trưởng","Holt-Winters","SARIMA","Hồi quy đa biến","Bottom-up KH"]
    store={m:{"a":[],"p":[]} for m in models}
    start=max(8,len(s)-max_origins)
    for i in range(start,len(s)):
        train=s.iloc[:i].copy(); td=dates.iloc[i]; actual=float(s.actual.iloc[i])
        if len(train)<6:continue
        funcs={
            "Thống kê & tăng trưởng":lambda:forecast_stat_trend(train,1)[0],
            "Holt-Winters":lambda:forecast_hw(train,1)[0],
            "SARIMA":lambda:forecast_sarima(train,1)[0],
        }
        for name,fn in funcs.items():
            try: p=float(fn());store[name]["a"].append(actual);store[name]["p"].append(p)
            except Exception:pass
        try:
            hw=weather_monthly[weather_monthly.date<=td] if weather_monthly is not None and not weather_monthly.empty else pd.DataFrame()
            futw=weather_monthly[weather_monthly.date==td] if weather_monthly is not None and not weather_monthly.empty else pd.DataFrame()
            oo=outage_monthly[outage_monthly.date<td] if outage_monthly is not None and not outage_monthly.empty else pd.DataFrame()
            fo=outage_monthly[outage_monthly.date==td] if outage_monthly is not None and not outage_monthly.empty else pd.DataFrame()
            p=float(forecast_multivariate(train,hw,futw,oo,fo,1)[0]);store["Hồi quy đa biến"]["a"].append(actual);store["Hồi quy đa biến"]["p"].append(p)
        except Exception:pass
        try:
            ch=customer_long[pd.to_datetime(customer_long.date)<td].copy() if customer_long is not None else pd.DataFrame()
            if not ch.empty:
                p=float(_customer_forecast_at_origin(ch,td));store["Bottom-up KH"]["a"].append(actual);store["Bottom-up KH"]["p"].append(p)
        except Exception:pass
    for m in models:
        met=metrics(store[m]["a"],store[m]["p"]);rows.append({"model":m,"n_test":len(store[m]["a"]),**met})
    out=pd.DataFrame(rows);return out.sort_values(["MAPE","RMSE"],na_position="last").reset_index(drop=True)

def adaptive_weights(backtest):
    b=backtest.dropna(subset=["MAPE"]).copy();b=b[b.n_test>=2]
    if b.empty:return {}
    # Robust inverse-error weighting; small floor prevents one model dominating.
    e=np.maximum(b.MAPE.values,0.75); raw=1/(e**2); raw=raw/raw.sum()
    return dict(zip(b.model,raw))

def forecast_all(series, customer_long, hist_weather_monthly, future_weather_monthly, outage_monthly=None, future_outage=None, horizon=3, backtest=None):
    preds={}
    for n,fn in [
        ("Thống kê & tăng trưởng",lambda:forecast_stat_trend(series,horizon)),
        ("Holt-Winters",lambda:forecast_hw(series,horizon)),
        ("SARIMA",lambda:forecast_sarima(series,horizon)),
        ("Hồi quy đa biến",lambda:forecast_multivariate(series,hist_weather_monthly,future_weather_monthly,outage_monthly,future_outage,horizon)),
        ("Bottom-up KH",lambda:forecast_bottom_up(customer_long,horizon)),
    ]:
        try:preds[n]=np.asarray(fn(),float)
        except Exception:preds[n]=np.repeat(np.nan,horizon)
    if backtest is None:backtest=backtest_five_models(series,customer_long,hist_weather_monthly,outage_monthly)
    w=adaptive_weights(backtest)
    dates=[(pd.to_datetime(series.date).iloc[-1].to_period("M")+h).to_timestamp() for h in range(1,horizon+1)]
    rows=[]
    for j,d in enumerate(dates):
        row={"date":d}
        valid=[]
        for m,a in preds.items():
            row[m]=float(a[j]) if j<len(a) and np.isfinite(a[j]) else np.nan
            if np.isfinite(row[m]) and m in w:valid.append((m,row[m]))
        if valid:
            sw=sum(w[m] for m,_ in valid); row["Ensemble"]=sum(v*w[m] for m,v in valid)/sw
        else:
            vv=[v for m,v in [(k,row[k]) for k in preds] if np.isfinite(v)];row["Ensemble"]=float(np.mean(vv)) if vv else np.nan
        rows.append(row)
    return pd.DataFrame(rows),w
