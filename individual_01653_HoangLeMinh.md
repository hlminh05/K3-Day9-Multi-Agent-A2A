# Báo cáo cá nhân — Multi-Agent E-commerce Dispute Resolution

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Hoàng Lê Minh |
| Mã học viên | 01653 |
| Khóa/Lớp | K3 |
| Vai trò chính | Thiết kế Coordinator, policy pipeline và verification |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Agent contracts | `src/ecommerce_dispute/contracts.py` | Domain facts | Immutable handoff | Hoàn thành |
| Orchestration | `src/ecommerce_dispute/coordinator.py` | Case và worker handoff | Draft đã duyệt | Hoàn thành |
| Policy engine | `src/ecommerce_dispute/agents/policy.py` | Order/payment/delivery | `PolicyDecision` | Hoàn thành |
| Independent verification | `src/ecommerce_dispute/agents/verifier.py` | Draft và CSV gốc | Accept/reject | Hoàn thành |
| OpenRouter gateway | `src/ecommerce_dispute/llm.py` | Prompt đã ẩn danh | Structured JSON | Hoàn thành |
| Artifact pipeline | `src/ecommerce_dispute/pipeline.py` | 50 verified result | Output, trace, metadata, ZIP | Hoàn thành |
| Tests | `tests/` | Unit và Olist fixture thật | 19 test | Hoàn thành |

## 3. Kết quả theo vai trò

- Pipeline đọc đủ 50 input và tạo đúng 50 output JSON theo schema README.
- Phân phối policy đã kiểm chứng: 8 `canceled_order_paid`, 8
  `unavailable_order_paid`, 8 `late_delivery_seller`, 8
  `late_delivery_logistics`, 9 `valid_split_payment` và 9
  `unsupported_late_claim`.
- Coordinator là agent cha duy nhất; worker không gọi nhau và không ghi file.
- Model được khóa cứng tại `qwen/qwen3-8b`, 8.2B tham số, dưới giới hạn 10B.
- OpenRouter smoke test đã xác nhận key, exact model identity và structured JSON.
- 19/19 test pass, bao gồm model hard gate, false evidence, anonymized API
  payload, 50-case integration và ZIP hard gate.
- `output.zip` chứa thư mục `output/` với `EC_001.json` đến `EC_050.json`,
  không chứa `.gitkeep`.

Lệnh xác minh:

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m ecommerce_dispute.cli --root . --zip
```

## 4. Giải thích phần kỹ thuật

### Vấn đề cần giải quyết

Nội dung khiếu nại không đủ để xác định trách nhiệm. Pipeline phải truy vấn
order, item, seller và payment; so sánh mốc giao hàng; sau đó áp dụng policy
theo đúng thứ tự. Mọi kết luận và evidence ID phải kiểm chứng được từ CSV.

### Cách triển khai

`OlistRepository` nạp và index CSV một lần. Coordinator lần lượt giao việc cho
Order & Seller Agent, Payment Agent, Delivery Agent và Policy Agent. Mỗi agent
gọi chung model `qwen/qwen3-8b` qua OpenRouter với prompt đã ẩn danh. Kết quả
model được lưu trong `LLMReview` rồi so sánh với deterministic guardrail.

Các handoff là frozen dataclass, không phải dictionary mutable dùng chung.
Verifier tự đọc lại CSV để kiểm tra issue, entity, evidence, số tiền, root cause,
responsible party và action. Chỉ Artifact Writer được ghi output sau khi
Verifier chấp nhận.

Phép tính tiền sử dụng `Decimal`. Payment được đối soát với `item + freight`
trong sai số `0.10 BRL`. `payment_value` được cộng theo từng payment row, không
nhân với số installment. Kết quả tiền được làm tròn hai chữ số cho output.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `input/EC_001.json` ... `EC_050.json`, các CSV Olist |
| Output | 50 JSON, `trace.jsonl`, `metadata.json`, `output.zip` |
| Handoff | Frozen dataclass trong `contracts.py` |
| Lỗi fail-closed | Thiếu key, sai model, order không tồn tại, policy không khớp, evidence/schema/money sai |

### Bảo vệ dữ liệu

API key chỉ nằm trong `.env`, được `.gitignore` loại trừ và không xuất hiện
trong trace. Tên model, provider, endpoint và parameter size được khai báo trong
source. Prompt API không gửi customer message, ID, evidence ID, timestamp thô
hoặc tổng giá trị đơn hàng; chỉ gửi count, boolean và chênh lệch đối soát tối
thiểu.

## 5. Quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần chứng minh agent sử dụng model dưới 10B nhưng output tài
  chính và evidence phải chính xác tuyệt đối.
- **Phương án đã cân nhắc:** LLM quyết định toàn bộ; rule-only; hoặc hybrid
  LLM cùng deterministic guardrail.
- **Phương án chọn:** Hybrid với `qwen/qwen3-8b` qua OpenRouter.
- **Lý do:** Qwen3-8B đáp ứng giới hạn 10B và structured workflow; code vẫn giữ
  CSV, phép tính tiền và policy làm nguồn sự thật để ngăn hallucination.
- **Bằng chứng:** 19 test pass; provider không thể thay bằng model lớn; evidence
  giả bị Verifier từ chối; payload không chứa ID 32 ký tự.

## 6. Lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Bản đầu sử dụng deterministic agent nhưng chưa gọi LLM.
- **Nguyên nhân:** Bài toán có policy đóng nên rule engine đã đủ để tính output,
  nhưng chưa thể hiện yêu cầu model của bài lab.
- **Cách xử lý:** Tích hợp OpenRouter gateway và `qwen/qwen3-8b` vào sáu agent,
  bổ sung `LLMReview`, exact-model hard gate, retry và thống kê token/call.
- **Cách xác minh:** Test model identity, giới hạn 8.2B, 300 invocation trong
  50-case integration và fail-closed khi thiếu key hoặc provider trả model khác.
- **Bài học:** Model nên tham gia phân tích, nhưng dữ kiện tài chính và evidence
  vẫn cần guardrail xác định.

## 7. Hiểu biết luồng end-to-end

Input cung cấp `claimed_order_id`. Order & Seller Agent truy vấn order/item và
xác định seller bàn giao sau `shipping_limit_date`. Payment Agent cộng từng
`payment_value` rồi đối soát với item cộng freight. Delivery Agent so sánh ngày
giao thực tế với ngày ước tính. Policy Agent áp dụng sáu rule theo đúng thứ tự
ưu tiên. Verifier tự truy vấn CSV để loại evidence không tồn tại và kiểm tra lại
tiền, entity, nguyên nhân, trách nhiệm và action. Single writer ghi output,
trace của lượt chạy mới nhất và metadata; ZIP gate chỉ đóng gói 50 JSON.

## 8. Cam kết

- [x] Báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end và thứ tự policy.
- [x] Các kết quả được nêu có test hoặc artifact xác minh.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Tên file chứa đúng năm số cuối mã học viên và họ tên.

**Họ và tên:** Hoàng Lê Minh

**Mã học viên:** 01653

**Ngày xác nhận:** 2026-08-05
