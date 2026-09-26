import json
import os
from typing import Any, Dict


def get_openai_config(st=None):
    """Resolve API configuration from Streamlit secrets first, then env vars."""
    api_key = None
    model = None
    if st is not None:
        try:
            api_key = st.secrets.get("OPENAI_API_KEY")
            model = st.secrets.get("OPENAI_MODEL")
        except Exception:
            pass
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    model = model or os.getenv("OPENAI_MODEL") or "gpt-5.6-terra"
    return api_key, model


def _clean(obj: Any):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(x) for x in obj]
    try:
        import numpy as np
        import pandas as pd
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        if pd.isna(obj):
            return None
    except Exception:
        pass
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def to_json_text(payload: Dict[str, Any]) -> str:
    return json.dumps(_clean(payload), ensure_ascii=False, indent=2)


def ask_openai(api_key: str, model: str, task: str, payload: Dict[str, Any], user_question: str = "") -> str:
    if not api_key:
        raise ValueError("Chưa cấu hình OPENAI_API_KEY trong Streamlit Secrets hoặc biến môi trường.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    instructions = (
        "Bạn là trợ lý phân tích EVN Forecast cho Điện lực Thường Xuân. "
        "Chỉ sử dụng dữ liệu trong ngữ cảnh được cung cấp; không tự bịa số liệu. "
        "Phân biệt rõ số thực tế, dự báo, ước tính mất điện, và suy luận. "
        "Ưu tiên giải thích được: mô hình, MAPE/MAE/RMSE, thời tiết, mùa vụ, mất điện, "
        "ngành nghề và khách hàng ảnh hưởng. Nếu dữ liệu thiếu thì nói rõ thiếu gì. "
        "Viết tiếng Việt, ngắn gọn, phù hợp văn phong báo cáo ngành điện."
    )
    prompt = f"""NHIỆM VỤ: {task}

CÂU HỎI BỔ SUNG CỦA NGƯỜI DÙNG:
{user_question or '(không có)'}

DỮ LIỆU TÓM TẮT EVN FORECAST:
{to_json_text(payload)}

YÊU CẦU ĐẦU RA:
- Nêu kết luận chính trước.
- Dẫn số cụ thể từ dữ liệu khi có.
- Nếu phân tích sai số, tách nguyên nhân định lượng được và nguyên nhân cần xác minh.
- Không thay đổi kết quả tính toán của app nếu không có căn cứ.
- Đề xuất hành động cập nhật mô hình cho tháng tiếp theo khi phù hợp.
"""
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
    )
    return response.output_text
