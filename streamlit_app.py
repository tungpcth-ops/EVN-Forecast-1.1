import io, os, calendar
from datetime import date, datetime, timedelta
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from multi_model_engine import (
    parse_customer_workbook, aggregate_monthly, merge_total_history,
    top100_influence, industry_summary, backtest_five_models,
    forecast_all, adaptive_weights, calendar_features
)
from outage_engine import (parse_outage_workbook, estimate_outage_losses, normalize_series_for_outages,
                           auto_impact_ratio_by_consumption)
from weather_engine import fetch_history, fetch_forecast, apply_overrides, monthly_features, future_month_features
from state_manager import load_state, save_state, state_to_bytes, merge_uploaded_state
from prompt_engine import build_chatgpt_prompt
from data_store import (load_customer_history, save_customer_history, merge_customer_history,
                        load_total_history, save_total_history, load_meta, clear_store,
                        backup_bundle_bytes, restore_bundle, load_outage_history, save_outage_history,
                        merge_outage_history, delete_outage_records)

st.set_page_config(page_title="EVN Forecast 1.5.3",page_icon="⚡",layout="wide")

WEATHER_LOCATION_NAME="Xã Thường Xuân, tỉnh Thanh Hóa"
WEATHER_LAT=19.90389
WEATHER_LON=105.34889

st.markdown("""
<style>
.block-container{padding-top:1.1rem;padding-bottom:2rem}.kpi{border:1px solid #d9e2f2;border-radius:14px;padding:14px 16px;background:linear-gradient(135deg,#f8fbff,#eef5ff)}
.kpi .v{font-size:1.55rem;font-weight:800}.kpi .s{color:#667085;font-size:.84rem}.note{padding:12px 14px;border-radius:12px;background:#fff8e6;border-left:5px solid #f59e0b}.ok{padding:12px 14px;border-radius:12px;background:#ecfdf3;border-left:5px solid #10b981}
</style>""",unsafe_allow_html=True)

def kpi(label,value,sub=""):
    st.markdown(f'<div class="kpi"><div class="s">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>',unsafe_allow_html=True)
def fmt(x):
    try:return f"{float(x):,.0f}".replace(",",".")
    except:return "-"

@st.cache_data(ttl=3600,show_spinner=False)
def load_weather_history(start,end): return fetch_history(WEATHER_LAT,WEATHER_LON,start,end)
@st.cache_data(ttl=1800,show_spinner=False)
def load_weather_forecast(): return fetch_forecast(WEATHER_LAT,WEATHER_LON,16)

if "model_state" not in st.session_state:
    st.session_state.model_state=load_state()

st.sidebar.title("⚡ EVN Forecast 1.5.3")
st.sidebar.caption("Multi-Model • Back-test • Weather • Bottom-up • Outage • Trợ lý ChatGPT không API")
state_upload=st.sidebar.file_uploader("Khôi phục Model State (.json)",type=["json"])
if state_upload:
    try:
        st.session_state.model_state=merge_uploaded_state(state_upload.getvalue());st.sidebar.success("Đã khôi phục Model State")
    except Exception as e:st.sidebar.error(str(e))

st.sidebar.subheader("1) 📚 Dữ liệu nền")
stored_meta=load_meta()
stored_customer=load_customer_history()
has_store=not stored_customer.empty
if has_store:
    latest_store=pd.to_datetime(stored_customer["date"]).max().strftime("%m/%Y")
    first_store=pd.to_datetime(stored_customer["date"]).min().strftime("%m/%Y")
    st.sidebar.success(f"Đã lưu dữ liệu nền {first_store} → {latest_store} • {stored_customer.customer_id.nunique():,} KH")
else:
    st.sidebar.warning("Chưa có dữ liệu nền. Chỉ cần nạp file gộp 2025–2026 một lần.")

with st.sidebar.expander("Nạp/Thay dữ liệu nền", expanded=not has_store):
    combined=st.file_uploader("File điện năng gộp 2025–2026 (nạp 1 lần)",type=["xlsx","xls"],key="combined")
    f2025=st.file_uploader("Hoặc file riêng năm 2025",type=["xlsx","xls"],key="f2025")
    f2026=st.file_uploader("Hoặc file riêng năm 2026",type=["xlsx","xls"],key="f2026")
    history_file=st.file_uploader("Lịch sử ĐTP tổng 2022–2024 (tùy chọn)",type=["xlsx","csv"],key="hist")
    if st.button("💾 Lưu dữ liệu nền",use_container_width=True):
        init_frames=[]
        try:
            if combined is not None: init_frames.append(parse_customer_workbook(combined))
            if f2025 is not None: init_frames.append(parse_customer_workbook(f2025,2025))
            if f2026 is not None: init_frames.append(parse_customer_workbook(f2026,2026))
            if init_frames:
                base=pd.concat(init_frames,ignore_index=True).drop_duplicates(["customer_id","date"],keep="last")
                save_customer_history(base)
                if history_file is not None:
                    h=pd.read_csv(history_file) if history_file.name.lower().endswith(".csv") else pd.read_excel(history_file)
                    save_total_history(h)
                st.success("Đã lưu dữ liệu nền. Từ tháng sau chỉ cần mục Cập nhật tháng mới.")
                st.rerun()
            else:
                st.warning("Hãy chọn ít nhất một file dữ liệu nền.")
        except Exception as e: st.error(f"Không lưu được dữ liệu nền: {e}")

st.sidebar.subheader("1B) ➕ Cập nhật tháng mới")
new_month_file=st.sidebar.file_uploader("File điện năng của tháng mới",type=["xlsx","xls"],key="new_month")
if st.sidebar.button("➕ Cập nhật vào lịch sử",use_container_width=True,disabled=new_month_file is None):
    try:
        new_df=parse_customer_workbook(new_month_file)
        old_df=load_customer_history()
        merged_df=merge_customer_history(old_df,new_df)
        if merged_df.empty: raise ValueError("File tháng mới không có dữ liệu hợp lệ")
        old_latest=pd.to_datetime(old_df.date).max() if not old_df.empty else None
        new_latest=pd.to_datetime(new_df.date).max()
        save_customer_history(merged_df)
        st.session_state.model_state.setdefault("events",[]).append({
            "time":datetime.now().isoformat(timespec="seconds"),
            "type":"monthly_update",
            "from_latest":str(old_latest.date()) if old_latest is not None else None,
            "new_latest":str(new_latest.date()),
            "rows_received":int(len(new_df))
        })
        save_state(st.session_state.model_state)
        st.sidebar.success(f"Đã cập nhật đến {new_latest.strftime('%m/%Y')}. Mô hình sẽ học lại sai số tự động.")
        st.rerun()
    except Exception as e: st.sidebar.error(f"Lỗi cập nhật tháng mới: {e}")

st.sidebar.caption("Sau lần nạp nền đầu tiên, các tháng sau chỉ tải file tháng mới. Dữ liệu trùng Mã KH + tháng sẽ lấy bản mới nhất.")
with st.sidebar.expander("Sao lưu / Khôi phục dữ liệu"):
    st.download_button("⬇️ Tải gói sao lưu dữ liệu",backup_bundle_bytes(),"EVN_Forecast_Data_Backup.zip","application/zip",use_container_width=True)
    restore_file=st.file_uploader("Khôi phục từ gói sao lưu (.zip)",type=["zip"],key="restore_bundle")
    if restore_file is not None and st.button("♻️ Khôi phục dữ liệu",use_container_width=True):
        try:
            restore_bundle(restore_file.getvalue())
            st.session_state.model_state=load_state()
            st.success("Đã khôi phục dữ liệu và Model State")
            st.rerun()
        except Exception as e: st.error(str(e))

st.sidebar.subheader("2) Mất điện / nguyên nhân sai số")
try:
    tpl=open("Mau_Nhat_ky_mat_dien.xlsx","rb").read();st.sidebar.download_button("⬇️ Mẫu nhật ký mất điện",tpl,"Mau_Nhat_ky_mat_dien.xlsx",use_container_width=True)
except:pass
outage_file=st.sidebar.file_uploader("Upload nhật ký mất điện",type=["xlsx"],key="outage")
st.sidebar.caption("Nhật ký được lưu vết. Tỷ lệ phụ tải ảnh hưởng được app tự tính theo sản lượng KH bị mất điện / tổng sản lượng cùng tháng.")
if outage_file is not None and st.sidebar.button("💾 Lưu/Cập nhật nhật ký mất điện", use_container_width=True):
    try:
        parsed_outage=parse_outage_workbook(outage_file)
        parsed_outage["source"]="Upload Excel"
        parsed_outage["saved_at"]=datetime.now().isoformat(timespec="seconds")
        parsed_outage=auto_impact_ratio_by_consumption(parsed_outage, load_customer_history())
        saved=merge_outage_history(load_outage_history(), parsed_outage)
        save_outage_history(saved)
        st.session_state.model_state.setdefault("events",[]).append({
            "time":datetime.now().isoformat(timespec="seconds"),"type":"outage_log_update",
            "rows_received":int(len(parsed_outage)),"rows_stored":int(len(saved))})
        save_state(st.session_state.model_state)
        st.sidebar.success(f"Đã lưu {len(parsed_outage)} dòng nhật ký. Tổng đang lưu: {len(saved)} dòng.")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Không lưu được nhật ký mất điện: {e}")
st.sidebar.caption("Có thể nhập nhanh Ngày, giờ bắt đầu/kết thúc, Mã KH, nguyên nhân sai số trong phần ⚡ bên dưới.")

st.sidebar.subheader("3) Dự báo")
horizon=st.sidebar.selectbox("Số tháng dự báo",[1,3,6,12],index=1)
use_normalized=st.sidebar.checkbox("Chuẩn hóa lịch sử do mất điện",value=True)

st.sidebar.subheader("4) Thời tiết")
st.sidebar.text_input("Địa điểm",WEATHER_LOCATION_NAME,disabled=True)
st.sidebar.caption(f"Khóa tọa độ {WEATHER_LAT:.5f}, {WEATHER_LON:.5f}")

st.title("⚡ EVN Forecast 1.5.3 – Điện lực Thường Xuân")
st.caption("5 nhánh đối chiếu: Thống kê/tăng trưởng • Holt-Winters • SARIMA • Hồi quy đa biến • Bottom-up khách hàng")

with st.expander("⚡ Nhập nhanh mất điện / nguyên nhân sai số", expanded=False):
    st.caption("Mỗi lần lưu sẽ ghi vết vào nhật ký. Không cần nhập tỷ lệ ảnh hưởng; app tự tính theo tỷ trọng sản lượng của các KH bị ảnh hưởng.")
    manual_default=pd.DataFrame(columns=["Mã sự cố","Ngày","Giờ bắt đầu","Giờ kết thúc","Mã KH","Nguyên nhân sai số"])
    manual=st.data_editor(manual_default,num_rows="dynamic",use_container_width=True,key="manual_outages_top")
    save_manual=st.button("💾 Lưu nhập nhanh vào nhật ký", use_container_width=True, key="save_manual_outages")

def manual_to_outage(df):
    if df is None or df.empty:return pd.DataFrame()
    out=[]
    for i,r in df.iterrows():
        d=pd.to_datetime(r.get("Ngày"),errors="coerce",dayfirst=True)
        if pd.isna(d):continue
        def ptime(v):
            if pd.isna(v) or str(v).strip()=="":return None
            z=pd.to_datetime(str(v),errors="coerce")
            return None if pd.isna(z) else z.time()
        a=ptime(r.get("Giờ bắt đầu"));b=ptime(r.get("Giờ kết thúc"))
        if a is None or b is None:continue
        dt1=datetime.combine(d.date(),a);dt2=datetime.combine(d.date(),b)
        if dt2<=dt1:dt2+=timedelta(days=1)
        dur=(dt2-dt1).total_seconds()/3600
        eid=str(r.get("Mã sự cố","") or "").strip() or f"MANUAL-{d.strftime('%Y%m%d')}-{i+1}"
        out.append({"event_id":eid,"date":d.normalize(),"start_time":a,"end_time":b,"duration_hours":dur,"tba":"","scope":"","reason":str(r.get("Nguyên nhân sai số","") or ""),"impact_ratio":1.0,"note":"Nhập trực tiếp","customer_id":str(r.get("Mã KH","") or ""),"customer_name":"","power_kw":np.nan,"kwh_per_hour_input":np.nan,"time_factor":1.0,"source":"Nhập nhanh","saved_at":datetime.now().isoformat(timespec="seconds")})
    return pd.DataFrame(out)

if save_manual:
    try:
        mr=manual_to_outage(manual)
        if mr.empty:
            st.warning("Chưa có dòng nhập nhanh hợp lệ để lưu.")
        else:
            mr=auto_impact_ratio_by_consumption(mr, load_customer_history())
            saved=merge_outage_history(load_outage_history(), mr)
            save_outage_history(saved)
            st.session_state.model_state.setdefault("events",[]).append({"time":datetime.now().isoformat(timespec="seconds"),"type":"outage_manual_update","rows_received":int(len(mr))})
            save_state(st.session_state.model_state)
            st.success(f"Đã lưu {len(mr)} dòng vào nhật ký mất điện.")
            st.rerun()
    except Exception as e:
        st.error(f"Không lưu được nhập nhanh: {e}")

# -------- data --------
# Dữ liệu khách hàng được đọc từ kho đã lưu. File tháng mới chỉ dùng để cập nhật kho qua nút ở sidebar.
customer_long=load_customer_history()
monthly=aggregate_monthly(customer_long)
history=load_total_history()
series_actual=merge_total_history(history if not history.empty else None,monthly)
if series_actual.empty:
    st.info("Chưa có dữ liệu nền. Mở mục 📚 Dữ liệu nền ở thanh bên và nạp file gộp 2025–2026 một lần.")
    st.stop()

# -------- outages: dùng nhật ký đã lưu vết --------
outage_rows=load_outage_history(); outage_details=pd.DataFrame(); outage_monthly=pd.DataFrame()
if not outage_rows.empty:
    # luôn tính lại tỷ lệ ảnh hưởng theo sản lượng đang có trong kho dữ liệu
    outage_rows=auto_impact_ratio_by_consumption(outage_rows, customer_long)

# -------- weather --------
weather_error=None
try:
    start=max(pd.Timestamp("2022-01-01"),pd.to_datetime(series_actual.date).min()-pd.DateOffset(months=2))
    hist_daily=load_weather_history(start.strftime("%Y-%m-%d"),(date.today()-timedelta(days=1)).strftime("%Y-%m-%d"))
    fc_daily=load_weather_forecast()
    overrides=st.session_state.model_state.get("weather_overrides",[])
    fc_daily=apply_overrides(fc_daily,overrides)
    hist_weather=monthly_features(hist_daily)
    fut_weather=future_month_features(hist_daily,fc_daily,series_actual.date.iloc[-1],horizon=horizon)
except Exception as e:
    weather_error=str(e);hist_daily=pd.DataFrame();fc_daily=pd.DataFrame();hist_weather=pd.DataFrame();fut_weather=pd.DataFrame()

if not outage_rows.empty:
    outage_details,outage_monthly=estimate_outage_losses(outage_rows,customer_long,series_actual)
series_norm=normalize_series_for_outages(series_actual,outage_monthly)
model_series=series_norm[["date","normalized_actual"]].rename(columns={"normalized_actual":"actual"}) if use_normalized else series_actual.copy()

# -------- forecast history & error comparison --------
def _month_key(v):
    return pd.to_datetime(v).to_period("M").to_timestamp()

def record_forecasts_to_state(state, forecast_df, weights, source_latest_month=None):
    hist=list(state.get("forecast_history",[]))
    now=datetime.now().isoformat(timespec="seconds")
    existing={(str(x.get("target_month")), str(x.get("model")), str(x.get("run_month"))) for x in hist}
    if source_latest_month is None:
        source_latest_month=pd.Timestamp.today().to_period("M").to_timestamp()
    run_month=str(pd.to_datetime(source_latest_month).to_period("M"))
    for _,r in forecast_df.iterrows():
        tm=str(pd.to_datetime(r["date"]).to_period("M"))
        for c in [x for x in forecast_df.columns if x!="date"]:
            v=r.get(c)
            if pd.isna(v): continue
            key=(tm,str(c),run_month)
            if key in existing: continue
            hist.append({"run_month":run_month,"created_at":now,"target_month":tm,"model":str(c),"forecast_kwh":float(v),"weight":float(weights.get(c,0)) if c!="Ensemble" else 1.0})
            existing.add(key)
    state["forecast_history"]=hist
    return state

def build_error_report(state, series_actual):
    fh=pd.DataFrame(state.get("forecast_history",[]))
    if fh.empty:return pd.DataFrame(),pd.DataFrame()
    fh["target_month"]=pd.to_datetime(fh["target_month"],errors="coerce").dt.to_period("M").dt.to_timestamp()
    act=series_actual[["date","actual"]].copy();act["date"]=pd.to_datetime(act.date).dt.to_period("M").dt.to_timestamp()
    # Ưu tiên snapshot 1 bước: dự báo được tạo khi tháng thực tế mới nhất là tháng liền trước tháng mục tiêu.
    fh["run_month_dt"]=pd.to_datetime(fh["run_month"],errors="coerce").dt.to_period("M").dt.to_timestamp()
    fh["is_one_step"]=(fh["run_month_dt"]==(fh["target_month"]-pd.DateOffset(months=1)))
    if "created_at" in fh.columns:
        fh=fh.sort_values(["is_one_step","created_at"],ascending=[False,True]).drop_duplicates(["target_month","model"],keep="last")
    d=fh.merge(act,left_on="target_month",right_on="date",how="inner").drop(columns=["date"])
    if d.empty:return d,pd.DataFrame()
    d["sai_lech_kWh"]=d.actual-d.forecast_kwh
    d["sai_lech_tuyet_doi_kWh"]=d.sai_lech_kWh.abs()
    d["sai_so_pct"]=np.where(d.actual!=0,d.sai_lech_tuyet_doi_kWh/d.actual*100,np.nan)
    d["bias_pct"]=np.where(d.actual!=0,d.sai_lech_kWh/d.actual*100,np.nan)
    rows=[]
    for m,g in d.groupby("model"):
        a=g.actual.values.astype(float);p=g.forecast_kwh.values.astype(float)
        err=a-p
        rows.append({"Mô hình":m,"Số kỳ":len(g),"MAPE %":np.nanmean(np.abs(err/a)*100) if np.all(a!=0) else np.nan,"MAE kWh":np.nanmean(np.abs(err)),"RMSE kWh":float(np.sqrt(np.nanmean(err**2))),"Bias kWh":np.nanmean(err),"Bias %":np.nanmean(err/a*100) if np.all(a!=0) else np.nan})
    sm=pd.DataFrame(rows).sort_values(["MAPE %","RMSE kWh"],na_position="last")
    return d.sort_values(["target_month","model"],ascending=[False,True]),sm

# -------- models --------
backtest=backtest_five_models(model_series,customer_long,hist_weather,outage_monthly,max_origins=10)
forecast_df,weights=forecast_all(model_series,customer_long,hist_weather,fut_weather,outage_monthly,None,horizon,backtest)
top100=top100_influence(customer_long,100)

# Tự lưu snapshot dự báo theo tháng dữ liệu mới nhất. Khi tháng sau có thực tế, app tự đối chiếu sai số.
_source_latest=pd.to_datetime(series_actual.date).max().to_period("M").to_timestamp()
_before_count=len(st.session_state.model_state.get("forecast_history",[]))
st.session_state.model_state=record_forecasts_to_state(st.session_state.model_state,forecast_df,weights,_source_latest)
_after_count=len(st.session_state.model_state.get("forecast_history",[]))
if _after_count>_before_count:
    save_state(st.session_state.model_state)

latest=series_norm.iloc[-1]
best=backtest.iloc[0] if not backtest.empty else None
c1,c2,c3,c4,c5=st.columns(5)
with c1:kpi("Tháng mới nhất",pd.to_datetime(latest.date).strftime("%m/%Y"))
with c2:kpi("Thực tế",fmt(latest.actual)+" kWh")
with c3:kpi("Ước mất do mất điện",fmt(latest.get("outage_lost_kwh",0))+" kWh")
with c4:kpi("Dự báo tháng kế",fmt(forecast_df.Ensemble.iloc[0])+" kWh" if not forecast_df.empty else "-")
with c5:kpi("MAPE tốt nhất",f"{best.MAPE:.2f}%" if best is not None and pd.notna(best.MAPE) else "-",str(best.model) if best is not None else "")

if best is not None and pd.notna(best.MAPE) and best.MAPE>1.5:
    st.markdown(f'<div class="note"><b>⚠️ MAPE kiểm định tốt nhất hiện {best.MAPE:.2f}%</b> – chưa đạt mục tiêu 1,5%. Hệ thống vẫn chọn trọng số theo back-test và hiển thị nguyên nhân để tiếp tục hiệu chỉnh.</div>',unsafe_allow_html=True)

# -------- tabs --------
t1,t2,t3,t4,t5,t6,t7,t8,t9,t10=st.tabs(["📊 Tổng quan","📈 5 mô hình","🌦️ Thời tiết","👥 Khách hàng","⚡ Mất điện","🔮 Dự báo","🎯 Đối chiếu sai số","🤖 Trợ lý ChatGPT","💾 Model State","📤 Xuất dữ liệu"])

with t1:
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=series_norm.date,y=series_norm.actual,mode="lines+markers",name="Thực tế"))
    if series_norm.outage_lost_kwh.sum()>0: fig.add_trace(go.Scatter(x=series_norm.date,y=series_norm.normalized_actual,mode="lines+markers",name="Chuẩn hóa mất điện",line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=forecast_df.date,y=forecast_df.Ensemble,mode="lines+markers",name="Adaptive Ensemble",line=dict(dash="dash")))
    fig.update_layout(title="Điện thương phẩm – thực tế, chuẩn hóa và dự báo",yaxis_title="kWh",hovermode="x unified",height=460)
    st.plotly_chart(fig,use_container_width=True)
    if weights:
        wdf=pd.DataFrame({"Mô hình":weights.keys(),"Trọng số":weights.values()}).sort_values("Trọng số",ascending=False)
        st.subheader("Trọng số tự động theo sai số back-test")
        st.bar_chart(wdf.set_index("Mô hình"))

with t2:
    st.subheader("Đối chiếu 5 nhánh mô hình")
    st.dataframe(backtest.style.format({"MAPE":"{:.2f}%","MAE":"{:,.0f}","RMSE":"{:,.0f}"}),use_container_width=True,hide_index=True)
    st.caption("Trọng số Ensemble ∝ 1/MAPE²; mô hình có sai số thấp hơn được trọng số cao hơn. Back-test dùng các tháng thực tế gần nhất và chỉ sử dụng dữ liệu có trước tháng cần kiểm định.")
    if not forecast_df.empty:
        disp=forecast_df.copy();disp.date=pd.to_datetime(disp.date).dt.strftime("%m/%Y")
        st.subheader("Kết quả dự báo từng mô hình")
        st.dataframe(disp.style.format({c:"{:,.0f}" for c in disp.columns if c!="date"}),use_container_width=True,hide_index=True)
        long=forecast_df.melt("date",var_name="Mô hình",value_name="kWh")
        st.plotly_chart(px.line(long,x="date",y="kWh",color="Mô hình",markers=True,title="So sánh dự báo giữa các nhánh"),use_container_width=True)

with t3:
    st.subheader(f"Thời tiết theo ngày – {WEATHER_LOCATION_NAME}")
    if weather_error: st.warning(weather_error)
    elif not fc_daily.empty:
        dmin=pd.to_datetime(fc_daily.date).min().date();dmax=pd.to_datetime(fc_daily.date).max().date()
        rg=st.date_input("Chọn ngày/khoảng ngày",value=(dmin,dmax),min_value=dmin,max_value=dmax)
        if isinstance(rg,tuple) and len(rg)==2: mask=(pd.to_datetime(fc_daily.date).dt.date>=rg[0])&(pd.to_datetime(fc_daily.date).dt.date<=rg[1])
        else: mask=pd.to_datetime(fc_daily.date).dt.date==rg
        wd=fc_daily.loc[mask].copy()
        a,b,c,d=st.columns(4)
        with a:kpi("Nhiệt độ TB",f"{wd.tavg.mean():.1f} °C")
        with b:kpi("Số ngày ≥35°C",str(int((wd.tmax>=35).sum())))
        with c:kpi("Số ngày ≥37°C",str(int((wd.tmax>=37).sum())))
        with d:kpi("Tổng mưa",f"{wd.rain_mm.sum():.1f} mm")
        fig=go.Figure();fig.add_trace(go.Scatter(x=wd.date,y=wd.tmax,name="Tmax",mode="lines+markers"));fig.add_trace(go.Scatter(x=wd.date,y=wd.tavg,name="Tavg",mode="lines+markers"));fig.add_trace(go.Scatter(x=wd.date,y=wd.tmin,name="Tmin",mode="lines+markers"));fig.update_layout(title="Nhiệt độ theo ngày",yaxis_title="°C")
        st.plotly_chart(fig,use_container_width=True)
        st.plotly_chart(px.bar(wd,x="date",y="rain_mm",title="Lượng mưa theo ngày",labels={"rain_mm":"mm","date":"Ngày"}),use_container_width=True)
        st.dataframe(wd.rename(columns={"date":"Ngày","tmax":"Tmax °C","tavg":"Tavg °C","tmin":"Tmin °C","rain_mm":"Mưa mm","sunshine_h":"Nắng giờ"}),use_container_width=True,hide_index=True)
        st.subheader("Biến thời tiết tự tổng hợp cho các tháng dự báo")
        st.dataframe(fut_weather,use_container_width=True,hide_index=True)

with t4:
    st.subheader("Top 100 khách hàng ảnh hưởng")
    if not top100.empty: st.dataframe(top100,use_container_width=True,hide_index=True)
    st.subheader("Phân tích theo ngành nghề")
    inds=industry_summary(customer_long,True)
    if not inds.empty:
        st.dataframe(inds.head(50),use_container_width=True,hide_index=True)
        label="industry_name" if "industry_name" in inds.columns else inds.columns[0]
        st.plotly_chart(px.bar(inds.head(15),x="kwh",y=label,orientation="h",title="Top ngành nghề theo điện năng tháng mới nhất"),use_container_width=True)
    if "customer_type" in customer_long.columns:
        latest_d=pd.to_datetime(customer_long.date).max();typ=customer_long[pd.to_datetime(customer_long.date)==latest_d].groupby("customer_type",as_index=False).agg(customers=("customer_id","nunique"),kwh=("kwh","sum")).sort_values("kwh",ascending=False)
        typ["share_pct"]=typ.kwh/max(typ.kwh.sum(),1)*100
        st.subheader("Theo loại khách hàng")
        st.dataframe(typ,use_container_width=True,hide_index=True)
        st.plotly_chart(px.pie(typ,names="customer_type",values="kwh",hole=.5,title="Cơ cấu điện năng theo loại khách hàng"),use_container_width=True)

with t5:
    st.subheader("Nhật ký mất điện / nguyên nhân sai số")
    st.caption("Nhật ký được lưu vết qua các lần cập nhật. Có thể xóa dòng nhập sai. TY_LE_PHU_TAI_ANH_HUONG được tự tính theo sản lượng của nhóm KH bị ảnh hưởng chia tổng sản lượng toàn đơn vị cùng tháng.")
    saved_outages=load_outage_history()
    if saved_outages.empty:
        st.info("Chưa có nhật ký mất điện đã lưu. Hãy Upload mẫu ở thanh bên hoặc dùng Nhập nhanh.")
    else:
        show=saved_outages.copy()
        show=auto_impact_ratio_by_consumption(show,customer_long)
        show["Xóa"]=False
        preferred=["Xóa","record_id","event_id","date","start_time","end_time","duration_hours","customer_id","customer_name","reason","TY_LE_PHU_TAI_ANH_HUONG_%","TY_TRONG_KH_TRONG_SU_CO_%","affected_kwh_month","system_kwh_month","source","saved_at"]
        cols=[c for c in preferred if c in show.columns]+[c for c in show.columns if c not in preferred and c not in {"impact_ratio","event_impact_ratio","customer_share_in_event","month","event_affected_kwh"}]
        edited=st.data_editor(show[cols],use_container_width=True,hide_index=True,disabled=[c for c in cols if c!="Xóa"],key="outage_delete_editor")
        cdel,csave=st.columns([1,3])
        with cdel:
            if st.button("🗑️ Xóa dòng đã chọn",use_container_width=True):
                ids=edited.loc[edited["Xóa"]==True,"record_id"].astype(str).tolist() if "Xóa" in edited.columns else []
                if not ids: st.warning("Chưa chọn dòng cần xóa.")
                else:
                    delete_outage_records(ids)
                    st.session_state.model_state.setdefault("events",[]).append({"time":datetime.now().isoformat(timespec="seconds"),"type":"outage_delete","record_ids":ids})
                    save_state(st.session_state.model_state)
                    st.success(f"Đã xóa {len(ids)} dòng và lưu vết thao tác.")
                    st.rerun()
        st.markdown("**Cách tính tỷ lệ tự động:** `Σ sản lượng tháng của KH bị ảnh hưởng / Tổng sản lượng toàn đơn vị cùng tháng × 100%`.")
    if not outage_details.empty:
        st.subheader("Kết quả ước điện năng không thực hiện")
        st.dataframe(outage_details,use_container_width=True,hide_index=True)
        st.subheader("Tổng hợp theo tháng")
        st.dataframe(outage_monthly,use_container_width=True,hide_index=True)

with t6:
    st.subheader("Dự báo chính thức theo Adaptive Ensemble")
    st.dataframe(forecast_df[["date","Ensemble"]].rename(columns={"date":"Tháng","Ensemble":"Dự báo kWh"}).style.format({"Dự báo kWh":"{:,.0f}"}),use_container_width=True,hide_index=True)
    st.markdown("**Nguyên tắc:** không chọn mô hình theo cảm tính. Hệ thống back-test 5 nhánh, tính MAPE/MAE/RMSE, sau đó tăng trọng số cho mô hình có MAPE thấp hơn. Bottom-up và hồi quy đa biến giúp phản ánh biến động KH lớn, thời tiết, lịch và mất điện; các mô hình chuỗi giữ vai trò kiểm tra quy luật xu hướng/mùa vụ.")

with t7:
    st.subheader("So sánh dự báo và thực tế")
    st.caption("Muốn có báo cáo sai số đúng theo thời điểm dự báo, hãy bấm 'Ghi nhận dự báo hiện tại' trước khi có số thực tế tháng đó. Khi upload file tháng mới, app tự ghép thực tế và tính sai số.")
    cA,cB=st.columns([1,3])
    with cA:
        if st.button("📌 Ghi nhận dự báo hiện tại",use_container_width=True):
            st.session_state.model_state=record_forecasts_to_state(st.session_state.model_state,forecast_df,weights,_source_latest)
            save_state(st.session_state.model_state)
            st.success("Đã lưu snapshot dự báo vào Model State")
    err_detail,err_summary=build_error_report(st.session_state.model_state,series_actual)
    if err_detail.empty:
        st.info("Chưa có cặp dự báo–thực tế trong Model State. Hãy ghi nhận dự báo, sau đó khi có tháng mới upload file tại mục '1B) Cập nhật tháng mới'.")
    else:
        st.subheader("Bảng sai số chi tiết theo tháng và mô hình")
        show=err_detail.copy();show["target_month"]=pd.to_datetime(show.target_month).dt.strftime("%m/%Y")
        cols=[c for c in ["target_month","model","forecast_kwh","actual","sai_lech_kWh","sai_lech_tuyet_doi_kWh","sai_so_pct","bias_pct","created_at"] if c in show.columns]
        st.dataframe(show[cols].style.format({"forecast_kwh":"{:,.0f}","actual":"{:,.0f}","sai_lech_kWh":"{:,.0f}","sai_lech_tuyet_doi_kWh":"{:,.0f}","sai_so_pct":"{:.2f}%","bias_pct":"{:.2f}%"}),use_container_width=True,hide_index=True)
        st.subheader("Xếp hạng chất lượng mô hình")
        st.dataframe(err_summary.style.format({"MAPE %":"{:.2f}%","MAE kWh":"{:,.0f}","RMSE kWh":"{:,.0f}","Bias kWh":"{:,.0f}","Bias %":"{:.2f}%"}),use_container_width=True,hide_index=True)
        if not err_summary.empty:
            st.plotly_chart(px.bar(err_summary,x="MAPE %",y="Mô hình",orientation="h",title="MAPE thực tế theo mô hình"),use_container_width=True)
        # latest actual month decomposition
        lm=pd.to_datetime(series_actual.date).max().to_period("M").to_timestamp()
        lmrows=err_detail[err_detail.target_month==lm]
        if not lmrows.empty:
            st.subheader(f"Chi tiết tháng {lm.strftime('%m/%Y')}")
            ens=lmrows[lmrows.model=="Ensemble"]
            if not ens.empty:
                r=ens.iloc[-1]
                c1,c2,c3,c4=st.columns(4)
                with c1:kpi("Dự báo Ensemble",fmt(r.forecast_kwh)+" kWh")
                with c2:kpi("Thực tế",fmt(r.actual)+" kWh")
                with c3:kpi("Chênh lệch",fmt(r.sai_lech_kWh)+" kWh")
                with c4:kpi("Sai số",f"{r.sai_so_pct:.2f}%")
            # reason context
            if not outage_monthly.empty:
                z=outage_monthly[pd.to_datetime(outage_monthly.date).dt.to_period("M").dt.to_timestamp()==lm]
                if not z.empty: st.write("**Ảnh hưởng mất điện tháng:**",z.to_dict("records"))
            # customer deltas month-over-month
            prev=lm-pd.DateOffset(months=1)
            a=customer_long[pd.to_datetime(customer_long.date).dt.to_period("M").dt.to_timestamp()==lm].groupby(["customer_id","customer_name"],as_index=False).kwh.sum().rename(columns={"kwh":"kwh_thang"})
            b=customer_long[pd.to_datetime(customer_long.date).dt.to_period("M").dt.to_timestamp()==prev].groupby(["customer_id","customer_name"],as_index=False).kwh.sum().rename(columns={"kwh":"kwh_truoc"})
            ch=a.merge(b,on=["customer_id","customer_name"],how="outer").fillna(0);ch["chenh_kwh"]=ch.kwh_thang-ch.kwh_truoc
            st.write("**Top KH làm thay đổi sản lượng so tháng trước:**")
            st.dataframe(pd.concat([ch.nlargest(10,"chenh_kwh"),ch.nsmallest(10,"chenh_kwh")]).drop_duplicates().sort_values("chenh_kwh").style.format({"kwh_thang":"{:,.0f}","kwh_truoc":"{:,.0f}","chenh_kwh":"{:+,.0f}"}),use_container_width=True,hide_index=True)

with t8:
    st.subheader("🤖 Trợ lý ChatGPT – không cần API key")
    st.caption("App không gọi OpenAI API và không phát sinh chi phí API. EVN Forecast chỉ tạo prompt đã tổng hợp dữ liệu; anh sao chép prompt rồi dán vào cuộc trò chuyện ChatGPT đang dùng.")
    st.info("Quy trình: chọn loại phân tích → app tạo prompt → bấm biểu tượng sao chép trên khung mã → dán vào ChatGPT. Không cần Streamlit Secrets hay OPENAI_API_KEY.")

    include_names = st.checkbox("Cho phép đưa tên Top KH vào prompt", value=False, help="Tắt mặc định để hạn chế đưa tên khách hàng ra ngoài app. Khi tắt, tên khách hàng được thay bằng '(ẩn tên KH)'.")

    err_detail_ai, err_summary_ai = build_error_report(st.session_state.model_state, series_actual)
    latest_month = pd.to_datetime(series_actual.date).max().to_period("M").to_timestamp()
    prev_month = latest_month - pd.DateOffset(months=1)

    # Customer change summary: only Top 20 and hide names by default
    cur = customer_long[pd.to_datetime(customer_long.date).dt.to_period("M").dt.to_timestamp()==latest_month].groupby(["customer_id","customer_name"],as_index=False).kwh.sum().rename(columns={"kwh":"current_kwh"})
    prv = customer_long[pd.to_datetime(customer_long.date).dt.to_period("M").dt.to_timestamp()==prev_month].groupby(["customer_id","customer_name"],as_index=False).kwh.sum().rename(columns={"kwh":"previous_kwh"})
    changes = cur.merge(prv,on=["customer_id","customer_name"],how="outer").fillna(0)
    changes["delta_kwh"] = changes.current_kwh - changes.previous_kwh
    changes = pd.concat([changes.nlargest(10,"delta_kwh"), changes.nsmallest(10,"delta_kwh")]).drop_duplicates("customer_id")
    if not include_names and not changes.empty:
        changes = changes.copy(); changes["customer_name"] = "(ẩn tên KH)"

    weather_payload = {}
    if not hist_weather.empty:
        wh = hist_weather.copy(); wh["date"] = pd.to_datetime(wh.date)
        weather_payload["recent_months"] = wh.tail(4).to_dict("records")
    if not fut_weather.empty:
        weather_payload["forecast_months"] = fut_weather.head(max(horizon,1)).to_dict("records")

    outage_payload = outage_monthly.tail(6).to_dict("records") if not outage_monthly.empty else []
    payload = {
        "unit": "Điện lực Thường Xuân",
        "latest_actual_month": str(latest_month.date()),
        "latest_actual_kwh": float(series_actual.loc[pd.to_datetime(series_actual.date).dt.to_period("M").dt.to_timestamp()==latest_month,"actual"].sum()),
        "normalized_latest_kwh": float(series_norm.loc[pd.to_datetime(series_norm.date).dt.to_period("M").dt.to_timestamp()==latest_month,"normalized_actual"].sum()) if "normalized_actual" in series_norm.columns else None,
        "backtest": backtest.to_dict("records"),
        "weights": weights,
        "forecasts": forecast_df.to_dict("records"),
        "error_summary": err_summary_ai.to_dict("records") if not err_summary_ai.empty else [],
        "error_latest": err_detail_ai[err_detail_ai.target_month==latest_month].to_dict("records") if not err_detail_ai.empty else [],
        "weather": weather_payload,
        "outages": outage_payload,
        "customer_changes_top20": changes.to_dict("records"),
        "top100_summary": {"count": int(len(top100)), "columns": list(top100.columns)},
        "data_note": "Prompt chỉ chứa dữ liệu tổng hợp; file khách hàng gốc không được đưa vào prompt."
    }

    if "last_chatgpt_prompt" not in st.session_state:
        st.session_state["last_chatgpt_prompt"] = ""

    c1,c2,c3=st.columns(3)
    if c1.button("🧠 Tạo prompt phân tích dự báo", use_container_width=True):
        task = "Phân tích dự báo hiện tại, so sánh 5 nhánh mô hình, giải thích back-test, MAPE/MAE/RMSE, trọng số Ensemble, tác động thời tiết/mùa vụ/mất điện/khách hàng và nêu rủi ro chính."
        st.session_state["last_chatgpt_prompt"] = build_chatgpt_prompt(task, payload)
    if c2.button("🎯 Tạo prompt giải trình sai số", use_container_width=True):
        task = "Phân tích chi tiết sai số dự báo so với thực tế. Tách nguyên nhân do mô hình, thời tiết, mất điện, ngày nghỉ/lễ, mùa vụ, ngành nghề và biến động khách hàng; định lượng phần nào dữ liệu cho phép và nêu phần cần xác minh. Soạn nội dung có thể dùng làm giải trình."
        st.session_state["last_chatgpt_prompt"] = build_chatgpt_prompt(task, payload)
    if c3.button("📄 Tạo prompt báo cáo lãnh đạo", use_container_width=True):
        task = "Soạn báo cáo ngắn trình lãnh đạo về kết quả dự báo điện thương phẩm, chất lượng 5 mô hình và Ensemble, chênh lệch dự báo-thực tế, các yếu tố thời tiết/mất điện/khách hàng ảnh hưởng và đề xuất kỳ tiếp theo."
        st.session_state["last_chatgpt_prompt"] = build_chatgpt_prompt(task, payload)

    st.divider()
    q=st.text_area("Câu hỏi tùy chỉnh cho ChatGPT",placeholder="Ví dụ: Vì sao dự báo tháng 10 giảm? Mô hình nào đang ổn định nhất? Top nguyên nhân sai số tháng 8 là gì?")
    if st.button("💬 Tạo prompt theo câu hỏi của tôi",use_container_width=True):
        task = "Trả lời câu hỏi của người dùng dựa trên dữ liệu EVN Forecast được cung cấp, có đối chiếu các mô hình và các yếu tố ảnh hưởng liên quan."
        st.session_state["last_chatgpt_prompt"] = build_chatgpt_prompt(task, payload, q)

    prompt = st.session_state.get("last_chatgpt_prompt", "")
    if prompt:
        st.success("Prompt đã sẵn sàng. Bấm biểu tượng sao chép ở góc khung bên dưới, sau đó dán vào ChatGPT.")
        st.code(prompt, language=None, wrap_lines=True)
        st.download_button("⬇️ Tải prompt (.txt)", prompt.encode("utf-8"), "EVN_Forecast_ChatGPT_Prompt.txt", "text/plain", use_container_width=True)
        st.text_area("Hoặc chọn toàn bộ nội dung tại đây để Ctrl+C", value=prompt, height=240)
        st.session_state.model_state.setdefault("prompt_history",[]).append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "latest_month": str(latest_month.date()),
            "include_customer_names": bool(include_names),
            "chars": len(prompt),
        })
    else:
        st.caption("Chọn một trong ba nút phía trên để tạo prompt. App không cần API key và không gửi dữ liệu tự động tới ChatGPT.")

with t9:
    st.subheader("Model State")
    st.session_state.model_state["last_run"]={"time":datetime.now().isoformat(timespec="seconds"),"latest_month":str(pd.to_datetime(series_actual.date).max().date()),"weights":weights,"backtest":backtest.to_dict("records")}
    st.session_state.model_state["model_weights"]=weights
    st.session_state.model_state["backtest"]=backtest.to_dict("records")
    if st.button("💾 Lưu Model State"):
        save_state(st.session_state.model_state);st.success("Đã lưu")
    st.download_button("⬇️ Tải model_state.json",state_to_bytes(st.session_state.model_state),"model_state.json","application/json")
    st.json(st.session_state.model_state.get("last_run",{}))

with t10:
    st.subheader("Xuất bộ kết quả")
    bio=io.BytesIO()
    with pd.ExcelWriter(bio,engine="openpyxl") as w:
        series_norm.to_excel(w,sheet_name="Du_lieu_tong",index=False)
        backtest.to_excel(w,sheet_name="Backtest_5_mo_hinh",index=False)
        forecast_df.to_excel(w,sheet_name="Du_bao",index=False)
        top100.to_excel(w,sheet_name="Top100",index=False)
        inds.to_excel(w,sheet_name="Nganh_nghe",index=False)
        if not outage_monthly.empty:outage_monthly.to_excel(w,sheet_name="Mat_dien_thang",index=False)
        if not fut_weather.empty:fut_weather.to_excel(w,sheet_name="Thoi_tiet_du_bao",index=False)
        err_detail,err_summary=build_error_report(st.session_state.model_state,series_actual)
        if not err_detail.empty:err_detail.to_excel(w,sheet_name="Sai_so_chi_tiet",index=False)
        if not err_summary.empty:err_summary.to_excel(w,sheet_name="Tong_hop_sai_so",index=False)
    st.download_button("⬇️ Tải Excel kết quả EVN Forecast 1.5.1",bio.getvalue(),"EVN_Forecast_1.5.2_Ket_qua.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
