import io
from datetime import datetime
import pandas as pd
from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def _fmt(x):
    try:
        return f"{float(x):,.0f}".replace(",", ".")
    except Exception:
        return str(x)


def build_docx(series, forecasts, backtest, top100=None, state=None, title="BÁO CÁO EVN FORECAST 1.1"):
    bio = io.BytesIO()
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(10)
    p = doc.add_paragraph()
    p.alignment = 1
    r = p.add_run(title)
    r.bold = True
    r.font.size = Pt(15)
    p = doc.add_paragraph()
    p.alignment = 1
    p.add_run("Điện lực Thường Xuân").bold = True

    doc.add_heading("1. Tổng quan", level=1)
    latest = series.iloc[-1]
    doc.add_paragraph(f"Tháng dữ liệu mới nhất: {latest['date'].strftime('%m/%Y')}")
    doc.add_paragraph(f"Điện thương phẩm: {_fmt(latest['actual'])} kWh")
    if state:
        doc.add_paragraph(f"Model State: EVNF_{state.get('latest_month') or 'NA'}_v1.1")
        doc.add_paragraph(f"Cập nhật: {state.get('updated_at') or 'Chưa lưu'}")

    doc.add_heading("2. Dự báo", level=1)
    table = doc.add_table(rows=1, cols=3)
    hdr = table.rows[0].cells
    hdr[0].text = "Tháng"
    hdr[1].text = "Dự báo (kWh)"
    hdr[2].text = "Ensemble"
    for _, row in forecasts.iterrows():
        cells = table.add_row().cells
        cells[0].text = pd.to_datetime(row['date']).strftime('%m/%Y')
        cells[1].text = _fmt(row['forecast'])
        cells[2].text = "Adaptive Ensemble"

    doc.add_heading("3. Kiểm định mô hình", level=1)
    if backtest is None or backtest.empty:
        doc.add_paragraph("Chưa đủ dữ liệu để kiểm định.")
    else:
        cols = [c for c in ["model","MAPE_1step","MAPE_2step","MAE_1step","RMSE_1step"] if c in backtest.columns]
        t = doc.add_table(rows=1, cols=len(cols))
        for i,c in enumerate(cols): t.rows[0].cells[i].text = c
        for _, row in backtest.iterrows():
            cells = t.add_row().cells
            for i,c in enumerate(cols):
                v=row[c]
                cells[i].text = f"{v:.2f}" if isinstance(v,(float,int)) and c!="model" else str(v)

    if top100 is not None and not top100.empty:
        doc.add_heading("4. Top 10 khách hàng ảnh hưởng", level=1)
        use = top100.head(10)
        cols = [c for c in ["rank","customer_id","customer_name","latest_kwh","delta_kwh","share_pct","influence_score"] if c in use.columns]
        t = doc.add_table(rows=1, cols=len(cols))
        for i,c in enumerate(cols): t.rows[0].cells[i].text=c
        for _, row in use.iterrows():
            cells=t.add_row().cells
            for i,c in enumerate(cols): cells[i].text=_fmt(row[c]) if c in ["latest_kwh","delta_kwh"] else str(row[c])

    doc.add_paragraph("\nBáo cáo được tạo tự động bởi EVN Forecast 1.1 Web.")
    doc.save(bio)
    return bio.getvalue()


def build_pdf(series, forecasts, backtest, top100=None, state=None, title="EVN Forecast 1.1"):
    bio = io.BytesIO()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=20)
    doc = SimpleDocTemplate(bio, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    story = [Paragraph(title, title_style), Paragraph("Dien luc Thuong Xuan", styles["Heading2"]), Spacer(1,6)]
    latest = series.iloc[-1]
    story += [Paragraph(f"Du lieu moi nhat: {latest['date'].strftime('%m/%Y')} - {_fmt(latest['actual'])} kWh", styles["BodyText"]), Spacer(1,8)]
    if state:
        story += [Paragraph(f"Model State: EVNF_{state.get('latest_month') or 'NA'}_v1.1", styles["BodyText"]), Spacer(1,6)]

    story.append(Paragraph("Du bao", styles["Heading2"]))
    rows=[["Thang","Du bao (kWh)"]]
    for _,r in forecasts.iterrows(): rows.append([pd.to_datetime(r['date']).strftime('%m/%Y'),_fmt(r['forecast'])])
    tbl=Table(rows,colWidths=[45*mm,55*mm])
    tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('GRID',(0,0),(-1,-1),0.4,colors.grey),('ALIGN',(1,1),(-1,-1),'RIGHT')]))
    story += [tbl, Spacer(1,10)]

    story.append(Paragraph("Kiem dinh mo hinh", styles["Heading2"]))
    if backtest is not None and not backtest.empty:
        rows=[["Model","MAPE 1","MAPE 2"]]
        for _,r in backtest.head(8).iterrows(): rows.append([str(r['model']),f"{r.get('MAPE_1step',0):.2f}%",f"{r.get('MAPE_2step',0):.2f}%"])
        tbl=Table(rows,colWidths=[60*mm,35*mm,35*mm])
        tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('GRID',(0,0),(-1,-1),0.4,colors.grey)]))
        story += [tbl, Spacer(1,10)]

    if top100 is not None and not top100.empty:
        story.append(Paragraph("Top 10 khach hang anh huong", styles["Heading2"]))
        rows=[["STT","Khach hang","T7/T8 moi nhat","Delta"]]
        for _,r in top100.head(10).iterrows(): rows.append([str(r.get('rank','')),str(r.get('customer_name',''))[:34],_fmt(r.get('latest_kwh',0)),_fmt(r.get('delta_kwh',0))])
        tbl=Table(rows,colWidths=[12*mm,85*mm,35*mm,35*mm])
        tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('GRID',(0,0),(-1,-1),0.35,colors.grey),('FONTSIZE',(0,0),(-1,-1),7)]))
        story.append(tbl)
    story += [Spacer(1,10), Paragraph("Bao cao duoc tao tu dong boi EVN Forecast 1.1 Web.", styles["BodyText"])]
    doc.build(story)
    return bio.getvalue()
