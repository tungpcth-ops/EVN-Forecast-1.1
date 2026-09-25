import io
import os
import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from forecast_engine import parse_customer_file, aggregate_monthly, detect_top_influence, build_total_series, compare_models, forecast_future
from outage_engine import parse_outage_workbook, estimate_outage_losses, normalize_series_for_outages
from state_manager import load_state, save_state, state_to_bytes, merge_uploaded_state
from report_export import build_docx, build_pdf

st.set_page_config(page_title="EVN Forecast 1.2", page_icon="⚡", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.metric-card {background:linear-gradient(135deg,#0b4f8a,#1677b8); color:white; padding:18px; border-radius:16px; box-shadow:0 6px 18px rgba(0,0,0,.12);}
.metric-card h3 {font-size:0.9rem; opacity:.85; margin:0 0 6px 0;}
.metric-card .big {font-size:1.55rem; font-weight:700; margin:0;}
.alert-card {background:#fff5e6; border-left:5px solid #f59e0b; padding:12px 16px; border-radius:10px;}
.success-card {background:#ecfdf5; border-left:5px solid #10b981; padding:12px 16px; border-radius:10px;}
.info-card {background:#eff6ff; border-left:5px solid #2563eb; padding:12px 16px; border-radius:10px;}
</style>
""", unsafe_allow_html=True)

STATE_PATH="model_state.json"


def fmt_int(x):
    try: return f"{float(x):,.0f}".replace(",", ".")
    except Exception: return str(x)


def get_secret(name, default=None):
    try:
        if name in st.secrets: return st.secrets[name]
    except Exception: pass
    return os.getenv(name, default)

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_open_meteo(lat,lon):
    url="https://api.open-meteo.com/v1/forecast"
    params={"latitude":lat,"longitude":lon,"daily":"temperature_2m_max,temperature_2m_min,precipitation_sum","forecast_days":16,"timezone":"Asia/Ho_Chi_Minh"}
    r=requests.get(url,params=params,timeout=15); r.raise_for_status(); return r.json()


def ai_explain(summary_text):
    key=get_secret("OPENAI_API_KEY")
    if not key: return None,"Chưa cấu hình OPENAI_API_KEY trong Streamlit Secrets."
    try:
        from openai import OpenAI
        client=OpenAI(api_key=key)
        model=get_secret("OPENAI_MODEL","gpt-5.6-luna")
        prompt=f"""Bạn là chuyên gia dự báo điện thương phẩm. Phân tích ngắn gọn, định lượng, phân biệt dữ liệu thực tế với suy luận. Chú ý ảnh hưởng mất điện phải dựa trên giờ mất điện và khách hàng bị ảnh hưởng, không quy đổi cơ học theo số ngày.\n{summary_text}\nYêu cầu: xu hướng, nguyên nhân, khách hàng bất thường, mất điện, rủi ro sai số, mức kế hoạch khuyến nghị."""
        resp=client.responses.create(model=model,input=prompt)
        return resp.output_text,None
    except Exception as e: return None,str(e)


def card(title,value,subtitle=""):
    st.markdown(f'<div class="metric-card"><h3>{title}</h3><div class="big">{value}</div><div>{subtitle}</div></div>',unsafe_allow_html=True)


if "model_state" not in st.session_state:
    st.session_state.model_state=load_state(STATE_PATH)

st.sidebar.title("⚡ EVN Forecast 1.2")
st.sidebar.caption("Web • Adaptive • Outage Detail • Model State • Auto Report")
state_upload=st.sidebar.file_uploader("Khôi phục Model State (.json)",type=["json"],key="state_upload")
if state_upload and st.sidebar.button("Khôi phục trạng thái"):
    try:
        st.session_state.model_state=merge_uploaded_state(state_upload.getvalue())
        save_state(st.session_state.model_state,STATE_PATH)
        st.sidebar.success("Đã khôi phục Model State")
    except Exception as e: st.sidebar.error(str(e))

st.sidebar.subheader("1) Dữ liệu nền")
f2025=st.sidebar.file_uploader("Điện năng khách hàng 2025",type=["xlsx","xls"],key="f2025")
f2026=st.sidebar.file_uploader("Điện năng khách hàng 2026",type=["xlsx","xls"],key="f2026")
history_file=st.sidebar.file_uploader("Lịch sử điện thương phẩm tổng",type=["xlsx","csv"],key="hist")

st.sidebar.subheader("2) Cập nhật tháng mới")
new_month_file=st.sidebar.file_uploader("File điện năng có tháng mới",type=["xlsx","xls"],key="new_month")
new_year=st.sidebar.number_input("Năm dữ liệu",min_value=2020,max_value=2100,value=2026,step=1)
update_btn=st.sidebar.button("🔄 Cập nhật tháng mới",type="primary",use_container_width=True)

st.sidebar.subheader("3) Mất điện chi tiết")
try:
    template_bytes=open("Mau_Nhat_ky_mat_dien.xlsx","rb").read()
    st.sidebar.download_button("⬇️ Tải mẫu nhật ký mất điện",template_bytes,"Mau_Nhat_ky_mat_dien.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
except Exception:
    pass
outage_file=st.sidebar.file_uploader("Nhật ký mất điện + KH ảnh hưởng",type=["xlsx"],key="outage_file")
st.sidebar.caption("Ưu tiên file chi tiết theo sự cố/KH. Nếu chưa có danh sách KH, có thể dùng hiệu chỉnh tổng hợp bên dưới.")
with st.sidebar.expander("Hiệu chỉnh tổng hợp dự phòng"):
    fallback_hours=st.number_input("Tổng số giờ mất điện",min_value=0.0,max_value=744.0,value=0.0,step=0.5)
    fallback_impact=st.slider("Tỷ lệ phụ tải bị ảnh hưởng (%)",0,100,0,5)

manual_note=st.sidebar.text_area("Ghi chú vận hành",value=st.session_state.model_state.get("notes", ""),height=80)

st.sidebar.subheader("4) Thời tiết")
# Khóa địa điểm thời tiết theo đúng xã Thường Xuân, tỉnh Thanh Hóa.
# Tọa độ trung tâm xã: khoảng 19.90389 N, 105.34889 E.
WEATHER_LOCATION_NAME = "Xã Thường Xuân, tỉnh Thanh Hóa"
WEATHER_LAT = 19.90389
WEATHER_LON = 105.34889
st.sidebar.text_input("Địa điểm dự báo", value=WEATHER_LOCATION_NAME, disabled=True)
st.sidebar.caption(f"Tọa độ cố định: {WEATHER_LAT:.5f}, {WEATHER_LON:.5f} • Không dùng Thọ Xuân/Như Xuân")
lat=WEATHER_LAT
lon=WEATHER_LON

st.title("⚡ EVN Forecast 1.2 – Điện lực Thường Xuân")
st.caption("Dashboard thích ứng • Mất điện theo giờ/KH • Model State • Word/PDF tự động")

frames=[]
for year,obj in [(2025,f2025),(2026,f2026)]:
    if obj is not None:
        try: frames.append(parse_customer_file(obj,year))
        except Exception as e: st.error(f"Không đọc được file {year}: {e}")
if update_btn and new_month_file is not None:
    try:
        nm=parse_customer_file(new_month_file,int(new_year)); frames.append(nm)
        st.session_state.model_state["events"].append({"time":datetime.now().isoformat(timespec="seconds"),"type":"monthly_update","year":int(new_year),"file":new_month_file.name})
        st.success("Đã nạp file tháng mới vào phiên phân tích.")
    except Exception as e: st.error(f"Không cập nhật được tháng mới: {e}")

customer_long=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
monthly=aggregate_monthly(customer_long) if not customer_long.empty else pd.DataFrame(columns=["date","actual"])

history=None
if history_file is not None:
    try: history=pd.read_csv(history_file) if history_file.name.lower().endswith('.csv') else pd.read_excel(history_file)
    except Exception as e: st.warning(f"Không đọc được lịch sử tổng: {e}")
series_actual=build_total_series(history,monthly)
if series_actual.empty:
    st.info("Hãy nạp dữ liệu 2025/2026 hoặc lịch sử điện thương phẩm để bắt đầu."); st.stop()

# Detailed outage analysis
outage_details=pd.DataFrame(); outage_monthly=pd.DataFrame(columns=["date","lost_kwh"])
if outage_file is not None:
    try:
        raw_outages=parse_outage_workbook(outage_file)
        outage_details,outage_monthly=estimate_outage_losses(raw_outages,customer_long,series_actual)
    except Exception as e:
        st.error(f"Không đọc/ước tính được file mất điện: {e}")

# Fallback aggregated correction applies only when no detailed outage estimate is supplied.
if outage_monthly.empty and fallback_hours>0 and fallback_impact>0:
    last=series_actual.iloc[-1]
    d=pd.to_datetime(last['date'])
    days=d.days_in_month
    lost=float(last['actual'])/(days*24)*float(fallback_hours)*(float(fallback_impact)/100.0)
    outage_monthly=pd.DataFrame({"date":[d.to_period('M').to_timestamp()],"lost_kwh":[lost]})

series_norm=normalize_series_for_outages(series_actual,outage_monthly)
model_series=series_norm[["date","normalized_actual"]].rename(columns={"normalized_actual":"actual"})
backtest=compare_models(model_series)
fc3,weights=forecast_future(model_series,horizon=3)
top100=detect_top_influence(customer_long,100) if not customer_long.empty else pd.DataFrame()
latest=series_norm.iloc[-1]; prev=series_norm.iloc[-2] if len(series_norm)>1 else None
latest_month=pd.to_datetime(latest['date']).strftime('%Y_%m')

weather=None
try: weather=fetch_open_meteo(float(lat),float(lon))
except Exception: pass

c1,c2,c3,c4,c5=st.columns(5)
with c1: card("Tháng mới nhất",pd.to_datetime(latest['date']).strftime('%m/%Y'),"")
with c2: card("Thực tế",fmt_int(latest['actual'])+" kWh","")
with c3: card("Ước mất do mất điện",fmt_int(latest.get('outage_lost_kwh',0))+" kWh","")
with c4: card("Chuẩn hóa",fmt_int(latest.get('normalized_actual',latest['actual']))+" kWh","")
with c5:
    best=backtest.iloc[0] if not backtest.empty else None
    card("MAPE tốt nhất",f"{best['MAPE_1step']:.2f}%" if best is not None else "N/A",str(best['model']) if best is not None else "")

if not top100.empty:
    extreme=top100[top100['delta_kwh'].abs()>=300000]
    if not extreme.empty:
        st.markdown(f'<div class="alert-card"><b>⚠️ Cảnh báo:</b> phát hiện {len(extreme)} khách hàng biến động tuyệt đối ≥ 300.000 kWh trong tháng gần nhất.</div>',unsafe_allow_html=True)
if not outage_monthly.empty:
    total_lost=outage_monthly['lost_kwh'].sum()
    st.markdown(f'<div class="info-card"><b>⚡ Mất điện:</b> điện năng ước không thực hiện trong các tháng có nhật ký: <b>{fmt_int(total_lost)} kWh</b>. Mô hình dùng chuỗi chuẩn hóa để học xu hướng nhưng vẫn giữ số thực tế để báo cáo.</div>',unsafe_allow_html=True)

# Tabs
t1,t2,t3,t4,t5,t6,t7=st.tabs(["📊 Dashboard","⚡ Mất điện","👥 Top 100","📈 Kiểm định","🔮 Dự báo","💾 Model State","📄 Báo cáo & AI"])

with t1:
    left,right=st.columns([2,1])
    with left:
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=series_norm['date'],y=series_norm['actual'],mode='lines+markers',name='Thực tế'))
        if series_norm['outage_lost_kwh'].sum()>0:
            fig.add_trace(go.Scatter(x=series_norm['date'],y=series_norm['normalized_actual'],mode='lines+markers',name='Chuẩn hóa mất điện',line=dict(dash='dot')))
        fig.add_trace(go.Scatter(x=fc3['date'],y=fc3['forecast'],mode='lines+markers',name='Dự báo Ensemble',line=dict(dash='dash')))
        fig.update_layout(title="Điện thương phẩm: Thực tế • Chuẩn hóa • Dự báo",yaxis_title="kWh",hovermode="x unified",height=430)
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.subheader("Trọng số Adaptive Ensemble")
        wdf=pd.DataFrame({"Mô hình":list(weights.keys()),"Trọng số":list(weights.values())})
        if not wdf.empty: st.plotly_chart(px.pie(wdf,names='Mô hình',values='Trọng số',hole=.55),use_container_width=True)
    if weather:
        daily=weather.get('daily',{})
        wdf=pd.DataFrame({"Ngày":daily.get('time',[]),"Tmax":daily.get('temperature_2m_max',[]),"Tmin":daily.get('temperature_2m_min',[]),"Mưa":daily.get('precipitation_sum',[])})
        st.subheader(f"🌦️ Thời tiết 16 ngày tới – {WEATHER_LOCATION_NAME}")
        st.caption(f"Nguồn Open-Meteo tại tọa độ cố định {WEATHER_LAT:.5f}, {WEATHER_LON:.5f}")
        st.dataframe(wdf,use_container_width=True,hide_index=True)

with t2:
    st.subheader("Nhật ký mất điện chi tiết")
    st.markdown("**Cách tính:** ưu tiên `kWh/giờ ước tính` → `công suất kW` → lịch sử 3 tháng + cùng kỳ của từng KH → phụ tải tổng (chỉ khi không có mã KH).")
    if outage_file is None and fallback_hours==0:
        st.info("Hãy nạp file nhật ký mất điện ở thanh bên. File có thể gồm 2 sheet `Su_co` và `KH_mat_dien`.")
    if not outage_details.empty:
        a,b,c,d=st.columns(4)
        unique_events=outage_details['event_id'].nunique()
        unique_customers=outage_details.loc[outage_details['customer_id'].astype(str).str.len()>0,'customer_id'].nunique()
        kh_hours=(outage_details['duration_hours'].fillna(0)).sum()
        total_lost=outage_details['lost_kwh'].fillna(0).sum()
        a.metric("Số sự cố",f"{unique_events:,}")
        b.metric("KH bị ảnh hưởng",f"{unique_customers:,}")
        c.metric("KH-giờ mất điện",f"{kh_hours:,.1f}")
        d.metric("Ước điện năng mất",fmt_int(total_lost)+" kWh")
        st.dataframe(outage_details,use_container_width=True,hide_index=True)
        st.subheader("Tổng hợp theo tháng")
        st.dataframe(outage_monthly,use_container_width=True,hide_index=True)
        top_out=outage_details.dropna(subset=['lost_kwh']).groupby(['customer_id','customer_name'],as_index=False)['lost_kwh'].sum().sort_values('lost_kwh',ascending=False).head(30)
        if not top_out.empty:
            st.plotly_chart(px.bar(top_out.sort_values('lost_kwh'),x='lost_kwh',y='customer_name',orientation='h',title="Top KH bị ảnh hưởng điện năng do mất điện"),use_container_width=True)
        outb=io.BytesIO()
        with pd.ExcelWriter(outb,engine='openpyxl') as writer:
            outage_details.to_excel(writer,sheet_name='Chi_tiet_uoc_tinh',index=False)
            outage_monthly.to_excel(writer,sheet_name='Tong_hop_thang',index=False)
        st.download_button("⬇️ Tải kết quả phân tích mất điện",outb.getvalue(),"Phan_tich_mat_dien_EVN_Forecast_1.2.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif not outage_monthly.empty:
        st.warning("Đang dùng hiệu chỉnh tổng hợp vì chưa có danh sách khách hàng chi tiết.")
        st.dataframe(outage_monthly,use_container_width=True,hide_index=True)

with t3:
    if top100.empty: st.info("Cần file khách hàng để phân tích Top 100.")
    else:
        st.dataframe(top100,use_container_width=True,hide_index=True)
        q=st.select_slider("Số khách hàng hiển thị biểu đồ",options=[10,20,30,50],value=20)
        chart=top100.head(q).sort_values('delta_kwh')
        st.plotly_chart(px.bar(chart,x='delta_kwh',y='customer_name',orientation='h',title=f"Top {q} biến động kWh"),use_container_width=True)
        st.download_button("⬇️ Tải Top100 CSV",top100.to_csv(index=False).encode('utf-8-sig'),"Top100_EVN_Forecast_1_2.csv","text/csv")

with t4:
    st.caption("Kiểm định được thực hiện trên chuỗi đã chuẩn hóa ảnh hưởng mất điện khi có dữ liệu chi tiết.")
    st.dataframe(backtest,use_container_width=True,hide_index=True)
    if not backtest.empty:
        metric='MAPE_2step' if 'MAPE_2step' in backtest.columns else 'MAPE_1step'
        plot=backtest.dropna(subset=[metric]).sort_values(metric)
        st.plotly_chart(px.bar(plot,x='model',y=metric,text_auto='.2f',title=f"So sánh {metric}"),use_container_width=True)

with t5:
    horizon=st.selectbox("Tầm dự báo",[1,3,6,12],index=1)
    fc,weights_h=forecast_future(model_series,horizon=horizon)
    st.dataframe(fc,use_container_width=True,hide_index=True)
    st.write("**Trọng số:**",{k:round(v,4) for k,v in weights_h.items()})
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as writer:
        series_norm.to_excel(writer,sheet_name='Lich_su_chuan_hoa',index=False)
        fc.to_excel(writer,sheet_name='Du_bao',index=False)
        backtest.to_excel(writer,sheet_name='Backtest',index=False)
        pd.DataFrame([weights_h]).to_excel(writer,sheet_name='Trong_so',index=False)
        if not top100.empty: top100.to_excel(writer,sheet_name='Top100',index=False)
        if not outage_monthly.empty: outage_monthly.to_excel(writer,sheet_name='Mat_dien_thang',index=False)
        if not outage_details.empty: outage_details.to_excel(writer,sheet_name='Mat_dien_chi_tiet',index=False)
    st.download_button("⬇️ Xuất Excel",out.getvalue(),"EVN_Forecast_1.2_Ket_qua.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with t6:
    st.subheader("Model State")
    st.json(st.session_state.model_state)
    col1,col2=st.columns(2)
    if col1.button("💾 Lưu Model State",type="primary",use_container_width=True):
        state=st.session_state.model_state
        state['latest_month']=latest_month
        state['model_weights']={k:float(v) for k,v in weights.items()}
        state['backtest']=backtest.replace({np.nan:None}).to_dict(orient='records') if not backtest.empty else []
        state['notes']=manual_note
        if not outage_monthly.empty:
            state['outage_history']=outage_monthly.assign(date=outage_monthly['date'].astype(str)).replace({np.nan:None}).to_dict(orient='records')
        state['forecast_history'].append({"saved_at":datetime.now().isoformat(timespec='seconds'),"origin":latest_month,"forecast":fc3.assign(date=fc3['date'].astype(str)).to_dict(orient='records')})
        st.session_state.model_state=save_state(state,STATE_PATH)
        st.success("Đã lưu Model State 1.2 trên server hiện tại.")
    col2.download_button("⬇️ Tải Model State",state_to_bytes(st.session_state.model_state),"model_state.json","application/json",use_container_width=True)
    st.caption("Streamlit Community Cloud có thể khởi động lại server. Hãy tải model_state.json làm bản sao.")

with t7:
    st.subheader("Xuất báo cáo tự động")
    docx_bytes=build_docx(series_norm,fc3,backtest,top100,st.session_state.model_state,outage_monthly,outage_details)
    pdf_bytes=build_pdf(series_norm,fc3,backtest,top100,st.session_state.model_state,outage_monthly,outage_details)
    c1,c2=st.columns(2)
    c1.download_button("📘 Xuất Word",docx_bytes,"Bao_cao_EVN_Forecast_1.2.docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document",use_container_width=True)
    c2.download_button("📕 Xuất PDF",pdf_bytes,"Bao_cao_EVN_Forecast_1.2.pdf","application/pdf",use_container_width=True)

    st.subheader("🤖 Phân tích bằng ChatGPT")
    outage_summary = outage_monthly.to_string(index=False) if not outage_monthly.empty else "Không có dữ liệu mất điện chi tiết."
    summary=(f"Tháng mới nhất {pd.to_datetime(latest['date']).strftime('%m/%Y')}: thực tế {latest['actual']:.0f} kWh; chuẩn hóa {latest.get('normalized_actual',latest['actual']):.0f} kWh.\n"
             f"Mất điện:\n{outage_summary}\nBacktest:\n{backtest.to_string(index=False)}\nDự báo 3 tháng:\n{fc3.to_string(index=False)}\n"
             f"Trọng số: {weights}. Ghi chú: {manual_note}")
    if st.button("🤖 Phân tích bằng ChatGPT",use_container_width=True):
        with st.spinner("Đang phân tích..."):
            txt,err=ai_explain(summary)
        if txt: st.markdown(txt)
        else: st.warning(err)

st.divider()
st.caption("EVN Forecast 1.2 Web • Adaptive Forecast • Outage Detail • Model State • Auto Word/PDF")
