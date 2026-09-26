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
from outage_engine import parse_outage_workbook, estimate_outage_losses, normalize_series_for_outages
from weather_engine import fetch_history, fetch_forecast, apply_overrides, monthly_features, future_month_features
from state_manager import load_state, save_state, state_to_bytes, merge_uploaded_state

st.set_page_config(page_title="EVN Forecast 1.4.1 Multi-Model",page_icon="⚡",layout="wide")

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

st.sidebar.title("⚡ EVN Forecast 1.4.1")
st.sidebar.caption("Multi-Model • Back-test • Weather • Bottom-up • Outage")
state_upload=st.sidebar.file_uploader("Khôi phục Model State (.json)",type=["json"])
if state_upload:
    try:
        st.session_state.model_state=merge_uploaded_state(state_upload.getvalue());st.sidebar.success("Đã khôi phục Model State")
    except Exception as e:st.sidebar.error(str(e))

st.sidebar.subheader("1) Dữ liệu khách hàng")
combined=st.sidebar.file_uploader("File điện năng gộp 2025–2026 / file mới nhất",type=["xlsx","xls"],key="combined")
f2025=st.sidebar.file_uploader("Hoặc file riêng năm 2025",type=["xlsx","xls"],key="f2025")
f2026=st.sidebar.file_uploader("Hoặc file riêng năm 2026",type=["xlsx","xls"],key="f2026")
history_file=st.sidebar.file_uploader("Lịch sử ĐTP tổng 2022–2024 (tùy chọn)",type=["xlsx","csv"],key="hist")

st.sidebar.subheader("1B) Cập nhật tháng mới")
new_month_file=st.sidebar.file_uploader("File điện năng có tháng mới",type=["xlsx","xls"],key="new_month")
st.sidebar.caption("Dùng khi có T9, T10... mới. App sẽ ghép theo Mã KH + tháng và ưu tiên số liệu file mới nếu trùng.")

st.sidebar.subheader("2) Mất điện / nguyên nhân sai số")
try:
    tpl=open("Mau_Nhat_ky_mat_dien.xlsx","rb").read();st.sidebar.download_button("⬇️ Mẫu nhật ký mất điện",tpl,"Mau_Nhat_ky_mat_dien.xlsx",use_container_width=True)
except:pass
outage_file=st.sidebar.file_uploader("Upload nhật ký mất điện",type=["xlsx"],key="outage")
st.sidebar.caption("Có thể nhập Ngày, giờ bắt đầu/kết thúc, Mã KH, nguyên nhân sai số trong tab ⚡ Mất điện.")

st.sidebar.subheader("3) Dự báo")
horizon=st.sidebar.selectbox("Số tháng dự báo",[1,3,6,12],index=1)
use_normalized=st.sidebar.checkbox("Chuẩn hóa lịch sử do mất điện",value=True)

st.sidebar.subheader("4) Thời tiết")
st.sidebar.text_input("Địa điểm",WEATHER_LOCATION_NAME,disabled=True)
st.sidebar.caption(f"Khóa tọa độ {WEATHER_LAT:.5f}, {WEATHER_LON:.5f}")

st.title("⚡ EVN Forecast 1.4.1 Multi-Model – Điện lực Thường Xuân")
st.caption("5 nhánh đối chiếu: Thống kê/tăng trưởng • Holt-Winters • SARIMA • Hồi quy đa biến • Bottom-up khách hàng")

with st.expander("⚡ Nhập nhanh mất điện / nguyên nhân sai số", expanded=False):
    st.caption("Dữ liệu nhập ở đây được đưa trực tiếp vào biến mất điện của mô hình. Có thể để trống và dùng file nhật ký chi tiết ở thanh bên.")
    manual_default=pd.DataFrame(columns=["Ngày","Giờ bắt đầu","Giờ kết thúc","Mã KH","Nguyên nhân sai số","Tỷ lệ ảnh hưởng %"])
    manual=st.data_editor(manual_default,num_rows="dynamic",use_container_width=True,key="manual_outages_top")

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
        impact=pd.to_numeric(pd.Series([r.get("Tỷ lệ ảnh hưởng %",100)]),errors="coerce").fillna(100).iloc[0]/100
        out.append({"event_id":f"MANUAL-{i+1}","date":d.normalize(),"start_time":a,"end_time":b,"duration_hours":dur,"tba":"","scope":"","reason":str(r.get("Nguyên nhân sai số","") or ""),"impact_ratio":float(np.clip(impact,0,1)),"note":"Nhập trực tiếp","customer_id":str(r.get("Mã KH","") or ""),"customer_name":"","power_kw":np.nan,"kwh_per_hour_input":np.nan,"time_factor":1.0})
    return pd.DataFrame(out)

# -------- data --------
frames=[]
try:
    if combined is not None: frames.append(parse_customer_workbook(combined))
    if f2025 is not None: frames.append(parse_customer_workbook(f2025,2025))
    if f2026 is not None: frames.append(parse_customer_workbook(f2026,2026))
    if new_month_file is not None: frames.append(parse_customer_workbook(new_month_file))
except Exception as e:st.error(f"Lỗi đọc dữ liệu KH: {e}")
customer_long=pd.concat(frames,ignore_index=True).drop_duplicates(["customer_id","date"],keep="last") if frames else pd.DataFrame()
monthly=aggregate_monthly(customer_long)
history=None
if history_file is not None:
    try:history=pd.read_csv(history_file) if history_file.name.lower().endswith(".csv") else pd.read_excel(history_file)
    except Exception as e:st.warning(f"Không đọc được lịch sử tổng: {e}")
series_actual=merge_total_history(history,monthly)
if series_actual.empty:
    st.info("Nạp file điện năng khách hàng để bắt đầu. File gộp có thể chứa các cột 'Điện năng tháng 1/2025' ... 'Điện năng tháng 8/2026'.")
    st.stop()

# -------- outages: uploaded + manual --------
outage_rows=pd.DataFrame(); outage_details=pd.DataFrame(); outage_monthly=pd.DataFrame()
if outage_file is not None:
    try: outage_rows=parse_outage_workbook(outage_file)
    except Exception as e: st.error(f"Lỗi nhật ký mất điện: {e}")
manual_rows=manual_to_outage(manual)
if not manual_rows.empty:
    outage_rows=pd.concat([outage_rows,manual_rows],ignore_index=True) if not outage_rows.empty else manual_rows

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

def record_forecasts_to_state(state, forecast_df, weights):
    hist=list(state.get("forecast_history",[]))
    now=datetime.now().isoformat(timespec="seconds")
    existing={(str(x.get("target_month")), str(x.get("model")), str(x.get("run_month"))) for x in hist}
    run_month=str(pd.Timestamp.today().to_period("M"))
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
    # If multiple runs forecast same target/model, keep the latest forecast created before actual was known; here latest stored snapshot is used.
    if "created_at" in fh.columns:
        fh=fh.sort_values("created_at").drop_duplicates(["target_month","model"],keep="last")
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
t1,t2,t3,t4,t5,t6,t7,t8,t9=st.tabs(["📊 Tổng quan","📈 5 mô hình","🌦️ Thời tiết","👥 Khách hàng","⚡ Mất điện","🔮 Dự báo","🎯 Đối chiếu sai số","💾 Model State","📤 Xuất dữ liệu"])

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
    st.subheader("Nhập mất điện và nguyên nhân sai số")
    st.caption("Nhập trực tiếp để truy vết: ngày, giờ bắt đầu/kết thúc, Mã KH và nguyên nhân sai số. Với dữ liệu chính thức nên dùng file mẫu để ước sản lượng không thực hiện theo từng KH.")
    if manual is not None and not manual.empty:
        st.markdown("**Dữ liệu nhập nhanh đang dùng:**")
        st.dataframe(manual,use_container_width=True,hide_index=True)
    if not outage_details.empty:
        st.subheader("Kết quả tính từ nhật ký upload")
        st.dataframe(outage_details,use_container_width=True,hide_index=True)
        st.subheader("Tổng hợp theo tháng")
        st.dataframe(outage_monthly,use_container_width=True,hide_index=True)
    else: st.info("Chưa có nhật ký mất điện upload. Bảng nhập tay ở trên được dùng làm hồ sơ nguyên nhân; để tính kWh mất chính xác theo KH, hãy tải mẫu và upload ở thanh bên.")

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
            st.session_state.model_state=record_forecasts_to_state(st.session_state.model_state,forecast_df,weights)
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
    st.subheader("Model State")
    st.session_state.model_state["last_run"]={"time":datetime.now().isoformat(timespec="seconds"),"latest_month":str(pd.to_datetime(series_actual.date).max().date()),"weights":weights,"backtest":backtest.to_dict("records")}
    st.session_state.model_state["model_weights"]=weights
    st.session_state.model_state["backtest"]=backtest.to_dict("records")
    if st.button("💾 Lưu Model State"):
        save_state(st.session_state.model_state);st.success("Đã lưu")
    st.download_button("⬇️ Tải model_state.json",state_to_bytes(st.session_state.model_state),"model_state.json","application/json")
    st.json(st.session_state.model_state.get("last_run",{}))

with t9:
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
    st.download_button("⬇️ Tải Excel kết quả EVN Forecast 1.4.1",bio.getvalue(),"EVN_Forecast_1.4.1_Ket_qua.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
