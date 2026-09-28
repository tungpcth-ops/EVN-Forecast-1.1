# EVN Forecast 1.5.1 – Trợ lý ChatGPT không cần API key

Phiên bản 1.5.1 giữ nguyên toàn bộ EVN Forecast Multi-Model và thay phần gọi OpenAI API bằng **Trợ lý ChatGPT tạo prompt**.

## Điểm mới
- Không cần `OPENAI_API_KEY`.
- Không gọi OpenAI API, không phát sinh chi phí API.
- Tab **🤖 Trợ lý ChatGPT** tạo prompt sẵn cho 3 tình huống:
  1. Phân tích dự báo và so sánh 5 nhánh mô hình.
  2. Giải trình sai số dự báo – thực tế.
  3. Soạn báo cáo lãnh đạo.
- Có ô câu hỏi tùy chỉnh.
- Prompt tự mang theo dữ liệu tổng hợp: back-test, MAPE/MAE/RMSE, trọng số Ensemble, forecast, sai số, thời tiết, mất điện và Top biến động khách hàng.
- Mặc định ẩn tên khách hàng; chỉ đưa tên Top KH vào prompt khi người dùng chủ động bật.
- Có khung `st.code` để sao chép nhanh và nút tải prompt `.txt`.

## Quy trình sử dụng
1. Nạp/cập nhật dữ liệu tháng mới và chạy EVN Forecast.
2. Mở tab **🤖 Trợ lý ChatGPT**.
3. Chọn loại prompt cần tạo.
4. Bấm biểu tượng sao chép trên khung prompt hoặc tải file `.txt`.
5. Dán prompt vào cuộc trò chuyện ChatGPT đang sử dụng.

Không cần vào `Streamlit > Manage app > Settings > Secrets` và không cần cấu hình API key.

## Cập nhật web hiện tại
1. Giải nén ZIP.
2. GitHub repo hiện tại > **Add file > Upload files**.
3. Kéo toàn bộ file bên trong lên.
4. Commit vào nhánh `main`.
5. Streamlit tự redeploy.

## Khuyến nghị GitHub
Không upload thư mục `__pycache__`, file `.pyc`, API key, hoặc file dữ liệu khách hàng vào repository public.
