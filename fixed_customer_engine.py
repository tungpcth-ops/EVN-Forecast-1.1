from __future__ import annotations
import re
from datetime import datetime
import pandas as pd
import numpy as np

ALIASES = {
    'forecast_month': ['THANG_DU_BAO','Tháng dự báo','THANG','Tháng','month','forecast_month'],
    'customer_id': ['MA_KHANG','Mã khách hàng','MA_KH','Mã KH','customer_id'],
    'customer_name': ['TEN_KHANG','Tên khách hàng','TEN_KH','Tên KH','customer_name'],
    'fixed_kwh': ['DIEN_NANG_CHOT_KWH','Điện năng chốt (kWh)','DIEN_NANG_DU_BAO','Dự báo cứng kWh','fixed_kwh'],
    'basis': ['CAN_CU','Căn cứ','BIEN_BAN','Biên bản/Kế hoạch','basis'],
    'note': ['GHI_CHU','Ghi chú','note'],
}

def _pick(df, aliases):
    return next((c for c in aliases if c in df.columns), None)

def _parse_month(v):
    if pd.isna(v):
        return pd.NaT
    if isinstance(v, pd.Timestamp):
        return v.to_period('M').to_timestamp()
    s=str(v).strip()
    if not s:
        return pd.NaT
    # Accept MM/YYYY, YYYY-MM, DD/MM/YYYY, Excel-like dates.
    m=re.match(r'^(\d{1,2})[/-](\d{4})$',s)
    if m:
        return pd.Timestamp(year=int(m.group(2)),month=int(m.group(1)),day=1)
    m=re.match(r'^(\d{4})[/-](\d{1,2})$',s)
    if m:
        return pd.Timestamp(year=int(m.group(1)),month=int(m.group(2)),day=1)
    d=pd.to_datetime(s,errors='coerce',dayfirst=True)
    return pd.NaT if pd.isna(d) else d.to_period('M').to_timestamp()

def parse_fixed_forecast_workbook(fileobj) -> pd.DataFrame:
    df=pd.read_excel(fileobj)
    cols={k:_pick(df,v) for k,v in ALIASES.items()}
    required=['forecast_month','customer_id','fixed_kwh']
    miss=[k for k in required if cols.get(k) is None]
    if miss:
        raise ValueError('Thiếu cột bắt buộc: THANG_DU_BAO, MA_KHANG, DIEN_NANG_CHOT_KWH')
    out=pd.DataFrame({
        'forecast_month':df[cols['forecast_month']].map(_parse_month),
        'customer_id':df[cols['customer_id']].astype(str).str.strip(),
        'fixed_kwh':pd.to_numeric(df[cols['fixed_kwh']],errors='coerce'),
    })
    out['customer_name']=df[cols['customer_name']].fillna('').astype(str).str.strip() if cols.get('customer_name') else ''
    out['basis']=df[cols['basis']].fillna('').astype(str).str.strip() if cols.get('basis') else ''
    out['note']=df[cols['note']].fillna('').astype(str).str.strip() if cols.get('note') else ''
    out=out.dropna(subset=['forecast_month','fixed_kwh'])
    out=out[(out.customer_id!='') & (out.fixed_kwh>=0)].copy()
    out['source']='Upload Excel'
    out['saved_at']=datetime.now().isoformat(timespec='seconds')
    return normalize_fixed_forecasts(out)

def normalize_fixed_forecasts(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=['forecast_month','customer_id','customer_name','fixed_kwh','basis','note','source','saved_at','record_id'])
    x=df.copy()
    x['forecast_month']=pd.to_datetime(x['forecast_month'],errors='coerce').dt.to_period('M').dt.to_timestamp()
    x['customer_id']=x['customer_id'].astype(str).str.strip()
    x['customer_name']=x.get('customer_name','').fillna('').astype(str).str.strip() if isinstance(x.get('customer_name',''),pd.Series) else ''
    x['fixed_kwh']=pd.to_numeric(x['fixed_kwh'],errors='coerce')
    for c in ['basis','note','source','saved_at']:
        if c not in x.columns:x[c]=''
        x[c]=x[c].fillna('').astype(str)
    x=x.dropna(subset=['forecast_month','fixed_kwh'])
    x=x[(x.customer_id!='') & (x.fixed_kwh>=0)].copy()
    x['record_id']=x['forecast_month'].dt.strftime('%Y-%m')+'|'+x['customer_id']
    return x.drop_duplicates('record_id',keep='last').sort_values(['forecast_month','customer_id']).reset_index(drop=True)

def enrich_with_customer_names(fixed_df: pd.DataFrame, customer_long: pd.DataFrame) -> pd.DataFrame:
    x=normalize_fixed_forecasts(fixed_df)
    if x.empty or customer_long is None or customer_long.empty:return x
    latest=(customer_long.sort_values('date').drop_duplicates('customer_id',keep='last')
            [['customer_id','customer_name']].copy())
    mp=dict(zip(latest.customer_id.astype(str),latest.customer_name.astype(str)))
    mask=x.customer_name.astype(str).str.strip().eq('') | x.customer_name.astype(str).eq('nan')
    x.loc[mask,'customer_name']=x.loc[mask,'customer_id'].map(mp).fillna('')
    return x

def fixed_summary_for_month(fixed_df: pd.DataFrame, month) -> dict:
    x=normalize_fixed_forecasts(fixed_df)
    m=pd.Timestamp(month).to_period('M').to_timestamp()
    z=x[x.forecast_month==m]
    return {'month':m,'customer_count':int(z.customer_id.nunique()),'fixed_kwh':float(z.fixed_kwh.sum())}
