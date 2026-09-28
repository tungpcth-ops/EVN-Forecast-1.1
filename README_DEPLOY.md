# EVN Forecast 1.5.2 – Dữ liệu nền nạp 1 lần

## Quy trình vận hành hàng tháng

1. **Lần đầu**: mở mục `📚 Dữ liệu nền` và nạp file gộp 2025–2026 (hoặc file riêng 2025 + 2026), sau đó bấm **💾 Lưu dữ liệu nền**.
2. App lưu lịch sử khách hàng vào `data_store/customer_history.pkl.gz` và Model State vào `model_state.json`.
3. **Các tháng sau**: chỉ tải file tháng mới tại `➕ Cập nhật tháng mới` rồi bấm **➕ Cập nhật vào lịch sử**.
4. App ghép theo `Mã KH + tháng`, ưu tiên số liệu file mới nếu trùng, sau đó tự chạy lại 5 mô hình.
5. App tự lưu snapshot dự báo theo tháng dữ liệu gần nhất. Khi có số thực tế tháng sau, tab `🎯 Đối chiếu sai số` tự tính sai số dự báo–thực tế, MAPE/MAE/RMSE/Bias và xếp hạng lại mô hình.
6. Adaptive Ensemble dùng kết quả back-test mới để cập nhật trọng số cho kỳ tiếp theo.

## Sao lưu dữ liệu

Trong sidebar có `Sao lưu / Khôi phục dữ liệu`:
- **⬇️ Tải gói sao lưu dữ liệu**: chứa dữ liệu khách hàng đã ghép, lịch sử tổng, metadata và Model State.
- **♻️ Khôi phục dữ liệu**: dùng file backup `.zip` nếu Streamlit bị reset.

> Lưu ý: Streamlit Community Cloud không cam kết ổ đĩa cục bộ tồn tại vĩnh viễn sau restart/redeploy. Vì vậy để đạt đúng mục tiêu “file nền chỉ nạp một lần” trong vận hành bình thường, app lưu local; đồng thời nên tải gói backup sau mỗi lần cập nhật tháng mới. Nếu cần lưu vĩnh viễn hoàn toàn tự động, bước tiếp theo nên dùng Supabase/PostgreSQL hoặc Google Drive làm kho dữ liệu ngoài.

## Cập nhật web

Upload toàn bộ file của bản này lên repository GitHub hiện tại và Commit vào `main`. Streamlit sẽ redeploy tự động.
