import io
import math
import unicodedata
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def _norm(s):
    s = "" if s is None else str(s).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.replace("_", " ").replace("-", " ").split())


def _find_col(df, aliases, required=False):
    nm = {_norm(c): c for c in df.columns}
    for a in aliases:
        if _norm(a) in nm:
            return nm[_norm(a)]
    if required:
        raise ValueError(f"Thiếu cột bắt buộc. Cần một trong: {', '.join(aliases)}")
    return None


def _parse_date(v):
    if pd.isna(v):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).normalize()
    return pd.to_datetime(v, errors="coerce", dayfirst=True)


def _parse_time(v):
    if pd.isna(v):
        return None
    if isinstance(v, datetime):
        return v.time()
    if hasattr(v, "hour") and hasattr(v, "minute"):
        try:
            return v
        except Exception:
            pass
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # Excel fraction-of-day time
        frac = float(v) % 1
        sec = int(round(frac * 86400)) % 86400
        return (datetime.min + timedelta(seconds=sec)).time()
    txt = str(v).strip()
    for fmt in ["%H:%M:%S", "%H:%M", "%H.%M"]:
        try:
            return datetime.strptime(txt, fmt).time()
        except Exception:
            pass
    parsed = pd.to_datetime(txt, errors="coerce")
    return None if pd.isna(parsed) else parsed.time()


def _duration_hours(date, start, end):
    d = _parse_date(date)
    s = _parse_time(start)
    e = _parse_time(end)
    if pd.isna(d) or s is None or e is None:
        return np.nan
    dt1 = datetime.combine(d.date(), s)
    dt2 = datetime.combine(d.date(), e)
    if dt2 <= dt1:
        dt2 += timedelta(days=1)
    return max(0.0, (dt2 - dt1).total_seconds() / 3600.0)


def parse_outage_workbook(fileobj):
    """Read outage workbook.

    Preferred workbook:
      - Su_co: SU_CO_ID, NGAY, GIO_BAT_DAU, GIO_KET_THUC, ...
      - KH_mat_dien: SU_CO_ID, MA_KHANG, ...
    Also accepts a single flat sheet where each row is one event/customer pair.
    """
    raw = fileobj.getvalue() if hasattr(fileobj, "getvalue") else fileobj
    xls = pd.ExcelFile(io.BytesIO(raw) if isinstance(raw, (bytes, bytearray)) else raw)
    sheets = {s: pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names}

    event_sheet = None
    detail_sheet = None
    for name, d in sheets.items():
        nn = _norm(name)
        if nn in {"su co", "suco", "outages", "outage", "mat dien"}:
            event_sheet = d
        if nn in {"kh mat dien", "khach hang mat dien", "customers", "chi tiet kh", "chi tiet"}:
            detail_sheet = d

    if event_sheet is None:
        # choose first sheet that has date/start/end-like columns
        for d in sheets.values():
            cols = {_norm(c) for c in d.columns}
            if any(x in cols for x in ["ngay", "ngay mat dien", "date"]) and any(x in cols for x in ["gio bat dau", "bat dau", "start"]):
                event_sheet = d
                break
    if event_sheet is None:
        event_sheet = next(iter(sheets.values()))

    ev = event_sheet.copy()
    c_id = _find_col(ev, ["SU_CO_ID", "Mã sự cố", "ID sự cố", "Event ID", "event_id"])
    c_date = _find_col(ev, ["NGAY", "Ngày", "Ngày mất điện", "Date"], required=True)
    c_start = _find_col(ev, ["GIO_BAT_DAU", "Giờ bắt đầu", "Bắt đầu", "Start"], required=True)
    c_end = _find_col(ev, ["GIO_KET_THUC", "Giờ kết thúc", "Kết thúc", "End"], required=True)
    c_tba = _find_col(ev, ["TEN_TBA", "TBA", "Trạm", "Phạm vi TBA"])
    c_scope = _find_col(ev, ["PHAM_VI", "Phạm vi", "Đường dây", "Khu vực"])
    c_reason = _find_col(ev, ["NGUYEN_NHAN", "NGUYEN_NHAN_SAI_SO", "Nguyên nhân", "Nguyên nhân sai số", "Reason"])
    c_impact = _find_col(ev, ["TY_LE_PHU_TAI_ANH_HUONG", "Tỷ lệ phụ tải ảnh hưởng", "% phụ tải ảnh hưởng", "Impact pct"])
    c_note = _find_col(ev, ["GHI_CHU", "Ghi chú", "Note"])
    c_cust = _find_col(ev, ["MA_KHANG", "Mã khách hàng", "Mã KH", "customer_id"])
    c_name = _find_col(ev, ["TEN_KHANG", "Tên khách hàng", "Tên KH", "customer_name"])
    c_kw = _find_col(ev, ["CONG_SUAT_KW", "Công suất kW", "kW"])
    c_kwhh = _find_col(ev, ["KWH_GIO_UOC_TINH", "kWh/giờ ước tính", "kWh giờ", "kwh_per_hour"])
    c_factor = _find_col(ev, ["HE_SO_KHUNG_GIO", "Hệ số khung giờ", "Hệ số phụ tải", "load_factor"])

    out = pd.DataFrame()
    out["event_id"] = ev[c_id].astype(str) if c_id else [f"SC{i+1:03d}" for i in range(len(ev))]
    out["date"] = ev[c_date].map(_parse_date)
    out["start_time"] = ev[c_start]
    out["end_time"] = ev[c_end]
    out["duration_hours"] = [
        _duration_hours(d, s, e) for d, s, e in zip(ev[c_date], ev[c_start], ev[c_end])
    ]
    out["tba"] = ev[c_tba].astype(str) if c_tba else ""
    out["scope"] = ev[c_scope].astype(str) if c_scope else ""
    out["reason"] = ev[c_reason].astype(str) if c_reason else ""
    if c_impact:
        imp = pd.to_numeric(ev[c_impact], errors="coerce")
        # accept 0-1 or 0-100
        imp = np.where(imp > 1.5, imp / 100.0, imp)
        out["impact_ratio"] = pd.Series(imp).clip(0, 1).fillna(1.0)
    else:
        out["impact_ratio"] = 1.0
    out["note"] = ev[c_note].astype(str) if c_note else ""
    out["customer_id"] = ev[c_cust].astype(str) if c_cust else ""
    out["customer_name"] = ev[c_name].astype(str) if c_name else ""
    out["power_kw"] = pd.to_numeric(ev[c_kw], errors="coerce") if c_kw else np.nan
    out["kwh_per_hour_input"] = pd.to_numeric(ev[c_kwhh], errors="coerce") if c_kwhh else np.nan
    out["time_factor"] = pd.to_numeric(ev[c_factor], errors="coerce").fillna(1.0) if c_factor else 1.0

    if detail_sheet is not None:
        det = detail_sheet.copy()
        d_id = _find_col(det, ["SU_CO_ID", "Mã sự cố", "ID sự cố", "Event ID", "event_id"], required=True)
        d_cust = _find_col(det, ["MA_KHANG", "Mã khách hàng", "Mã KH", "customer_id"], required=True)
        d_name = _find_col(det, ["TEN_KHANG", "Tên khách hàng", "Tên KH", "customer_name"])
        d_kw = _find_col(det, ["CONG_SUAT_KW", "Công suất kW", "kW"])
        d_kwhh = _find_col(det, ["KWH_GIO_UOC_TINH", "kWh/giờ ước tính", "kWh giờ", "kwh_per_hour"])
        d_factor = _find_col(det, ["HE_SO_KHUNG_GIO", "Hệ số khung giờ", "Hệ số phụ tải", "load_factor"])
        d_reason = _find_col(det, ["NGUYEN_NHAN_SAI_SO", "Nguyên nhân sai số", "NGUYEN_NHAN", "Nguyên nhân"])
        dd = pd.DataFrame({
            "event_id": det[d_id].astype(str),
            "customer_id": det[d_cust].astype(str),
            "customer_name_detail": det[d_name].astype(str) if d_name else "",
            "error_reason_detail": det[d_reason].astype(str) if d_reason else "",
            "power_kw_detail": pd.to_numeric(det[d_kw], errors="coerce") if d_kw else np.nan,
            "kwh_per_hour_detail": pd.to_numeric(det[d_kwhh], errors="coerce") if d_kwhh else np.nan,
            "time_factor_detail": pd.to_numeric(det[d_factor], errors="coerce").fillna(1.0) if d_factor else 1.0,
        })
        # If detail exists, expand events to affected customers. Flat customer rows in Su_co still work when no detail sheet.
        base = out.drop(columns=["customer_id", "customer_name", "power_kw", "kwh_per_hour_input", "time_factor"])
        out = base.merge(dd, on="event_id", how="left")
        out = out.rename(columns={
            "customer_name_detail": "customer_name",
            "power_kw_detail": "power_kw",
            "kwh_per_hour_detail": "kwh_per_hour_input",
            "time_factor_detail": "time_factor",
        })
        out["customer_id"] = out["customer_id"].fillna("").astype(str)
        out["customer_name"] = out["customer_name"].fillna("").astype(str)
        if "error_reason_detail" in out.columns:
            er = out["error_reason_detail"].fillna("").astype(str)
            out["reason"] = np.where(er.str.strip().ne(""), er, out["reason"])

    out = out.dropna(subset=["date", "duration_hours"]).copy()
    out["duration_hours"] = pd.to_numeric(out["duration_hours"], errors="coerce").fillna(0).clip(lower=0, upper=168)
    out["time_factor"] = pd.to_numeric(out["time_factor"], errors="coerce").fillna(1.0).clip(lower=0, upper=5)
    return out


def _baseline_hourly(customer_long, customer_id, event_date):
    if customer_long is None or customer_long.empty or not customer_id:
        return np.nan
    cid = str(customer_id)
    c = customer_long[customer_long["customer_id"].astype(str) == cid].copy()
    if c.empty:
        return np.nan
    c["date"] = pd.to_datetime(c["date"])
    event_month = pd.Timestamp(event_date).to_period("M").to_timestamp()
    hist = c[c["date"] < event_month].sort_values("date")
    if hist.empty:
        return np.nan

    recent = hist.tail(3).copy()
    if not recent.empty:
        recent["hours"] = recent["date"].dt.days_in_month * 24
        recent_hourly = recent["kwh"].sum() / max(recent["hours"].sum(), 1)
    else:
        recent_hourly = np.nan

    same_prev = c[c["date"] == event_month - pd.DateOffset(years=1)]
    if not same_prev.empty:
        row = same_prev.iloc[-1]
        same_hourly = float(row["kwh"]) / (pd.Timestamp(row["date"]).days_in_month * 24)
    else:
        same_hourly = np.nan

    if np.isfinite(recent_hourly) and np.isfinite(same_hourly):
        return 0.65 * recent_hourly + 0.35 * same_hourly
    if np.isfinite(recent_hourly):
        return recent_hourly
    if np.isfinite(same_hourly):
        return same_hourly
    return np.nan


def estimate_outage_losses(outage_rows, customer_long=None, total_series=None):
    """Estimate unserved energy per outage row.

    Priority: explicit kWh/hour -> explicit kW -> customer historical hourly baseline -> event-level fallback.
    Event-level fallback is only used for rows without customer_id and requires total_series.
    """
    if outage_rows is None or outage_rows.empty:
        empty = pd.DataFrame(columns=["date", "lost_kwh"])
        return outage_rows.copy() if outage_rows is not None else pd.DataFrame(), empty

    d = outage_rows.copy()
    latest_total_by_month = {}
    if total_series is not None and not total_series.empty:
        ts = total_series.copy()
        ts["date"] = pd.to_datetime(ts["date"]).dt.to_period("M").dt.to_timestamp()
        latest_total_by_month = dict(zip(ts["date"], pd.to_numeric(ts["actual"], errors="coerce")))

    baselines = []
    sources = []
    losses = []
    for _, r in d.iterrows():
        kwhh = r.get("kwh_per_hour_input", np.nan)
        pkw = r.get("power_kw", np.nan)
        factor = float(r.get("time_factor", 1.0) or 1.0)
        impact = float(r.get("impact_ratio", 1.0) or 1.0)
        dur = float(r.get("duration_hours", 0.0) or 0.0)
        cid = str(r.get("customer_id", "") or "").strip()
        baseline = np.nan
        source = ""
        if pd.notna(kwhh) and float(kwhh) >= 0:
            baseline = float(kwhh)
            source = "Nhập kWh/giờ"
        elif pd.notna(pkw) and float(pkw) >= 0:
            baseline = float(pkw)
            source = "Công suất kW"
        elif cid and cid.lower() not in {"nan", "none"}:
            baseline = _baseline_hourly(customer_long, cid, r["date"])
            source = "Lịch sử KH" if np.isfinite(baseline) else "Không đủ lịch sử KH"
        else:
            month = pd.Timestamp(r["date"]).to_period("M").to_timestamp()
            total = latest_total_by_month.get(month, np.nan)
            if pd.notna(total) and total > 0:
                baseline = float(total) / (pd.Timestamp(month).days_in_month * 24)
                source = "Tổng phụ tải tháng"
            else:
                source = "Không đủ dữ liệu"

        loss = baseline * dur * factor * impact if np.isfinite(baseline) else np.nan
        baselines.append(baseline)
        sources.append(source)
        losses.append(loss)

    d["baseline_kwh_per_hour"] = baselines
    d["estimate_source"] = sources
    d["lost_kwh"] = losses
    d["month"] = pd.to_datetime(d["date"]).dt.to_period("M").dt.to_timestamp()

    valid = d.dropna(subset=["lost_kwh"]).copy()
    if valid.empty:
        monthly = pd.DataFrame(columns=["date","lost_kwh","outage_hours","affected_customers","event_count"])
    else:
        monthly = valid.groupby("month", as_index=False).agg(
            lost_kwh=("lost_kwh","sum"),
            outage_hours=("duration_hours","sum"),
            affected_customers=("customer_id", lambda x: x.astype(str).replace({"":"nan"}).loc[lambda z: ~z.str.lower().isin(["nan","none"])].nunique()),
            event_count=("event_id","nunique"),
        ).rename(columns={"month":"date"})
    return d, monthly


def normalize_series_for_outages(series, outage_monthly):
    s = series.copy()
    if s.empty:
        return s
    s["date"] = pd.to_datetime(s["date"]).dt.to_period("M").dt.to_timestamp()
    s["actual"] = pd.to_numeric(s["actual"], errors="coerce")
    if outage_monthly is None or outage_monthly.empty:
        s["outage_lost_kwh"] = 0.0
        s["normalized_actual"] = s["actual"]
        return s
    o = outage_monthly.copy()
    o["date"] = pd.to_datetime(o["date"]).dt.to_period("M").dt.to_timestamp()
    s = s.merge(o[["date", "lost_kwh"]], on="date", how="left")
    s["outage_lost_kwh"] = s["lost_kwh"].fillna(0.0)
    s["normalized_actual"] = s["actual"] + s["outage_lost_kwh"]
    return s.drop(columns=["lost_kwh"])
