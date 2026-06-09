# VSF AI Agent Kế Toán — Project State
**Cập nhật:** 2026-06-08 ~17:30  
**Internship:** VGR / Vinsmart Future — Tuần 3/6  
**Repo:** https://github.com/13716/chat_bot  

---

## 🗂️ Cấu trúc project

```
D:\python\VSF\
├── backend/                    ← FastAPI + Python
│   ├── core/
│   │   ├── config.py           ✅ GROQ, GEMINI, DEEPSEEK keys
│   │   ├── logging.py          ✅ Loguru structured JSON logging
│   │   └── middleware.py       ✅ Request trace, X-Request-ID header
│   ├── routers/
│   │   ├── agent.py            ✅ POST /agent/chat, /models, /analyze-file
│   │   ├── accounting.py       ✅ POST /accounting/variance, /bank-recon
│   │   ├── admin.py            ✅ GET /admin/logs, /errors, /metrics
│   │   ├── chat.py             ✅ Chat thông thường
│   │   ├── conversations.py    ✅ CRUD conversations
│   │   └── profile.py          ✅
│   ├── services/
│   │   ├── llm.py              ✅ Fallback chain: Groq→Gemini→Deepseek→OpenAI→Anthropic
│   │   ├── accounting.py       ✅ parse_excel, flag_variance, reconcile_bank (33 TDD)
│   │   └── file_analyzer.py    ✅ Excel/CSV/PDF/Word/Image → summary + tool suggestions
│   ├── scripts/
│   │   └── ingest_laws.py      ✅ RAG ingestion pipeline (checkpoint + fallback models)
│   ├── data/
│   │   ├── Thong-tu-99-2025-TT-BTC-huong-dan-Che-do-ke-toan-doanh-nghiep.pdf  ← 622 trang
│   │   └── checkpoints/        ← Checkpoint files cho ingestion
│   ├── logs/
│   │   ├── app_2026-06-05.log  ✅ JSON structured logs
│   │   └── error_2026-06-05.log
│   ├── main.py                 ✅ FastAPI app, middleware, routers
│   └── system_promt.md         ✅ System prompt VAS + TT200 + tool guide
├── frontend/                   ← Next.js 16 + Tailwind v4
│   ├── app/
│   │   ├── page.tsx            ✅ → AgentChatWindow
│   │   ├── globals.css         ✅ @import "tailwindcss" + @source
│   │   └── layout.tsx
│   ├── components/
│   │   ├── AgentChatWindow.tsx ✅ UI chính ChatGPT-style
│   │   ├── AccountingUpload.tsx ✅ UI upload cũ (giữ lại)
│   │   └── ProfileSettings.tsx
│   └── lib/
│       └── api.tsx             ✅ streamAgentChat, getAgentModels, analyzeFile
├── RAG_FLOWCHART.md            ✅ 5 Mermaid pipeline diagrams
└── PROJECT_STATE.md            ← File này
```

---

## ✅ Hoàn thành

### Backend
- **UC#2 Variance Analysis**: parse_excel_variance → flag_variance → LLM commentary (SSE stream)
- **UC#5 Bank Reconciliation**: parse_excel_bank → fuzzy match → LLM commentary (SSE stream)
- **Agent tool-calling**: Groq llama-3.3-70b, detect intent từ chat, auto-execute khi có file
- **Model selector**: 4 models (Groq 70B, 8B, Gemma, Deepseek)
- **File Analyzer**: Excel/CSV/PDF/Word/Image → summary + tool suggestions
- **LLM Fallback chain**: Deepseek→Groq→Gemini→OpenAI→Anthropic
- **System prompt**: load từ `system_promt.md` + tool guide bằng tiếng Việt
- **Logging & Tracing**: loguru JSON, X-Request-ID header, /admin/logs, /admin/errors, /admin/metrics
- **RAG Ingestion script**: checkpoint sau mỗi batch, fallback 4 Gemini models, --resume flag

### Frontend
- **AgentChatWindow**: ChatGPT-style layout, sidebar lịch sử, model selector, output format MD/JSON/HTML
- **File upload**: drag & drop, multi-file, phân tích nhanh, gợi ý tool
- **Tool auto-execute**: khi file đính kèm → chạy ngay không hỏi lại
- **Rich output**: markdown render, code blocks với Copy + Download buttons
- **Conversation history**: localStorage persistence, không mất khi reload

### Infrastructure
- **pgvector**: Bảng `law_chunks` (vector 384 chiều) đã tạo trong Supabase
- **Logging**: JSON logs hàng ngày, rotation 30 ngày, error log riêng
- **Middleware**: Request ID, duration tracking, unhandled exception capture

---

## ⏳ Đang chờ

### RAG Ingestion (TT99/2025)
- **File**: `D:\python\VSF\data\Thong-tu-99-2025-TT-BTC-huong-dan-Che-do-ke-toan-doanh-nghiep.pdf`
- **Trạng thái**: Chưa chạy lại (đã có script mới với checkpoint + fallback)
- **Vấn đề**: Gemini 2.5-flash free tier chỉ 20 req/ngày, key mới đã điền nhưng lại bị quota
- **Checkpoint**: Trống (chưa có trang nào được lưu)
- **Lệnh chạy**:
  ```powershell
  cd D:\python\VSF\backend
  D:\python\VSF\venv\Scripts\python.exe scripts\ingest_laws.py `
    --file "D:\python\VSF\data\Thong-tu-99-2025-TT-BTC-huong-dan-Che-do-ke-toan-doanh-nghiep.pdf" `
    --source "TT99/2025"
  # Nếu bị dừng: thêm --resume để tiếp tục
  ```

---

## ✅ Mới hoàn thành (2026-06-05)

### RAG Pipeline [XONG]
- **`backend/services/rag/intent.py`** — rule-based intent detection (legal/tool/general)
- **`backend/services/rag/retriever.py`** — pgvector cosine search, lazy embedding, graceful fallback
- **`backend/routers/agent.py`** — RAG augmentation: detect_intent → retrieve → augment sys_prompt
- **`frontend/lib/api.tsx`** — thêm `Citation` type + `onCitations` callback
- **`frontend/components/AgentChatWindow.tsx`** — citation badges hiển thị sau response pháp lý
- SSE event mới: `__CITATIONS__` trước `[DONE]`

⚠️ **RAG sẽ hoạt động đầy đủ sau khi chạy full ingestion 622 trang** (hiện chỉ có ~10 trang, articles 17-23)

### Bug fixes cuối ngày [XONG 2026-06-05 ~18:30]

#### RAG - Hybrid Article Filter
- **`backend/services/rag/retriever.py`** — thêm `_extract_article_num()`: khi hỏi "Điều X", filter trực tiếp theo `article='X'` thay vì cosine search → không bị miss do câu ngắn
- Fallback: nếu Điều X chưa có trong DB → vector search bình thường
- Khi không tìm thấy gì → thêm disclaimer vào sys_prompt, LLM không bịa citation

#### Tool routing - Intent-based gating
- **`backend/routers/agent.py`** — `use_tools = tool_capable AND intent == "tool"` 
- intent=`legal` và `general` stream thẳng, **không đi qua tool-calling loop**
- Ngăn LLM gọi nhầm `analyze_financial_statement` khi hỏi câu pháp lý có file đính kèm

#### Bank Reconciliation - Flexible column detection
- **`backend/services/accounting.py`** — `_norm_col()` + `_detect_bank_col()`: 3-lớp matching (exact → substring → reverse-substring) + `unicodedata` strip dấu
- Fallback: nếu không detect được → dùng cột text đầu tiên làm vendor, cột số đầu tiên làm amount
- Sửa bug 422: `tool_args = tc.get("arguments") or {}` (thay vì `.get("arguments", {})` bị None)

#### Tool guard - Non-Excel file
- **`frontend/components/AgentChatWindow.tsx`** — khi tool bị trigger nhưng không có Excel → hiện thông báo và bỏ qua, không crash

---

### UC#1 Financial Statement Reader [XONG 2026-06-05]
- **`backend/services/financial_statement.py`** — parse BCTC Excel (2 sheet CĐKT + KQKD), compute 8 ratios, flag status
- **`backend/routers/agent.py`** — tool `analyze_financial_statement` + `_run_fs` handler
- **`frontend/lib/api.tsx`** — `FSRatio` type, `AgentMeta.ratios`
- **`frontend/components/AgentChatWindow.tsx`** — `RatioTags` component, tool card, CSS badges
- File mẫu: `data/BCTC_mau_2025.xlsx`
- Test: parse 11 chỉ tiêu ✅, 8 ratios ✅, flag 3 WARNING ✅

---

## ✅ Mới hoàn thành (2026-06-08 Tuần 3)

### RAG Full Ingestion batch 1 [XONG 09:10]
- **Trang 0–50** (50 trang đầu TT99/2025) → **164 chunks** vào pgvector
- 148,746 ký tự, Điều 1–50 coverage
- Tiếp tục batch 2 (trang 51–100) ngày mai với --resume

### UC#7 AR/AP Aging Analysis [XONG 2026-06-08]
- **`backend/services/aging.py`** — parse_excel_aging, summarize_aging, build_aging_prompt
  - Column detect 3-lớp (Unicode + fuzzy) — hỗ trợ dấu/không dấu
  - 5 buckets: Current/1-30/31-60/61-90/>90 ngày
  - Vendor risk scoring: LOW/MEDIUM/HIGH/CRITICAL
  - Due date fallback: invoice_date + payment_terms (default 30 ngày)
- **`backend/routers/agent.py`** — tool `ar_ap_aging`, handler `_run_aging`, param `aging_file`
- **`frontend/lib/api.tsx`** — AgingSummary type, AgingBucketData, AgingVendor, agingFile param
- **`frontend/components/AgentChatWindow.tsx`** — AgingCard component, tool card UI, auto-execute
- **`data/CongNo_AR_mau_2025.xlsx`** — sample 12 invoices, 2.77 tỷ đồng, 4 đối tác
- Test: 12 rows parsed ✅, Risk=HIGH ✅, 40.6% >90 ngày ✅
- **`frontend/tsconfig.json`** — fix ignoreDeprecations từ "6.0" → "5.0" (TS type check clean)

### UC#7 — Test suite + bug fixes column detection [XONG 2026-06-08]
- **`backend/test_aging.py`** — 52 unit tests (bucket/detect/date/risk/parse/edge) → **52/52 PASS**
- Integration test qua POST /agent/chat (SSE) → HTTP 200, meta đúng (file test tạm đã dọn sau khi verify)
- 🐛 Fix bug 1: `_detect_aging_col` đổi từ first-canonical-wins → **longest-match-wins**
  - Cũ: alias generic "ngày" (invoice_date) nuốt cột "Ngày đến hạn" (due_date) → code đoán due=invoice+30
  - Mới: exact match ưu tiên tuyệt đối, rồi chọn alias dài nhất (cụ thể nhất)
- 🐛 Fix bug 2: thêm alias viết tắt "số hđ/so hd/mã hđ" → nhận đúng cột "Số HĐ" (trước trả None)

### Charts visualization (Recharts) [XONG 2026-06-08]
- **`frontend/components/AgentCharts.tsx`** — recharts 3.8.1, 3 chart client-only (`next/dynamic {ssr:false}`):
  - **AgingChart** (UC#7): bar phân bổ tuổi nợ, màu theo rủi ro xanh→đỏ
  - **ActualVsBudgetChart** (UC#2): grouped horizontal bar Thực tế vs Kế hoạch
  - **VarianceWaterfall** (UC#2): waterfall chênh lệch tích lũy (Favorable/Unfavorable + cột Tổng)
- **`backend/routers/agent.py`** — `_run_variance` meta thêm `flagged_items` (budget/actual/variance_abs, sort |var| cap 12)
- **`frontend/lib/api.tsx`** — type `VarianceChartItem`, thêm `flagged_items` vào `AgentMeta`
- **`frontend/components/AgentChatWindow.tsx`** — render chart cạnh AgingCard + khi có flagged_items; CSS `.ag-chart-card`
- **`data/Variance_mau_2025.xlsx`** — sample 8 khoản mục, 5 vượt ngưỡng
- Light theme khớp app, tooltip tiếng Việt. Verify: `next build` 0 errors, tsc 0 errors, HTTP variance trả 5 flagged_items đủ data

### Chart UC#1 (BCTC) + Fix Tool Routing [XONG 2026-06-08]
- **`backend/services/financial_statement.py`** — `flag_ratios` thêm `benchmark_good/benchmark_ok/dir` cho chart
- **`frontend/components/AgentCharts.tsx`** — `FSRatioChart`: 2 panel (% và lần), bar Thực tế tô màu theo status + bar Ngưỡng tốt xám; legend tùy chỉnh (Đạt/Cảnh báo/Nguy hiểm)
- 🐛 **Fix bug routing nghiêm trọng** (file Excel + "phân tích báo cáo tài chính" → đi RAG, không chạy tool):
  - **`backend/services/rag/intent.py`**: "báo cáo tài chính" là legal keyword nuốt mất câu phân tích. Thêm keyword UC#1+UC#7 vào `_TOOL_KEYWORDS`; so khớp **không phụ thuộc dấu** (kể cả `đ→d`) → test 12/12
  - **`backend/routers/agent.py`**: File Excel đính kèm → **ép `intent=tool`** (file Word/PDF không ép)
- 🐛 **Fix 503 — Llama tool-calling thất bại** (`tool_use_failed`: Groq Llama sinh `<function=...>` sai định dạng):
  - **`backend/routers/agent.py`** — thêm `_select_tool_by_rules()`: chọn tool theo từ khóa + số file Excel, chạy **TRƯỚC** vòng LLM → nhanh (0.6–2.2s) + chắc chắn, không phụ thuộc Llama
  - 503 thay bằng thông báo hướng dẫn thân thiện
- ✅ Verify end-to-end trên UI: cả 3 UC (BCTC/tuổi nợ/variance) chạy tool đúng + render chart đẹp, không còn 503/RAG

### Pie chart + Rule-based chart selector + fixes [XONG 2026-06-08 ~17:30]
- **`frontend/lib/chartRules.ts`** (MỚI) — `recommendCharts(dataShape)`: chọn loại chart theo đặc tính dữ liệu
  - composition+parts-of-whole+≤6 nhóm → pie+bar | variance → groupedBar+waterfall | có cặp → groupedBar | time → area | mặc định bar
- **`frontend/components/AgentCharts.tsx`** — thêm `AgingPieChart` (donut cơ cấu tuổi nợ); các `*ChartGroup` gọi rule engine + badge "🤖 Biểu đồ đề xuất"
- **`frontend/components/AgentChatWindow.tsx`** — render qua ChartGroup; CSS `.ag-chart-reco`
- 🐛 **Fix legal vs tool** (tác dụng phụ của ép intent): chỉ ép `intent=tool` khi intent=`general`. Câu "...đúng pháp lý chưa" (intent=legal) → giữ RAG. Verify 3/3
- 🐛 **Fix "Maximum update depth" (loop vô hạn)**: recharts v3 Pie + `label` callback + animation → thêm `isAnimationActive={false}`. **Verify bằng browser preview**: inject chart vào localStorage + reload → 0 lỗi console, 5 pie sectors + 5 bars render OK
- **`.claude/launch.json`** (gốc project) — config preview cho dev server

## 🔴 Chưa làm

### 1. ~~RAG Batch 2 (trang 50–100)~~ [XONG 2026-06-09 09:25]
- ✅ Append **198 chunks** (13 Gemini calls, 0 lỗi) → DB tổng **362 chunks** (164 batch1 + 198 batch2)
- 🐛 Fix bug `ingest_laws.py`: `--resume` ghi "không xóa data cũ" nhưng vẫn `delete_existing` → thêm tham số `wipe`, `--resume` giờ **append** thật (không thì batch 2 đã xóa batch 1)
- Điều có header: 4 (1, 2, 24, 30) — vẫn thưa vì trang 50–100 chủ yếu phụ lục/biểu mẫu (topic "Khác")
- ✅ **Vector search hoạt động tốt**: test 5/5 query trả nội dung đúng (TK 111, TK 333, doanh thu...), score 0.56–0.72
- Còn lại: trang 100–622 (chạy batch tiếp theo `--start 100 --resume` các ngày sau)

### 2. RAG quality polish
- Sau khi có batch 2: tinh chỉnh min_score, top_k cho retrieval

---

## 🔑 Config hiện tại

```env
GROQ_API_KEY=gsk_a5tfMT...          ✅ Primary LLM
GEMINI_API_KEY=AQ.Ab8RN6...         ⚠️ Key mới, cần verify quota
DEEPSEEK_API_KEY=sk-9da6d...        ❌ Bị block tại VN
DATABASE_URL=postgresql://...supabase...  ✅ pgvector sẵn sàng
```

## Embedding Model
```
Model: all-MiniLM-L6-v2 (offline, cached)
Dimensions: 384
DB schema: vector(384)
Offline mode: HF_HUB_OFFLINE=1
```

## Servers
```
Backend:  http://localhost:8000  (uvicorn --reload)
Frontend: http://localhost:3000  (npm run dev)
Venv:     D:\python\VSF\venv\Scripts\python.exe
```

---

## 📋 Kế hoạch tuần tới (Tuần 3)

| Ngày | Việc | Kết quả mong đợi |
|------|------|-----------------|
| T2 8/6 | Chạy RAG ingestion + RAG Retriever | law_chunks đầy đủ, query trả về citations |
| T3 9/6 | Intent Detection + Tích hợp vào Agent | Chat pháp lý có trích dẫn |
| T4 10/6 | UC#1 Financial Statement Reader | Upload BCTC → ratios → commentary |
| T5 11/6 | UC#7 AR/AP Aging + Citation badges | Demo 4 UC hoàn chỉnh |
| T6 12/6 | Test + Polish + Demo prep | Ready to demo |

---

## 📝 Ghi chú kỹ thuật quan trọng

1. **Gemini quota**: free tier 20 req/ngày cho gemini-2.5-flash. Key mới `AQ.Ab8...` format khác thường (53 chars, bắt đầu AQ)
2. **Sentence-transformers**: Phải set `HF_HUB_OFFLINE=1` khi dùng, model cache ở `~/.cache/huggingface/hub`
3. **DB connection timeout**: Supabase đóng connection idle sau vài phút → reconnect trước khi save
4. **Vector dimension**: 384 (all-MiniLM-L6-v2) — phải nhất quán cả ingestion lẫn query
5. **Loguru format**: lowercase methods (`logger.info`, `logger.warning`) — KHÔNG phải `logger.INFO`
6. **Windows symlinks**: Cần Developer Mode để sentence-transformers hoạt động bình thường
