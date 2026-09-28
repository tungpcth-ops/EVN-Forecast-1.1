# EVN Forecast 1.5.3 Web – Lưu vết nhật ký mất điện

## Điểm mới
- Nhật ký mất điện được lưu vào kho dữ liệu cùng lịch sử khách hàng.
- Mỗi lần Upload hoặc nhập nhanh đều có nút Lưu/Cập nhật và ghi sự kiện vào Model State.
- Có thể chọn từng dòng sai và bấm Xóa; thao tác xóa cũng được lưu vết.
- Gói Sao lưu/Khôi phục dữ liệu đã bao gồm `outage_history.pkl.gz`.
- `TY_LE_PHU_TAI_ANH_HUONG` không cần nhập tay.

### Công thức tự tính tỷ lệ phụ tải ảnh hưởng
`Tỷ lệ ảnh hưởng = Tổng kWh tháng của các khách hàng bị ảnh hưởng / Tổng kWh toàn đơn vị cùng tháng × 100%`

Nếu tháng sự cố chưa có dữ liệu thực tế, app dùng sản lượng tháng gần nhất trước sự cố để ước tính.

## Cách cập nhật website
1. Giải nén ZIP.
2. GitHub repository EVN Forecast hiện tại → Add file → Upload files.
3. Upload toàn bộ file bên trong thư mục.
4. Commit vào `main`.
5. Streamlit tự redeploy.

## Lưu ý Streamlit Community Cloud
Ổ đĩa cục bộ có thể bị reset khi redeploy. Sau mỗi kỳ cập nhật nên tải `EVN_Forecast_Data_Backup.zip`; file backup đã chứa cả lịch sử khách hàng, tổng điện thương phẩm, nhật ký mất điện và Model State.
