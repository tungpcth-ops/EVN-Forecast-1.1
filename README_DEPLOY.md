# EVN Forecast 1.2 Web – Điện lực Thường Xuân

## Điểm mới 1.2
- Nhật ký mất điện theo **ngày + giờ bắt đầu + giờ kết thúc**.
- Danh sách **khách hàng bị mất điện theo từng sự cố**.
- Tự tính số giờ mất điện; hỗ trợ sự cố qua 0 giờ.
- Ước tính điện năng không thực hiện theo từng khách hàng.
- Chuỗi `actual` vẫn giữ nguyên để báo cáo; chuỗi `normalized_actual = actual + lost_kwh` dùng để học xu hướng/dự báo.
- Dashboard hiển thị Thực tế / Chuẩn hóa / Dự báo.
- Model State lưu thêm lịch sử ảnh hưởng mất điện.
- Word/PDF/Excel có phần phân tích mất điện.

## File nhật ký mất điện
Dùng file `Mau_Nhat_ky_mat_dien.xlsx`.

### Sheet `Su_co`
- `SU_CO_ID`
- `NGAY`
- `GIO_BAT_DAU`
- `GIO_KET_THUC`
- `TEN_TBA`
- `PHAM_VI`
- `NGUYEN_NHAN`
- `TY_LE_PHU_TAI_ANH_HUONG`
- `GHI_CHU`

### Sheet `KH_mat_dien`
- `SU_CO_ID`
- `MA_KHANG`
- `TEN_KHANG`
- `KWH_GIO_UOC_TINH` (không bắt buộc)
- `CONG_SUAT_KW` (không bắt buộc)
- `HE_SO_KHUNG_GIO` (không bắt buộc, mặc định 1.0)

Mỗi khách hàng bị ảnh hưởng là một dòng. Một sự cố có nhiều khách hàng thì lặp `SU_CO_ID`.

## Cách ước tính điện năng mất
Ưu tiên theo thứ tự:
1. `KWH_GIO_UOC_TINH` do người dùng nhập.
2. `CONG_SUAT_KW` do người dùng nhập.
3. Điện năng lịch sử của chính khách hàng: trung bình 3 tháng gần nhất, kết hợp cùng kỳ năm trước nếu có.
4. Nếu không có mã khách hàng: phụ tải tổng tháng x số giờ x tỷ lệ ảnh hưởng.

## Deploy
Giữ nguyên các file trong thư mục gốc GitHub và main file là `streamlit_app.py`.
Streamlit Cloud sẽ tự redeploy khi GitHub có commit mới.

## Nâng từ 1.1 lên 1.2 trên GitHub
Tải các file sau đè lên repository cũ:
- `streamlit_app.py`
- `forecast_engine.py`
- `state_manager.py`
- `report_export.py`
- `outage_engine.py` (mới)
- `Mau_Nhat_ky_mat_dien.xlsx` (mới)
- `README_DEPLOY.md`

`requirements.txt` của 1.1 vẫn dùng được.


## Khóa địa điểm thời tiết
Bản cập nhật này cố định nguồn thời tiết cho **Xã Thường Xuân, tỉnh Thanh Hóa** tại tọa độ trung tâm khoảng **19.90389, 105.34889**. Người dùng không thể đổi sang Thọ Xuân/Như Xuân từ giao diện, giúp EVN Forecast sử dụng nhất quán đúng địa bàn quản lý.
