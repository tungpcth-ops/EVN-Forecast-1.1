# EVN Forecast 1.1 Web Deploy

Phiên bản 1.1 bổ sung:
- Nút **Cập nhật tháng mới**.
- **Model State** lưu trọng số, lịch sử backtest, lịch sử dự báo, sự kiện và ghi chú.
- Tải/khôi phục `model_state.json` để sao lưu trạng thái.
- Dashboard mới: KPI cards, biểu đồ thực tế + dự báo, trọng số ensemble, cảnh báo KH biến động lớn.
- Xuất **Excel / Word / PDF** tự động.
- ChatGPT/OpenAI phân tích kết quả nếu cấu hình API key.

## Deploy không cần cài đặt trên máy
1. Giải nén thư mục.
2. Đưa toàn bộ nội dung lên một GitHub repository.
3. Vào https://share.streamlit.io
4. Chọn repository và file `streamlit_app.py`.
5. Bấm Deploy.

## OpenAI API (tùy chọn)
Trong Streamlit Cloud > App settings > Secrets:

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5.6-luna"
```

Không đưa API key vào GitHub.

## Model State
Streamlit Community Cloud có thể khởi động lại server nên file cục bộ không phải lưu trữ bền vững tuyệt đối.
EVN Forecast 1.1 vì vậy có 2 lớp:
1. Lưu `model_state.json` trên server hiện tại.
2. Nút **Tải Model State** để người dùng sao lưu; khi cần dùng **Khôi phục trạng thái**.

Nếu triển khai trên VPS/server ổn định, `model_state.json` sẽ được giữ theo ổ đĩa của server.

## Quy trình hàng tháng
1. Nạp dữ liệu nền (hoặc khôi phục Model State).
2. Nạp file có tháng mới.
3. Bấm **Cập nhật tháng mới**.
4. Xem Dashboard, Top 100, Backtest.
5. Điều chỉnh số ngày mất điện / ghi chú vận hành nếu có.
6. Bấm **Lưu Model State**.
7. Xuất Excel/Word/PDF.

## Cấu trúc
- `streamlit_app.py`: giao diện web.
- `forecast_engine.py`: mô hình dự báo và backtest.
- `state_manager.py`: lưu/khôi phục Model State.
- `report_export.py`: xuất Word/PDF.
- `requirements.txt`: thư viện.
- `.streamlit/`: cấu hình deploy.
