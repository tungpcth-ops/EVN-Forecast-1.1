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
        for p in [CUSTOMERS_PATH, TOTAL_HISTORY_PATH, META_PATH, STATE_PATH]:
            if p.exists():
                z.write(p, arcname=p.name if p == STATE_PATH else f'data_store/{p.name}')
    return bio.getvalue()


def restore_bundle(raw: bytes) -> dict:
    _ensure_dir()
    with zipfile.ZipFile(io.BytesIO(raw), 'r') as z:
        allowed = {
            'data_store/customer_history.pkl.gz': CUSTOMERS_PATH,
            'data_store/total_history.pkl.gz': TOTAL_HISTORY_PATH,
            'data_store/data_meta.json': META_PATH,
            'model_state.json': STATE_PATH,
        }
        for name, target in allowed.items():
            if name in z.namelist():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    return load_meta()
