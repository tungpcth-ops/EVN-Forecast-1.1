# EVN Forecast 1.5.4 Web – KH dự báo cứng

## Điểm mới 1.5.4

Bổ sung **Khách hàng dự báo điện năng cứng** cho các KH đã làm việc và thống nhất sản lượng tháng.

### Nguyên tắc tính
- Với KH đã có số chốt trong tháng mục tiêu, EVN Forecast **không dùng giá trị mô hình** của KH đó.
- Hệ thống ước phần đóng góp mà mô hình đang gán cho nhóm KH cứng, **loại phần đó khỏi từng nhánh mô hình**, rồi **cộng đúng sản lượng đã chốt**.
- Áp dụng cho cả 5 nhánh và Adaptive Ensemble để tránh tính trùng.
- Back-test lịch sử vẫn dùng dữ liệu thực tế lịch sử; số chốt chỉ tác động vào tháng được khai báo.

### Cách nhập
Có 2 cách:
1. Thanh bên → **2) 📌 KH dự báo cứng** → tải `Mau_KH_du_bao_cung.xlsx`, điền và upload.
2. Tab **📌 KH dự báo cứng** → nhập trực tiếp từng dòng.

Các trường:
- `THANG_DU_BAO`
- `MA_KHANG`
- `TEN_KHANG` (có thể để trống, app tự dò)
- `DIEN_NANG_CHOT_KWH`
- `CAN_CU`
- `GHI_CHU`

Nếu nhập lại cùng **Tháng + Mã KH**, bản mới nhất thay bản cũ. Có thể chọn dòng và xóa khi nhập sai.

## Dữ liệu bền vững
Kho dữ liệu/backup gồm:
- lịch sử điện năng KH
- lịch sử tổng
- nhật ký mất điện
- **KH dự báo cứng**
- Model State

## Deploy
Upload toàn bộ file vào repository Streamlit hiện tại và Commit vào `main`. Streamlit tự redeploy.
