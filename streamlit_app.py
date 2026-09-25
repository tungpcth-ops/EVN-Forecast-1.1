import io
import os
import json
import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from forecast_engine import parse_customer_file, aggregate_monthly, detect_top_influence, build_total_series, compare_models, forecast_future
from state_manager import load_state, save_state, state_to_bytes, merge_uploaded_state
from report_export import build_docx, build_pdf

st.set_page_config(page_title="EVN Forecast 1.1", page_icon="⚡", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.metric-card {background:linear-gradient(135deg,#0b4f8a,#1677b8); color:white; padding:18px; border-radius:16px; box-shadow:0 6px 18px rgba(0,0,0,.12);}
.metric-card h3 {font-size:0.9rem; opacity:.85; margin:0 0 6px 0;}
.metric-card .big {font-size:1.55rem; font-weight:700; margin:0;}
.alert-card {background:#fff5e6; border-left:5px solid #f59e0b; padding:12px 16px; border-radius:10px;}
.success-card {background:#ecfdf5; border-left:5px solid #10b981; padding:12px 16px; border-radius:10px;}
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
        prompt=f"""Bạn là chuyên gia dự báo điện thương phẩm. Phân tích ngắn gọn, định lượng, phân biệt dữ liệu thực tế với suy luận.\n{summary_text}\nYêu cầu: xu hướng, nguyên nhân, khách hàng bất thường, rủi ro sai số, mức kế hoạch khuyến nghị."""
        resp=client.responses.create(model=model,input=prompt)
        return resp.output_text,None
    except Exception as e: return None,str(e)


def card(title,value,subtitle=""):
    st.markdown(f'<div class="metric-card"><h3>{title}</h3><div class="big">{value}</div><div>{subtitle}</div></div>',unsafe_allow_html=True)

# state init
if "model_state" not in st.session_state:
    st.session_state.model_state=load_state(STATE_PATH)

st.sidebar.title("⚡ EVN Forecast 1.1")
st.sidebar.caption("Web • Adaptive • Model State • Auto Report")
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

st.sidebar.subheader("3) Điều chỉnh nghiệp vụ")
outage_days=st.sidebar.number_input("Số ngày mất điện",0.0,31.0,0.0,0.5)
outage_impact=st.sidebar.slider("Mức ảnh hưởng mất điện (% phụ tải)",0,100,50,5)
manual_note=st.sidebar.text_area("Ghi chú vận hành",value=st.session_state.model_state.get("notes", ""),height=80)

st.sidebar.subheader("4) Thời tiết")
lat=st.sidebar.number_input("Vĩ độ",value=19.90,format="%.4f")
lon=st.sidebar.number_input("Kinh độ",value=105.35,format="%.4f")

st.title("⚡ EVN Forecast 1.1 – Điện lực Thường Xuân")
st.caption("Dashboard thích ứng • Cập nhật tháng mới • Lưu Model State • Word/PDF tự động")

# load files
frames=[]
for year,obj in [(2025,f2025),(2026,f2026)]:
    if obj is not None:
        try: frames.append(parse_customer_file(obj,year))
        except Exception as e: st.error(f"Không đọc được file {year}: {e}")
if update_btn and new_month_file is not None:
    try:
        nm=parse_customer_file(new_month_file,int(new_year))
        frames.append(nm)
        st.session_state.model_state["events"].append({"time":datetime.now().isoformat(timespec="seconds"),"type":"monthly_update","year":int(new_year),"file":new_month_file.name})
        st.success("Đã nạp file tháng mới vào phiên phân tích. Hãy kiểm tra Dashboard và bấm 'Lưu Model State' sau khi xem kết quả.")
    except Exception as e: st.error(f"Không cập nhật được tháng mới: {e}")

customer_long=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
monthly=aggregate_monthly(customer_long) if not customer_long.empty else pd.DataFrame(columns=["date","actual"])

history=None
if history_file is not None:
    try:
        history=pd.read_csv(history_file) if history_file.name.lower().endswith('.csv') else pd.read_excel(history_file)
    except Exception as e: st.warning(f"Không đọc được lịch sử tổng: {e}")
series=build_total_series(history,monthly)

if series.empty:
    st.info("Hãy nạp dữ liệu 2025/2026 hoặc lịch sử điện thương phẩm để bắt đầu.")
    st.stop()

# analyses
backtest=compare_models(series)
fc3,weights=forecast_future(series,horizon=3,outage_days=float(outage_days),outage_impact=float(outage_impact)/100.0)
top100=detect_top_influence(customer_long,100) if not customer_long.empty else pd.DataFrame()
latest=series.iloc[-1]
prev=series.iloc[-2] if len(series)>1 else None
latest_month=pd.to_datetime(latest['date']).strftime('%Y_%m')

# weather
weather=None
try: weather=fetch_open_meteo(float(lat),float(lon))
except Exception: pass

# KPIs
c1,c2,c3,c4=st.columns(4)
with c1: card("Tháng mới nhất",pd.to_datetime(latest['date']).strftime('%m/%Y'),"")
with c2: card("Điện thương phẩm",fmt_int(latest['actual'])+" kWh","")
with c3:
    pct=(latest['actual']/prev['actual']-1)*100 if prev is not None and prev['actual'] else 0
    card("So tháng trước",f"{pct:+.2f}%","")
with c4:
    best=backtest.iloc[0] if not backtest.empty else None
    card("MAPE tốt nhất",f"{best['MAPE_1step']:.2f}%" if best is not None else "N/A",str(best['model']) if best is not None else "")

# alert
if not top100.empty:
    extreme=top100[top100['delta_kwh'].abs()>=300000]
    if not extreme.empty:
        st.markdown(f'<div class="alert-card"><b>⚠️ Cảnh báo:</b> phát hiện {len(extreme)} khách hàng biến động tuyệt đối ≥ 300.000 kWh trong tháng gần nhất.</div>',unsafe_allow_html=True)

# tabs
t1,t2,t3,t4,t5,t6=st.tabs(["📊 Dashboard","👥 Top 100","📈 Kiểm định","🔮 Dự báo","💾 Model State","📄 Báo cáo & AI"])

with t1:
    left,right=st.columns([2,1])
    with left:
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=series['date'],y=series['actual'],mode='lines+markers',name='Thực tế'))
        fig.add_trace(go.Scatter(x=fc3['date'],y=fc3['forecast'],mode='lines+markers',name='Dự báo Ensemble',line=dict(dash='dash')))
        fig.update_layout(title="Điện thương phẩm: Thực tế & Dự báo",yaxis_title="kWh",hovermode="x unified",height=430)
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.subheader("Trọng số Adaptive Ensemble")
        wdf=pd.DataFrame({"Mô hình":list(weights.keys()),"Trọng số":list(weights.values())})
        if not wdf.empty:
            st.plotly_chart(px.pie(wdf,names='Mô hình',values='Trọng số',hole=.55),use_container_width=True)
    if weather:
        daily=weather.get('daily',{})
        wdf=pd.DataFrame({"Ngày":daily.get('time',[]),"Tmax":daily.get('temperature_2m_max',[]),"Tmin":daily.get('temperature_2m_min',[]),"Mưa":daily.get('precipitation_sum',[])})
        st.subheader("🌦️ Thời tiết 16 ngày tới")
        st.dataframe(wdf,use_container_width=True,hide_index=True)

with t2:
    if top100.empty: st.info("Cần file khách hàng để phân tích Top 100.")
    else:
        st.dataframe(top100,use_container_width=True,hide_index=True)
        q=st.select_slider("Số khách hàng hiển thị biểu đồ",options=[10,20,30,50],value=20)
        chart=top100.head(q).sort_values('delta_kwh')
        st.plotly_chart(px.bar(chart,x='delta_kwh',y='customer_name',orientation='h',title=f"Top {q} biến động kWh"),use_container_width=True)
        st.download_button("⬇️ Tải Top100 CSV",top100.to_csv(index=False).encode('utf-8-sig'),"Top100_EVN_Forecast_1_1.csv","text/csv")

with t3:
    st.dataframe(backtest,use_container_width=True,hide_index=True)
    if not backtest.empty:
        metric='MAPE_2step' if 'MAPE_2step' in backtest.columns else 'MAPE_1step'
        plot=backtest.dropna(subset=[metric]).sort_values(metric)
        st.plotly_chart(px.bar(plot,x='model',y=metric,text_auto='.2f',title=f"So sánh {metric}"),use_container_width=True)

with t4:
    horizon=st.selectbox("Tầm dự báo",[1,3,6,12],index=1)
    fc,weights_h=forecast_future(series,horizon=horizon,outage_days=float(outage_days),outage_impact=float(outage_impact)/100.0)
    st.dataframe(fc,use_container_width=True,hide_index=True)
    st.write("**Trọng số:**",{k:round(v,4) for k,v in weights_h.items()})
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as writer:
        series.to_excel(writer,sheet_name='Lich_su',index=False)
        fc.to_excel(writer,sheet_name='Du_bao',index=False)
        backtest.to_excel(writer,sheet_name='Backtest',index=False)
        pd.DataFrame([weights_h]).to_excel(writer,sheet_name='Trong_so',index=False)
        if not top100.empty: top100.to_excel(writer,sheet_name='Top100',index=False)
    st.download_button("⬇️ Xuất Excel",out.getvalue(),"EVN_Forecast_1.1_Ket_qua.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with t5:
    st.subheader("Model State")
    st.json(st.session_state.model_state)
    col1,col2=st.columns(2)
    if col1.button("💾 Lưu Model State",type="primary",use_container_width=True):
        state=st.session_state.model_state
        state['latest_month']=latest_month
        state['model_weights']={k:float(v) for k,v in weights.items()}
        state['backtest']=backtest.replace({np.nan:None}).to_dict(orient='records') if not backtest.empty else []
        state['notes']=manual_note
        state['forecast_history'].append({"saved_at":datetime.now().isoformat(timespec='seconds'),"origin":latest_month,"forecast":fc3.assign(date=fc3['date'].astype(str)).to_dict(orient='records')})
        st.session_state.model_state=save_state(state,STATE_PATH)
        st.success("Đã lưu Model State trên server hiện tại.")
    col2.download_button("⬇️ Tải Model State",state_to_bytes(st.session_state.model_state),"model_state.json","application/json",use_container_width=True)
    st.caption("Lưu ý: Streamlit Community Cloud có thể khởi động lại server. Hãy tải model_state.json làm bản sao và khôi phục khi cần.")

with t6:
    st.subheader("Xuất báo cáo tự động")
    docx_bytes=build_docx(series,fc3,backtest,top100,st.session_state.model_state)
    pdf_bytes=build_pdf(series,fc3,backtest,top100,st.session_state.model_state)
    c1,c2=st.columns(2)
    c1.download_button("📘 Xuất Word",docx_bytes,"Bao_cao_EVN_Forecast_1.1.docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document",use_container_width=True)
    c2.download_button("📕 Xuất PDF",pdf_bytes,"Bao_cao_EVN_Forecast_1.1.pdf","application/pdf",use_container_width=True)

    st.subheader("🤖 Phân tích bằng ChatGPT")
    summary=(f"Tháng mới nhất {pd.to_datetime(latest['date']).strftime('%m/%Y')}: {latest['actual']:.0f} kWh.\n"
             f"Backtest:\n{backtest.to_string(index=False)}\nDự báo 3 tháng:\n{fc3.to_string(index=False)}\n"
             f"Trọng số: {weights}. Mất điện: {outage_days} ngày, mức ảnh hưởng {outage_impact}%. Ghi chú: {manual_note}")
    if st.button("🤖 Phân tích bằng ChatGPT",use_container_width=True):
        with st.spinner("Đang phân tích..."):
            txt,err=ai_explain(summary)
        if txt: st.markdown(txt)
        else: st.warning(err)

st.divider()
st.caption("EVN Forecast 1.1 Web • Adaptive Forecast • Model State • Auto Word/PDF")
