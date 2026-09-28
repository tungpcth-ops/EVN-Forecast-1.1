import json
from typing import Any, Dict


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


def build_chatgpt_prompt(task: str, payload: Dict[str, Any], user_question: str = "") -> str:
    """Build a self-contained prompt that users can copy into ChatGPT without API calls."""
    return f"""Bạn là trợ lý phân tích EVN Forecast cho Điện lực Thường Xuân.

NGUYÊN TẮC PHÂN TÍCH:
- Chỉ sử dụng dữ liệu EVN Forecast trong ngữ cảnh dưới đây; không tự bịa số liệu.
- Phân biệt rõ số thực tế, dự báo, dữ liệu đã chuẩn hóa do mất điện và suy luận.
- Ưu tiên giải thích theo 5 nhánh: thống kê/xu hướng, Holt-Winters/seasonal, SARIMA, hồi quy đa biến, bottom-up khách hàng.
- Khi so sánh mô hình, dùng MAPE/MAE/RMSE/back-test và trọng số Ensemble có trong dữ liệu.
- Phân tích thêm thời tiết xã Thường Xuân, mùa vụ, ngày nghỉ/lễ, mất điện, ngành nghề và biến động Top khách hàng khi dữ liệu có hỗ trợ.
- Nếu dữ liệu thiếu để kết luận nguyên nhân, nêu rõ cần xác minh gì.
- Không thay đổi kết quả tính toán của app nếu không có căn cứ.
- Viết tiếng Việt, ưu tiên số liệu cụ thể, văn phong phù hợp báo cáo ngành điện.

NHIỆM VỤ:
{task}

CÂU HỎI BỔ SUNG CỦA NGƯỜI DÙNG:
{user_question or '(không có)'}

DỮ LIỆU TÓM TẮT EVN FORECAST:
{to_json_text(payload)}

YÊU CẦU ĐẦU RA:
1. Nêu kết luận chính trước.
2. Dẫn số cụ thể từ dữ liệu khi có.
3. Nếu phân tích sai số, tách nguyên nhân định lượng được và nguyên nhân cần xác minh.
4. Nếu phân tích dự báo, đối chiếu 5 nhánh và giải thích vì sao Ensemble/trọng số hiện tại hợp lý hoặc cần thận trọng.
5. Đề xuất hành động cập nhật mô hình cho kỳ tiếp theo.
6. Không sử dụng thông tin ngoài dữ liệu nếu người dùng chưa yêu cầu tìm thêm nguồn bên ngoài.
"""
