# EVN Forecast 1.4 Multi-Model – Điện lực Thường Xuân

Phiên bản này triển khai dự báo theo 5 nhánh và back-test tự động:

1. Thống kê chuỗi thời gian & tăng trưởng 2025–2026.
2. Holt-Winters / seasonal.
3. SARIMA.
4. Hồi quy đa biến với thời tiết, số ngày, ngày nghỉ, mất điện.
5. Bottom-up theo từng khách hàng, ưu tiên Top 100 khách hàng ảnh hưởng lớn.

## Dữ liệu khách hàng
App đọc được cả hai dạng:
- File riêng từng năm có cột `Điện năng tháng 1`, `Điện năng tháng 2`...
- File gộp có cột `Điện năng tháng 1/2025` ... `Điện năng tháng 8/2026`.

Các cột metadata được nhận diện: `MA_KHANG`, `TEN_KHANG`, `MÃ NGÀNH NGHỀ`, `TÊN NGÀNH NGHỀ`, `LOẠI KHÁCH HÀNG`, `CHUOI_GIA`.

## Thời tiết
Khóa cố định địa điểm `Xã Thường Xuân, tỉnh Thanh Hóa` tại tọa độ 19.90389, 105.34889.
- Bảng nhiệt độ ngày: Tmax/Tavg/Tmin.
- Biểu đồ nhiệt độ và lượng mưa.
- Số ngày >=35°C, >=37°C.
- Tổng lượng mưa, số ngày mưa, giờ nắng.
- Tự tổng hợp thành biến tháng cho hồi quy đa biến.
- Phần tháng ngoài 16 ngày dự báo được bổ sung bằng khí hậu lịch sử cùng tháng.

## Mất điện / nguyên nhân sai số
Có thể:
- Upload `Mau_Nhat_ky_mat_dien.xlsx`.
- Hoặc nhập nhanh trên Web: ngày, giờ bắt đầu, giờ kết thúc, Mã KH, nguyên nhân sai số, tỷ lệ ảnh hưởng.

Hệ thống tự tính số giờ mất điện và ước điện năng không thực hiện theo thứ tự: kWh/giờ nhập -> công suất kW -> lịch sử KH -> phụ tải tổng.

## Back-test và lựa chọn mô hình
Mỗi nhánh được kiểm định rolling trên các tháng đã có thực tế. App tính MAPE, MAE, RMSE. Trọng số Adaptive Ensemble được tính theo nghịch đảo bình phương MAPE để mô hình dự báo tốt hơn nhận trọng số cao hơn.

## Deploy
Upload toàn bộ file trong thư mục này lên repository GitHub đang dùng cho Streamlit và Commit vào branch `main`. Streamlit Community Cloud sẽ tự redeploy.

Main file: `streamlit_app.py`

Không đưa API key hoặc dữ liệu khách hàng thật vào repository public.
