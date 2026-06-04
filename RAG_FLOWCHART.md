# RAG System — VSF AI Agent Kế Toán
## Flowchart thiết kế trước khi implement

---

## PIPELINE 1 — Ingestion (chạy 1 lần, khi setup)

```mermaid
flowchart TD
    A([🗂️ Văn bản pháp lý\nPDF / Word / TXT]) --> B

    B[📥 Document Loader\ntheo loại file] --> C{Loại file?}

    C -->|PDF| D1[pypdf\nextract text]
    C -->|Word .docx| D2[python-docx\nextract paragraphs]
    C -->|TXT / MD| D3[Đọc thẳng]

    D1 & D2 & D3 --> E[🏷️ Metadata Extraction\n- Tên văn bản: TT200, TT133...\n- Năm ban hành\n- Số điều / khoản]

    E --> F[✂️ Smart Chunking\nchia theo Điều / Khoản]

    F --> G{Chunk hợp lệ?}
    G -->|Quá ngắn < 100 chars| H[❌ Bỏ qua]
    G -->|Quá dài > 1000 chars| I[Chia nhỏ thêm\noverlap 100 chars]
    G -->|Vừa| J[✅ Chunk OK]
    I --> J

    J --> K[🔢 Embedding\nsentence-transformers\nparaphrase-multilingual-mpnet]

    K --> L[(🐘 pgvector\nPostgreSQL\nBảng: law_chunks\n- id, content, embedding\n- source, article, topic)]

    L --> M([✅ Vector Store\nsẵn sàng query])

    style A fill:#dbeafe,stroke:#3b82f6
    style M fill:#d1fae5,stroke:#10b981
    style H fill:#fee2e2,stroke:#ef4444
    style L fill:#ede9fe,stroke:#7c3aed
```

---

## PIPELINE 2 — Query (chạy mỗi khi user hỏi)

```mermaid
flowchart TD
    START([💬 User gửi message]) --> HIST[Lấy conversation history]

    HIST --> INTENT{🧠 Intent Detection\nGroq phân tích câu hỏi}

    INTENT -->|Hỏi pháp lý\n'theo thông tư nào'\n'điều mấy quy định'| RAG_PATH
    INTENT -->|Cần phân tích file Excel\n'variance', 'đối chiếu'| TOOL_PATH
    INTENT -->|Câu hỏi kế toán\nghiệp vụ chung| DIRECT_PATH

    %% RAG Path
    subgraph RAG_PATH [" 📚 RAG Path — Pháp lý "]
        R1[Embed câu hỏi\nsentence-transformers] --> R2
        R2[🔍 Vector Search\npgvector cosine similarity\nTop 5 chunks] --> R3
        R3{Similarity\nscore > 0.7?} -->|Có| R4
        R3 -->|Không đủ| R5[Fallback:\nKhông tìm được văn bản\ntrả lời từ kiến thức LLM]
        R4[📋 Assemble Context\n- Nội dung chunks\n- Source: TT200 Điều 15 K2\n- Trích dẫn chính xác] --> R6
        R6[🏗️ Build Augmented Prompt\n= System Prompt\n+ Law Context\n+ User Question\n+ Format instruction]
        R6 --> LLM
    end

    %% Tool Path
    subgraph TOOL_PATH [" 🔧 Tool Path — Phân tích file "]
        T1[Existing Agent\ntool-calling loop] --> T2
        T2{Có file\nđính kèm?} -->|Có| T3
        T2 -->|Không| T4[Hiện tool card\nyêu cầu upload]
        T3[Execute tool\nanalyze_variance\nbank_reconciliation] --> LLM
        T4 --> T5([Chờ user\nupload file])
    end

    %% Direct Path
    subgraph DIRECT_PATH [" 💡 Direct Path — Nghiệp vụ "]
        D1[System prompt\n+ History\n+ Question] --> LLM
    end

    LLM[🤖 LLM\nGroq / Deepseek] --> RESPONSE

    subgraph RESPONSE [" 📤 Response Assembly "]
        RE1[Nội dung trả lời\nbằng tiếng Việt] --> RE2
        RE2{Có dùng RAG?} -->|Có| RE3
        RE2 -->|Không| RE4[Plain response]
        RE3[Thêm Citation Badges\n📎 TT200 - Điều 15, K2\n📎 TT45 - Điều 9] --> RE4
        RE4 --> RE5[Stream về Frontend\nSSE tokens]
    end

    RE5 --> END([🖥️ Hiển thị\ntrên chat với badges\nkèm download MD/HTML])

    style START fill:#dbeafe,stroke:#3b82f6
    style END fill:#d1fae5,stroke:#10b981
    style LLM fill:#fef3c7,stroke:#f59e0b
    style RAG_PATH fill:#eff6ff,stroke:#3b82f6
    style TOOL_PATH fill:#f0fdf4,stroke:#10b981
    style DIRECT_PATH fill:#fdf4ff,stroke:#a855f7
```

---

## PIPELINE 3 — Tích hợp vào Agent hiện có

```mermaid
flowchart LR
    subgraph FRONTEND ["🖥️ Frontend — AgentChatWindow"]
        UI1[User nhập câu hỏi] --> UI2
        UI2[Đính file nếu có] --> UI3
        UI3[Chọn Model\nChọn Output Format] --> UI4
        UI4[POST /agent/chat\n+ message\n+ history\n+ model_id\n+ files]
    end

    subgraph BACKEND ["⚙️ Backend — /agent/chat"]
        BE1[Nhận request] --> BE2
        BE2[Load System Prompt\nsystem_promt.md] --> BE3
        BE3[🆕 RAG Retrieval\nnếu cần pháp lý] --> BE4
        BE4[Tool Detection\nGroq function calling] --> BE5
        BE5{Quyết định}

        BE5 -->|Direct| BE6[Stream LLM response]
        BE5 -->|RAG| BE7[Stream + citations]
        BE5 -->|Tool| BE8[Execute UC\nstream kết quả + meta]
    end

    subgraph DATABASE ["🗄️ Database — PostgreSQL"]
        DB1[(conversations\nmessages)]
        DB2[(🆕 law_chunks\n+ embeddings)]
        DB3[(🆕 company_profiles)]
    end

    UI4 --> BE1
    BE3 <--> DB2
    BE6 & BE7 & BE8 --> STREAM[SSE Stream\nTokens + META\n+ CITATIONS]
    STREAM --> UI1
    BE1 <--> DB1

    style FRONTEND fill:#eff6ff,stroke:#3b82f6
    style BACKEND fill:#f0fdf4,stroke:#10b981
    style DATABASE fill:#ede9fe,stroke:#7c3aed
    style DB2 fill:#fef3c7,stroke:#f59e0b
    style DB3 fill:#fef3c7,stroke:#f59e0b
```

---

## PIPELINE 4 — Chunking Strategy chi tiết

```mermaid
flowchart TD
    PDF[📄 TT200.pdf\n~200 trang] --> EXTRACT[Extract toàn bộ text]

    EXTRACT --> PARSE[Parse cấu trúc\nRegex theo mẫu VN]

    PARSE --> LEVEL1[Chương I, II, III...]
    LEVEL1 --> LEVEL2[Điều 1, 2, 3...]
    LEVEL2 --> LEVEL3[Khoản 1, 2, 3...]
    LEVEL3 --> LEVEL4[Điểm a, b, c...]

    LEVEL3 --> META[Gán metadata\nsource: TT200\nchapter: Chương II\narticle: Điều 15\ntopic: GTGT khấu trừ]

    META --> SIZE{Kích thước\nchunk}

    SIZE -->|< 150 chars| MERGE[Merge với chunk\nkế tiếp]
    SIZE -->|150-800 chars ✅| EMBED
    SIZE -->|> 800 chars| SPLIT[Split + overlap\n100 chars]

    MERGE & SPLIT --> SIZE
    EMBED[Tạo embedding\nvector 768 dims] --> STORE

    STORE[(pgvector\nlaw_chunks)]

    STORE --> STATS[📊 Thống kê\nTT200: ~850 chunks\nTT133: ~420 chunks\nTT45: ~180 chunks\nTotal: ~2000 chunks]

    style PDF fill:#fee2e2,stroke:#ef4444
    style STORE fill:#ede9fe,stroke:#7c3aed
    style STATS fill:#d1fae5,stroke:#10b981
```

---

## PIPELINE 5 — Response với Citations

```mermaid
flowchart TD
    Q[❓ User hỏi:\n'Điều kiện khấu trừ\nthuế GTGT đầu vào?'] --> EMBED[Embed câu hỏi]

    EMBED --> SEARCH[pgvector search\ncosine similarity]

    SEARCH --> RESULTS[Top 5 chunks\n\n1. TT200 Điều 15 K1 - score 0.92\n2. TT200 Điều 15 K2 - score 0.89\n3. TT219 Điều 12    - score 0.81\n4. TT200 Điều 14 K3 - score 0.74\n5. TT26 Điều 1      - score 0.71]

    RESULTS --> FILTER[Filter score > 0.70\n→ giữ lại 5/5]

    FILTER --> PROMPT[Build prompt:\n---CONTEXT---\nTT200 Điều 15 K1: Thuế GTGT đầu vào\ncủa hàng hoá, dịch vụ...\n\nTT200 Điều 15 K2: Điều kiện cần có\nhóa đơn GTGT hợp lệ...\n---END CONTEXT---\n\nCâu hỏi: Điều kiện khấu trừ GTGT?]

    PROMPT --> LLM[🤖 LLM trả lời\ndựa trên context]

    LLM --> OUTPUT[📤 Kết quả:\n'Theo Thông tư 200/2014,\nĐiều 15, Khoản 1:\nThuế GTGT đầu vào được\nkhấu trừ khi...\n\n📎 TT200 - Điều 15, K1\n📎 TT200 - Điều 15, K2']

    OUTPUT --> STREAM[Stream về chat\n+ Citation badges\n+ Download PDF gốc link]

    style Q fill:#dbeafe,stroke:#3b82f6
    style OUTPUT fill:#d1fae5,stroke:#10b981
    style LLM fill:#fef3c7,stroke:#f59e0b
```

---

## Kế hoạch implement theo ngày

```mermaid
gantt
    title RAG Implementation Plan
    dateFormat  YYYY-MM-DD
    section Setup
    Thu thập văn bản pháp lý (PDF)     :a1, 2026-06-05, 1d
    Setup pgvector + schema             :a2, 2026-06-05, 1d
    section Ingestion
    Document loader + chunking          :b1, 2026-06-06, 1d
    Embedding + vector store            :b2, 2026-06-06, 1d
    section Query
    Intent detection                    :c1, 2026-06-07, 1d
    Vector search + retrieval           :c2, 2026-06-07, 1d
    section Integration
    Augmented prompt builder            :d1, 2026-06-08, 1d
    Citation badges frontend            :d2, 2026-06-08, 1d
    section Testing
    Test với câu hỏi thực tế            :e1, 2026-06-09, 1d
    Fine-tune similarity threshold      :e2, 2026-06-09, 1d
```

---

## Files sẽ tạo mới

```
backend/
├── services/
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── ingestor.py        ← load PDF → chunks → embeddings
│   │   ├── retriever.py       ← query pgvector → top-k chunks
│   │   └── intent.py          ← detect: RAG / Tool / Direct
│   └── file_analyzer.py       ← (đã có ✅)
├── routers/
│   ├── agent.py               ← (update: thêm RAG call)
│   └── rag_admin.py           ← POST /rag/ingest, GET /rag/stats
├── models/
│   └── law_chunk.py           ← SQLAlchemy model cho pgvector
├── data/
│   └── laws/                  ← PDF văn bản pháp lý
│       ├── TT200_2014.pdf
│       ├── TT133_2016.pdf
│       └── TT45_2013.pdf
└── scripts/
    └── ingest_laws.py         ← chạy 1 lần để nhập dữ liệu

frontend/
└── components/
    └── CitationBadge.tsx      ← component hiển thị nguồn trích dẫn
```
