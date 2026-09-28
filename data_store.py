from __future__ import annotations
import io
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
import pandas as pd

STORE_DIR = Path('data_store')
CUSTOMERS_PATH = STORE_DIR / 'customer_history.pkl.gz'
TOTAL_HISTORY_PATH = STORE_DIR / 'total_history.pkl.gz'
META_PATH = STORE_DIR / 'data_meta.json'
STATE_PATH = Path('model_state.json')
OUTAGE_HISTORY_PATH = STORE_DIR / 'outage_history.pkl.gz'
FIXED_FORECAST_PATH = STORE_DIR / 'fixed_customer_forecasts.pkl.gz'


def _ensure_dir():
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def load_customer_history() -> pd.DataFrame:
    if not CUSTOMERS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_pickle(CUSTOMERS_PATH, compression='gzip')
    except Exception:
        return pd.DataFrame()


def save_customer_history(df: pd.DataFrame) -> None:
    _ensure_dir()
    df.to_pickle(CUSTOMERS_PATH, compression='gzip')
    meta = load_meta()
    meta.update({
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'customer_rows': int(len(df)),
        'customer_count': int(df['customer_id'].nunique()) if 'customer_id' in df.columns and not df.empty else 0,
        'first_month': str(pd.to_datetime(df['date']).min().date()) if 'date' in df.columns and not df.empty else None,
        'latest_month': str(pd.to_datetime(df['date']).max().date()) if 'date' in df.columns and not df.empty else None,
    })
    save_meta(meta)


def load_total_history() -> pd.DataFrame:
    if not TOTAL_HISTORY_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_pickle(TOTAL_HISTORY_PATH, compression='gzip')
    except Exception:
        return pd.DataFrame()


def save_total_history(df: pd.DataFrame) -> None:
    _ensure_dir()
    df.to_pickle(TOTAL_HISTORY_PATH, compression='gzip')


def merge_customer_history(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        out = new.copy()
    elif new is None or new.empty:
        out = old.copy()
    else:
        out = pd.concat([old, new], ignore_index=True)
    if out.empty:
        return out
    out['date'] = pd.to_datetime(out['date']).dt.to_period('M').dt.to_timestamp()
    out['customer_id'] = out['customer_id'].astype(str).str.strip()
    out = out.sort_values('date').drop_duplicates(['customer_id', 'date'], keep='last').reset_index(drop=True)
    return out



def load_outage_history() -> pd.DataFrame:
    if not OUTAGE_HISTORY_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_pickle(OUTAGE_HISTORY_PATH, compression='gzip')
    except Exception:
        return pd.DataFrame()


def save_outage_history(df: pd.DataFrame) -> None:
    _ensure_dir()
    if df is None:
        df = pd.DataFrame()
    df.to_pickle(OUTAGE_HISTORY_PATH, compression='gzip')


def merge_outage_history(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        out = new.copy() if new is not None else pd.DataFrame()
    elif new is None or new.empty:
        out = old.copy()
    else:
        out = pd.concat([old, new], ignore_index=True)
    if out.empty:
        return out
    import hashlib
    def make_id(r):
        raw = '|'.join(str(r.get(k,'')) for k in ['event_id','date','start_time','end_time','customer_id'])
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]
    if 'record_id' not in out.columns:
        out['record_id'] = out.apply(make_id, axis=1)
    else:
        miss = out['record_id'].isna() | out['record_id'].astype(str).str.strip().eq('')
        if miss.any():
            out.loc[miss, 'record_id'] = out.loc[miss].apply(make_id, axis=1)
    if 'date' in out.columns:
        out['date'] = pd.to_datetime(out['date'], errors='coerce')
    out = out.drop_duplicates('record_id', keep='last').reset_index(drop=True)
    return out


def delete_outage_records(record_ids) -> pd.DataFrame:
    df = load_outage_history()
    if df.empty or 'record_id' not in df.columns:
        return df
    ids = {str(x) for x in record_ids}
    df = df[~df['record_id'].astype(str).isin(ids)].reset_index(drop=True)
    save_outage_history(df)
    return df


def load_fixed_forecasts() -> pd.DataFrame:
    if not FIXED_FORECAST_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_pickle(FIXED_FORECAST_PATH, compression='gzip')
    except Exception:
        return pd.DataFrame()


def save_fixed_forecasts(df: pd.DataFrame) -> None:
    _ensure_dir()
    if df is None:
        df = pd.DataFrame()
    df.to_pickle(FIXED_FORECAST_PATH, compression='gzip')


def merge_fixed_forecasts(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    from fixed_customer_engine import normalize_fixed_forecasts
    if old is None or old.empty:
        out = new.copy() if new is not None else pd.DataFrame()
    elif new is None or new.empty:
        out = old.copy()
    else:
        out = pd.concat([old, new], ignore_index=True)
    return normalize_fixed_forecasts(out)


def delete_fixed_forecast_records(record_ids) -> pd.DataFrame:
    df = load_fixed_forecasts()
    if df.empty or 'record_id' not in df.columns:
        return df
    ids = {str(x) for x in record_ids}
    df = df[~df['record_id'].astype(str).isin(ids)].reset_index(drop=True)
    save_fixed_forecasts(df)
    return df

def load_meta() -> dict:
    if not META_PATH.exists():
        return {'created_at': None, 'updated_at': None}
    try:
        return json.loads(META_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'created_at': None, 'updated_at': None}


def save_meta(meta: dict) -> None:
    _ensure_dir()
    meta = dict(meta)
    if not meta.get('created_at'):
        meta['created_at'] = datetime.now().isoformat(timespec='seconds')
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')


def clear_store() -> None:
    if STORE_DIR.exists():
        shutil.rmtree(STORE_DIR)


def backup_bundle_bytes() -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for p in [CUSTOMERS_PATH, TOTAL_HISTORY_PATH, OUTAGE_HISTORY_PATH, FIXED_FORECAST_PATH, META_PATH, STATE_PATH]:
            if p.exists():
                z.write(p, arcname=p.name if p == STATE_PATH else f'data_store/{p.name}')
    return bio.getvalue()


def restore_bundle(raw: bytes) -> dict:
    _ensure_dir()
    with zipfile.ZipFile(io.BytesIO(raw), 'r') as z:
        allowed = {
            'data_store/customer_history.pkl.gz': CUSTOMERS_PATH,
            'data_store/total_history.pkl.gz': TOTAL_HISTORY_PATH,
            'data_store/outage_history.pkl.gz': OUTAGE_HISTORY_PATH,
            'data_store/fixed_customer_forecasts.pkl.gz': FIXED_FORECAST_PATH,
            'data_store/data_meta.json': META_PATH,
            'model_state.json': STATE_PATH,
        }
        for name, target in allowed.items():
            if name in z.namelist():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    return load_meta()
