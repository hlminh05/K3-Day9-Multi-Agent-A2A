# Báo cáo cá nhân — Multi-Agent E-commerce Dispute Resolution

> Đổi tên file theo mẫu `individual_5SoCuoiMHV_HoVaTen.md` và điền ba trường
> nhận dạng bên dưới trước khi nộp. Các nội dung kỹ thuật đã phản ánh đúng
> implementation trong repository, không chứa secret.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | `[CẦN ĐIỀN]` |
| MSSV | `[CẦN ĐIỀN]` |
| Khóa/Lớp | K3 / `[CẦN ĐIỀN]` |
| Vai trò chính | Thiết kế Coordinator, policy pipeline và verification |
| Ngày hoàn thành | 2026-08-05 |

## 2. Phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Agent contracts | `contracts.py` | Domain facts | Immutable handoff | Hoàn thành |
| Orchestration | `coordinator.py` | Case và worker handoff | Draft đã duyệt | Hoàn thành |
| Policy engine | `agents/policy.py` | Order/payment/delivery | `PolicyDecision` | Hoàn thành |
| Independent verification | `agents/verifier.py` | Draft và CSV gốc | accept/reject | Hoàn thành |
| Artifact pipeline | `pipeline.py` | 50 verified result | output, trace, metadata, ZIP | Hoàn thành |
| Tests | `tests/` | Unit và Olist fixture thật | 17 test | Hoàn thành |

## 3. Kết quả bàn giao

- Pipeline xử lý đủ 50 input và tạo đúng 50 output JSON.
- Kết quả gồm 8 `canceled_order_paid`, 8 `unavailable_order_paid`, 8
  `late_delivery_seller`, 8 `late_delivery_logistics`, 9
  `valid_split_payment` và 9 `unsupported_late_claim`.
- Mỗi case tạo 13 trace event; toàn bộ run có 650 event và 300 lần gọi
  `qwen/qwen3-8b`, thể hiện task assignment và handoff thật giữa các agent.
- Verifier kiểm tra lại evidence ID, entity, số tiền, policy và schema từ CSV.
- `output.zip` chỉ chứa 50 file `EC_001.json` đến `EC_050.json`.

Lệnh xác minh:

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m ecommerce_dispute.cli --root . --zip
```

Kết quả mong đợi và thực tế: 17 test pass; CLI báo `case_count=50`,
`trace_event_count=650` và `model_calls=300`.

## 4. Giải thích kỹ thuật

### Vấn đề cần giải quyết

Một phản ánh của khách hàng không đủ để xác định trách nhiệm. Hệ thống phải
join order với item, seller và payment; so sánh ba mốc delivery; sau đó áp dụng
policy theo đúng độ ưu tiên. Mọi kết luận và evidence phải tồn tại trong CSV.

### Cách triển khai

`OlistRepository` nạp và index CSV một lần. Coordinator giữ quyền điều phối duy
nhất và lần lượt giao việc cho Order & Seller Agent, Payment Agent, Delivery
Agent và Policy Agent. Mỗi agent gọi chung `qwen/qwen3-8b` qua OpenRouter để review phần
việc được giao. Kết quả model được lưu trong `LLMReview` rồi so sánh với
guardrail. Kết quả giữa các agent được truyền bằng frozen dataclass, không phải
mutable dictionary dùng chung. Verifier gọi model audit và thực hiện một phép
đối soát độc lập trên CSV; draft chỉ được ghi sau khi guardrail không còn lỗi.

Các phép tính dùng `Decimal`; payment được coi là khớp khi chênh lệch với
`item + freight` không quá `0.10 BRL`, sau đó mới chuyển sang float hai chữ số
cho schema output. Order không có item vẫn có item và freight total bằng `0.0`.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `input/EC_001.json` ... `EC_050.json`, 9 Olist CSV |
| Output | 50 JSON theo schema README, `trace.jsonl`, `metadata.json`, `output.zip` |
| Contract | Frozen dataclass trong `contracts.py` |
| Điều kiện lỗi | Thiếu input, order không tồn tại, policy không hỗ trợ, case không khớp rule, evidence/schema/money sai |

## 5. Quyết định kỹ thuật quan trọng

- **Bối cảnh:** Có thể dùng LLM nhỏ để suy luận từng case hoặc dùng agent theo
  quy tắc xác định.
- **Phương án đã cân nhắc:** (1) gọi model dưới 10B cho mọi worker; (2) worker
  deterministic, typed handoff và verifier độc lập.
- **Phương án chọn:** Hybrid agent dùng Qwen3-8B (8.2B) cùng deterministic guardrail.
- **Lý do:** Model đáp ứng yêu cầu agent dùng LLM dưới 10B và hỗ trợ tiếng Việt,
  JSON/tool workflow. Policy là bảng điều kiện đóng nên phép tính/ID vẫn phải do
  code xác minh để ngăn hallucination và bảo đảm tái lập.
- **Bằng chứng:** 17 test pass trên toàn bộ 50 case; metadata ghi 300 model call;
  evidence giả bị Verifier từ chối; output ZIP vượt qua hard gate.

## 6. Lỗi/blocker đã xử lý

- **Triệu chứng:** File báo cáo mẫu cũ chứa câu hỏi Crossref/vector index không
  liên quan tới bài Olist và dễ dẫn tới báo cáo sai phạm vi.
- **Nguyên nhân:** Template từ một lab retrieval trước đó được giữ lại trong repo.
- **Cách xử lý:** Thay nội dung bằng luồng Olist end-to-end, contract, policy,
  verifier và lệnh test thực tế.
- **Cách xác minh:** So sánh artifact được mô tả với `architecture.md`, source và
  output của CLI.
- **Bài học:** Tài liệu cũng cần được kiểm tra theo đúng domain giống như code.

## 7. Hiểu biết end-to-end

Input cung cấp `claimed_order_id`. Order & Seller Agent dùng ID này truy vấn
order và item, xác định seller cùng việc carrier nhận hàng trước hay sau
`shipping_limit_date`. Payment Agent cộng từng `payment_value`, tuyệt đối không
nhân với installment, rồi đối soát với item cộng freight. Delivery Agent so
sánh ngày giao thực tế với ngày ước tính. Policy Agent áp dụng sáu rule theo
đúng thứ tự. Verifier tự truy vấn CSV để loại evidence không tồn tại và kiểm
tra lại tiền, entity, nguyên nhân, trách nhiệm, action. Cuối cùng single writer
ghi đủ bộ output và trace lượt chạy mới nhất; ZIP gate bảo đảm file nộp không
chứa artifact ngoài 50 JSON.

## 8. Cam kết

- [ ] Tôi đã điền và kiểm tra thông tin cá nhân/tên file.
- [x] Nội dung kỹ thuật khớp với source và artifact trong repo.
- [x] Tôi có thể giải thích luồng end-to-end và thứ tự policy.
- [x] Các kết quả được nêu đều có test hoặc artifact xác minh.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.

**Họ và tên:** `[CẦN ĐIỀN]`

**Ngày xác nhận:** `[CẦN ĐIỀN]`
