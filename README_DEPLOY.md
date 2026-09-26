# EVN Forecast 1.5 AI – Web Deploy

Phiên bản 1.5 bổ sung tab **ChatGPT AI** trên nền EVN Forecast 1.4.1 Multi-Model.

## Chức năng AI
- Phân tích 5 nhánh mô hình và Adaptive Ensemble.
- Giải trình sai số dự báo – thực tế.
- Phân tích tác động thời tiết, mùa vụ, mất điện và Top khách hàng.
- Soạn báo cáo ngắn trình lãnh đạo.
- Ô hỏi tự do “Hỏi AI về dữ liệu dự báo”.
- Lưu lịch sử phân tích AI trong Model State.

## Bảo mật dữ liệu
Mặc định ứng dụng **không gửi toàn bộ file khách hàng lên OpenAI**. Chỉ gửi dữ liệu tổng hợp cần thiết: back-test, forecast, trọng số, sai số, thời tiết, mất điện và Top biến động. Tên khách hàng được ẩn mặc định; chỉ gửi tên khi người dùng bật tùy chọn.

## Cấu hình OpenAI trên Streamlit Cloud
Không ghi API key vào GitHub.

Vào:
`Streamlit > Manage app > Settings > Secrets`

Thêm:
```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5.6-terra"
```

Có thể dùng `gpt-5.6` nếu muốn chất lượng cao hơn. Ứng dụng gọi **OpenAI Responses API** bằng Python SDK chính thức.

## Cập nhật website hiện tại
1. Giải nén ZIP.
2. GitHub repo hiện tại > Add file > Upload files.
3. Kéo toàn bộ file bên trong lên.
4. Commit changes vào `main`.
5. Streamlit tự redeploy.

## Lưu ý
- File `.streamlit/secrets.example.toml` chỉ là mẫu, không chứa khóa thật.
- Nếu dùng ô nhập API key trong app, key chỉ tồn tại trong phiên Streamlit hiện tại và không được ghi vào Model State.
