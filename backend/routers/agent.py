"""
Agent Router — tool-calling loop, model selection, file analysis
POST /agent/chat
POST /agent/analyze-file
GET  /agent/models
GET  /agent/health
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from openai import AsyncOpenAI

from core.config import get_settings
from services.accounting import (
    build_recon_prompt, build_variance_prompt,
    flag_variance, parse_excel_bank, parse_excel_variance, reconcile_bank,
)
from services.file_analyzer import analyze_file
from services.aging import (
    build_aging_prompt, parse_excel_aging, summarize_aging,
)
from services.financial_statement import (
    build_fs_prompt, compute_ratios, flag_ratios, parse_excel_fs,
)
from services.rag.intent import detect_intent
from services.rag.retriever import format_citations, format_context, retrieve

router = APIRouter(prefix="/agent", tags=["agent"])
settings = get_settings()

# ── Load system prompt từ file ────────────────────────────────────────────

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_promt.md"

def _load_system_prompt() -> str:
    try:
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return "Bạn là chuyên gia kế toán Việt Nam, am hiểu VAS và Thông tư 200/2014/TT-BTC."

_BASE_PROMPT = _load_system_prompt()

# Phần hướng dẫn tool — gắn thêm vào cuối system prompt
_TOOL_GUIDE = """

## CÔNG CỤ PHÂN TÍCH (Tools)

### NGUYÊN TẮC QUAN TRỌNG — ĐỌC TRƯỚC KHI GỌI TOOL

❌ **KHÔNG GỌI BẤT KỲ TOOL NÀO** khi:
- User chỉ yêu cầu **tóm tắt**, **đọc**, **xem qua**, **review** file (dù file là Excel hay Word hay PDF)
- User hỏi câu hỏi mà không đề cập rõ ràng đến việc phân tích số liệu
- File đính kèm là **Word (.doc/.docx)**, **PDF thông thường**, **text**, **ảnh** — những file này dùng để đọc, không phải để chạy tool kế toán
- User chỉ muốn **chat**, **hỏi đáp** hoặc **giải thích khái niệm**

✅ **CHỈ GỌI TOOL** khi:
- File đính kèm là **Excel (.xlsx/.xls)** VÀ user rõ ràng yêu cầu phân tích số liệu
- User dùng từ khóa cụ thể như: "phân tích variance", "đối chiếu ngân hàng", "tính ROE ROA", "phân tích BCTC"

---

### analyze_financial_statement
Gọi KHI VÀ CHỈ KHI user muốn **tính toán tỷ số tài chính** từ file Excel BCTC:
- Tính ROE, ROA, Current Ratio, Quick Ratio, Debt/Equity, Gross Margin, Net Margin
- Đánh giá sức khỏe tài chính, so sánh với ngưỡng chuẩn
- File PHẢI là Excel có dữ liệu CĐKT và KQKD
- Từ khóa kích hoạt: "tính ROE", "phân tích tỷ số tài chính", "đánh giá sức khỏe tài chính", "phân tích BCTC"
- ❌ KHÔNG gọi nếu user chỉ nói "tóm tắt file", "xem file", "file này nói gì"

### analyze_variance
Gọi KHI VÀ CHỈ KHI user muốn **phân tích chênh lệch Actual vs Budget**:
- File Excel có cột Budget, Actual
- Từ khóa: "variance", "chênh lệch ngân sách", "thực tế vs kế hoạch", "actual vs budget"
- ❌ KHÔNG gọi nếu user chỉ nói "tóm tắt", "xem qua" file

### bank_reconciliation
Gọi khi user muốn:
- Đối chiếu sao kê ngân hàng với sổ sách kế toán
- Tìm giao dịch không khớp / chênh lệch ngân hàng vs sổ sách
- Kiểm tra reconciliation, đối chiếu số dư cuối kỳ
- Phát hiện giao dịch bị bỏ sót hoặc ghi nhầm
- Từ khóa kích hoạt: bank reconciliation, đối chiếu ngân hàng, sao kê, reconcile

**Lưu ý**: Khi không có file Excel nhưng user yêu cầu → hỏi upload file trước khi gọi tool.

### ar_ap_aging
Gọi khi user muốn phân tích tuổi nợ (aging analysis):
- Phân loại công nợ theo nhóm: Chưa đến hạn, 1-30, 31-60, 61-90, >90 ngày
- Đánh giá rủi ro thu hồi nợ / rủi ro thanh toán
- Tìm đối tác/khách hàng có nợ quá hạn lâu nhất
- Phân tích AR (Phải Thu) hoặc AP (Phải Trả)
- Từ khóa kích hoạt: aging, tuổi nợ, công nợ phải thu, công nợ phải trả, AR aging, AP aging,
  nợ quá hạn, overdue, phân tích công nợ, danh sách công nợ
"""

SYSTEM_PROMPT = _BASE_PROMPT + _TOOL_GUIDE

# ── Model registry ────────────────────────────────────────────────────────

MODELS = [
    # Groq
    {"id": "groq:llama-3.3-70b-versatile",  "name": "Llama 3.3 70B",        "provider": "Groq",     "key_attr": "GROQ_API_KEY",     "base_url": "https://api.groq.com/openai/v1",  "model": "llama-3.3-70b-versatile",  "tool_capable": True},
    {"id": "groq:llama-3.1-8b-instant",     "name": "Llama 3.1 8B (Fast)",  "provider": "Groq",     "key_attr": "GROQ_API_KEY",     "base_url": "https://api.groq.com/openai/v1",  "model": "llama-3.1-8b-instant",     "tool_capable": True},
    {"id": "groq:gemma2-9b-it",             "name": "Gemma 2 9B",           "provider": "Groq",     "key_attr": "GROQ_API_KEY",     "base_url": "https://api.groq.com/openai/v1",  "model": "gemma2-9b-it",             "tool_capable": False},
    # Gemini via OpenAI-compat (nếu có key)
    {"id": "deepseek:deepseek-chat",        "name": "Deepseek Chat",        "provider": "Deepseek", "key_attr": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com",         "model": "deepseek-chat",            "tool_capable": True},
]

def _get_available_models() -> list[dict]:
    out = []
    for m in MODELS:
        key = getattr(settings, m["key_attr"], "")
        if key:
            out.append({**m, "available": True})
    return out

def _build_client(model_id: str) -> tuple[AsyncOpenAI, str, bool]:
    """Return (client, model_name, tool_capable)."""
    for m in MODELS:
        if m["id"] == model_id:
            key = getattr(settings, m["key_attr"], "")
            if not key:
                raise HTTPException(503, f"API key chưa cấu hình cho {m['provider']}")
            return AsyncOpenAI(api_key=key, base_url=m["base_url"]), m["model"], m["tool_capable"]
    raise HTTPException(400, f"Model không hợp lệ: {model_id}")

def _default_model_id() -> str:
    for m in MODELS:
        if m["tool_capable"] and getattr(settings, m["key_attr"], ""):
            return m["id"]
    for m in MODELS:
        if getattr(settings, m["key_attr"], ""):
            return m["id"]
    raise HTTPException(503, "Không có model nào khả dụng")

# ── Tools definition ──────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_variance",
            "description": (
                "UC#2 — Phân tích variance (chênh lệch thực tế vs kế hoạch/ngân sách) từ file Excel P&L. "
                "Tự động flag các khoản mục vượt ngưỡng, phân biệt Revenue Favorable / Expense Unfavorable, "
                "và viết commentary chuẩn CFO bằng tiếng Việt. "
                "GỌI TOOL NÀY khi user đề cập: variance, chênh lệch ngân sách, thực tế vs kế hoạch, "
                "actual vs budget, P&L analysis, phân tích kết quả kinh doanh, "
                "khoản mục vượt ngưỡng, giải thích chênh lệch, variance commentary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Kỳ kế toán cụ thể, ví dụ: 'Tháng 6/2026', 'Q2 2026', 'H1 2026'. Lấy từ câu hỏi của user.",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Ngưỡng % để flag variance (0.0–1.0). Mặc định 0.15 = 15%. Dùng 0.1 nếu user muốn chi tiết hơn.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_financial_statement",
            "description": (
                "UC#1 — Tính toán tỷ số tài chính (ROE, ROA, Current Ratio, Quick Ratio, Debt/Equity, "
                "Gross Margin, Net Margin) từ file Excel BCTC và viết báo cáo phân tích sức khỏe tài chính. "
                "CHỈ GỌI TOOL NÀY khi: (1) file đính kèm là Excel, VÀ (2) user rõ ràng yêu cầu TÍNH TỶ SỐ "
                "hoặc PHÂN TÍCH SỨC KHỎE TÀI CHÍNH — ví dụ: 'tính ROE', 'phân tích tỷ số tài chính', "
                "'đánh giá sức khỏe tài chính doanh nghiệp'. "
                "KHÔNG GỌI TOOL NÀY khi: user chỉ muốn tóm tắt file, xem nội dung file, "
                "file không phải Excel (Word/PDF/ảnh), hoặc user không đề cập đến tỷ số tài chính cụ thể."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Kỳ báo cáo, VD: 'Năm 2025', 'Q4 2025', 'H1 2026'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bank_reconciliation",
            "description": (
                "UC#5 — Đối chiếu sao kê ngân hàng với sổ sách kế toán, dùng fuzzy matching để tìm giao dịch "
                "không khớp, ghi nhầm hoặc bị bỏ sót. Phân tích nguyên nhân chênh lệch và viết báo cáo. "
                "GỌI TOOL NÀY khi user đề cập: đối chiếu ngân hàng, bank reconciliation, sao kê ngân hàng, "
                "reconcile, kiểm tra số dư ngân hàng, giao dịch không khớp, chênh lệch sổ sách vs ngân hàng, "
                "outstanding items, bank statement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fuzzy_threshold": {
                        "type": "integer",
                        "description": "Ngưỡng độ tương đồng tên vendor khi fuzzy match (0–100). Mặc định 85. Giảm xuống 70 nếu tên vendor có nhiều biến thể.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ar_ap_aging",
            "description": (
                "UC#7 — Phân tích tuổi nợ AR/AP (Aging Analysis). Phân loại công nợ phải thu/phải trả "
                "theo nhóm thời gian: Chưa đến hạn, 1-30, 31-60, 61-90, >90 ngày. Đánh giá rủi ro, "
                "xác định đối tác có nợ quá hạn, viết commentary cảnh báo bằng tiếng Việt. "
                "GỌI TOOL NÀY khi user đề cập: aging, tuổi nợ, công nợ phải thu, công nợ phải trả, "
                "AR aging, AP aging, nợ quá hạn, overdue, phân tích công nợ, danh sách công nợ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ar_type": {
                        "type": "string",
                        "enum": ["AR", "AP", "both"],
                        "description": "Loại công nợ cần phân tích: AR (Phải Thu), AP (Phải Trả), both (cả hai). Mặc định 'both'.",
                    },
                    "payment_terms_days": {
                        "type": "integer",
                        "description": "Số ngày thanh toán mặc định nếu file không có cột due_date (VD: 30, 45, 60). Mặc định 30.",
                    },
                    "as_of_date": {
                        "type": "string",
                        "description": "Ngày tính aging, định dạng YYYY-MM-DD. Mặc định hôm nay.",
                    },
                },
                "required": [],
            },
        },
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────

async def _save_temp(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1] or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        return tmp.name

def _cleanup(*paths: str):
    for p in paths:
        try: os.unlink(p)
        except: pass

async def _run_variance(tmp: str, period, threshold) -> dict:
    rows, val = parse_excel_variance(tmp)
    if not val.is_valid:
        raise HTTPException(422, "; ".join(e.message for e in val.errors))
    flagged = flag_variance(rows, threshold=threshold)
    fc = sum(1 for r in flagged if r["flagged"])
    logger.info(f"Variance: {fc}/{len(rows)} flagged")

    # Chart data: các khoản vượt ngưỡng, sort theo |variance_abs| giảm dần, cap 12 để chart gọn
    chart_items = sorted(
        (r for r in flagged if r["flagged"] and r.get("variance_abs") is not None),
        key=lambda r: abs(r["variance_abs"]),
        reverse=True,
    )[:12]
    flagged_items = [
        {
            "item":         r["item"],
            "budget":       r.get("budget"),
            "actual":       r.get("actual"),
            "variance_abs": r.get("variance_abs"),
            "variance_pct": r.get("variance_pct"),
            "line_type":    r.get("line_type", "expense"),
            "direction":    r.get("direction", ""),
        }
        for r in chart_items
    ]

    return {
        "prompt": build_variance_prompt(flagged, period=period, threshold=threshold),
        "meta": {
            "total_rows": len(rows),
            "flagged_count": fc,
            "threshold": threshold,
            "period": period,
            "flagged_items": flagged_items,
        },
    }

async def _run_fs(tmp: str, period) -> dict:
    data, val = parse_excel_fs(tmp)
    if not val.is_valid:
        raise HTTPException(422, "; ".join(e.message for e in val.errors))
    ratios = compute_ratios(data)
    flagged = flag_ratios(ratios)
    critical = sum(1 for f in flagged if f["status"] == "critical")
    warning  = sum(1 for f in flagged if f["status"] == "warning")
    logger.info(f"FS: {len(flagged)} ratios, {critical} critical, {warning} warning")
    return {
        "prompt": build_fs_prompt(data, ratios, flagged, period=period),
        "meta": {
            "ratios": flagged,
            "critical_count": critical,
            "warning_count": warning,
            "period": period,
        },
    }


async def _run_aging(tmp: str, ar_type: str, payment_terms: int, as_of_date_str: Optional[str]) -> dict:
    from datetime import date as _date
    as_of = None
    if as_of_date_str:
        try:
            from datetime import datetime as _dt
            as_of = _dt.strptime(as_of_date_str, "%Y-%m-%d").date()
        except Exception:
            pass

    rows, val = parse_excel_aging(tmp, as_of=as_of, payment_terms_days=payment_terms)
    if not val.is_valid:
        raise HTTPException(422, "; ".join(e.message for e in val.errors))

    # Filter theo loại nếu cần
    if ar_type in ("AR", "AP"):
        filtered = [r for r in rows if r["ar_type"] == ar_type or r["ar_type"] == "unknown"]
    else:
        filtered = rows

    summary = summarize_aging(filtered)
    label_map = {"AR": "Công nợ Phải Thu (AR)", "AP": "Công nợ Phải Trả (AP)", "both": "Công nợ AR/AP"}
    label = label_map.get(ar_type, "Công nợ")

    logger.info(
        f"Aging: {len(rows)} invoices, total={summary.get('total_outstanding',0):,.0f}, "
        f"risk={summary.get('risk_level','?')}"
    )
    return {
        "prompt": build_aging_prompt(summary, label),
        "meta": {
            "aging_summary": summary,
            "ar_type": ar_type,
            "invoice_count": len(rows),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# RULE-BASED TOOL SELECTOR
# Llama trên Groq hay sinh tool-call sai định dạng (tool_use_failed). Khi đã biết
# intent=tool (vd Excel đính kèm), chọn tool theo luật → nhanh + chắc chắn,
# không phụ thuộc khả năng tool-calling kém ổn định của LLM.
# ─────────────────────────────────────────────────────────────────────────────

def _norm_msg(text: str) -> str:
    import unicodedata
    s = (text or "").lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


_KW_BANK     = ["doi chieu", "reconcil", "sao ke", "bank statement"]
_KW_AGING    = ["tuoi no", "aging", "cong no", "no qua han", "phai thu", "phai tra", "overdue"]
_KW_VARIANCE = ["chenh lech", "variance", "ke hoach", "budget", "vuot nguong",
                "thuc te vs", "actual vs", "ngan sach", "du toan"]
_KW_FS       = ["bao cao tai chinh", "bctc", "tai chinh", "ty so", "chi so tai chinh",
                "roe", "roa", "thanh khoan", "bien loi nhuan", "can doi ke toan", "kqkd"]


def _select_tool_by_rules(message: str, excel_count: int) -> Optional[dict]:
    """Chọn tool theo từ khóa + số file Excel. Trả {name, arguments} hoặc None."""
    n = _norm_msg(message)

    # Bank reconciliation: cần đối chiếu 2 nguồn → keyword hoặc có >=2 file Excel
    if any(k in n for k in _KW_BANK) or excel_count >= 2:
        return {"name": "bank_reconciliation", "arguments": {}}

    if any(k in n for k in _KW_AGING):
        ar_type = "AR" if "phai thu" in n else ("AP" if "phai tra" in n else "both")
        return {"name": "ar_ap_aging", "arguments": {"ar_type": ar_type}}

    if any(k in n for k in _KW_VARIANCE):
        return {"name": "analyze_variance", "arguments": {}}

    if any(k in n for k in _KW_FS):
        return {"name": "analyze_financial_statement", "arguments": {}}

    # Có đúng 1 file Excel nhưng câu mơ hồ → mặc định phân tích BCTC
    if excel_count == 1:
        return {"name": "analyze_financial_statement", "arguments": {}}

    return None


async def _run_bank_recon(bank_tmp, book_tmp, fuzzy) -> dict:
    bank_rows, bv = parse_excel_bank(bank_tmp)
    if not bv.is_valid: raise HTTPException(422, "; ".join(e.message for e in bv.errors))
    book_rows, bkv = parse_excel_bank(book_tmp)
    if not bkv.is_valid: raise HTTPException(422, "; ".join(e.message for e in bkv.errors))
    result = reconcile_bank(bank_rows, book_rows, fuzzy_threshold=fuzzy)
    logger.info(f"BankRecon: match_rate={result['summary']['match_rate']}%")
    return {
        "prompt": build_recon_prompt(result),
        "meta": {
            "summary": result["summary"],
            "matched_count": len(result["matched"]),
            "unmatched_bank": result["unmatched_bank"][:10],
            "unmatched_book": result["unmatched_book"][:10],
        },
    }

# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models():
    return {"models": _get_available_models()}


@router.post("/analyze-file")
async def analyze_file_endpoint(file: UploadFile = File(...)):
    tmp = await _save_temp(file)
    try:
        result = analyze_file(tmp, file.filename or "file")
        return result
    finally:
        _cleanup(tmp)


@router.post("/chat")
async def agent_chat(
    message: str = Form(...),
    history: str = Form("[]"),
    model_id: Optional[str] = Form(None),
    output_format: Optional[str] = Form("markdown"),   # markdown | json | html
    # files đính kèm (general — không phải tool files)
    attached_files: list[UploadFile] = File(default=[]),
    # tool execution files
    variance_file: Optional[UploadFile] = File(None),
    bank_file: Optional[UploadFile] = File(None),
    book_file: Optional[UploadFile] = File(None),
    aging_file: Optional[UploadFile] = File(None),
    pending_tool: Optional[str] = Form(None),
):
    mid = model_id or _default_model_id()
    client, llm_model, tool_capable = _build_client(mid)

    try:
        conv_history: list[dict] = json.loads(history)
    except Exception:
        conv_history = []

    # Format instruction appended to system prompt
    fmt_instruction = {
        "json": "\n\nKhi trả lời phân tích số liệu, hãy format kết quả dưới dạng JSON hợp lệ trong code block ```json```.",
        "html": "\n\nKhi trả lời phân tích số liệu, hãy format kết quả dưới dạng HTML có cấu trúc trong code block ```html```.",
        "markdown": "",
    }.get(output_format or "markdown", "")

    sys_prompt = SYSTEM_PROMPT + fmt_instruction

    # ── Handle pending tool (sau khi user upload file) ─────────────────
    if pending_tool:
        try:
            tc = json.loads(pending_tool)
        except Exception:
            raise HTTPException(400, "pending_tool phải là JSON")

        tool_name = tc.get("name"); tool_args = tc.get("arguments") or {}; tc_id = tc.get("id", "call_0")
        tmps: list[str] = []
        tool_result = ""; tool_meta: dict = {}

        try:
            if tool_name == "analyze_financial_statement":
                if not variance_file: raise HTTPException(400, "Cần fs_file (gửi qua variance_file)")
                p = await _save_temp(variance_file); tmps.append(p)
                r = await _run_fs(p, tool_args.get("period"))
                tool_result = r["prompt"]; tool_meta = r["meta"]
            elif tool_name == "analyze_variance":
                if not variance_file: raise HTTPException(400, "Cần variance_file")
                p = await _save_temp(variance_file); tmps.append(p)
                r = await _run_variance(p, tool_args.get("period"), float(tool_args.get("threshold", 0.15)))
                tool_result = r["prompt"]; tool_meta = r["meta"]
            elif tool_name == "bank_reconciliation":
                if not bank_file or not book_file: raise HTTPException(400, "Cần bank_file và book_file")
                bp = await _save_temp(bank_file); bkp = await _save_temp(book_file)
                tmps.extend([bp, bkp])
                r = await _run_bank_recon(bp, bkp, int(tool_args.get("fuzzy_threshold", 85)))
                tool_result = r["prompt"]; tool_meta = r["meta"]
            elif tool_name == "ar_ap_aging":
                if not aging_file: raise HTTPException(400, "Cần aging_file (file Excel danh sách công nợ)")
                p = await _save_temp(aging_file); tmps.append(p)
                r = await _run_aging(
                    p,
                    tool_args.get("ar_type", "both"),
                    int(tool_args.get("payment_terms_days", 30)),
                    tool_args.get("as_of_date"),
                )
                tool_result = r["prompt"]; tool_meta = r["meta"]
            else:
                raise HTTPException(400, f"Unknown tool: {tool_name}")
        finally:
            _cleanup(*tmps)

        messages = [
            {"role": "system", "content": sys_prompt},
            *conv_history,
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": tc_id, "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
            }]},
            {"role": "tool", "tool_call_id": tc_id, "content": tool_result},
        ]

        async def gen_tool():
            yield f"data: __META__{json.dumps(tool_meta, ensure_ascii=False)}\n\n"
            stream = await client.chat.completions.create(model=llm_model, messages=messages, stream=True)
            async for chunk in stream:
                t = chunk.choices[0].delta.content or ""
                if t: yield f"data: {t}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen_tool(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── RAG augmentation (chỉ cho câu hỏi pháp lý) ──────────────────────
    rag_chunks: list[dict] = []
    intent = detect_intent(message)

    # File Excel đính kèm → ép intent=tool (chạy phân tích), TRỪ KHI câu hỏi là
    # CÂU HỎI TUÂN THỦ PHÁP LÝ rõ ràng (giữ RAG). Lý do dùng marker thay vì intent:
    #   - "phân tích FILE báo cáo tài chính" bị detect_intent xếp nhầm legal vì có
    #     "báo cáo tài chính", nhưng thực chất là yêu cầu PHÂN TÍCH → phải chạy tool.
    #   - "báo cáo tài chính này đúng pháp lý chưa" → có marker tuân thủ → giữ RAG.
    # File Word/PDF KHÔNG ép → giữ guard tóm tắt cũ.
    _COMPLIANCE_MARKERS = [
        "phap ly", "tu phap", "phap luat", "hop phap", "tuan thu", "hop le",
        "hop quy", "dung luat", "dung quy dinh", "dung chuan", "dung thong tu",
        "theo thong tu", "theo quy dinh", "theo chuan muc", "vi pham", "co dung phap",
    ]
    has_excel = any((af.filename or "").lower().endswith((".xlsx", ".xls")) for af in attached_files)
    is_compliance_q = any(m in _norm_msg(message) for m in _COMPLIANCE_MARKERS)
    if has_excel and tool_capable and not is_compliance_q:
        if intent != "tool":
            logger.info(f"Excel + không phải câu tuân thủ → ép intent '{intent}'→'tool'")
        intent = "tool"

    if intent == "legal":
        rag_chunks = await asyncio.to_thread(retrieve, message)
        if rag_chunks:
            sys_prompt = sys_prompt + format_context(rag_chunks)
            logger.info(f"RAG augmented: {len(rag_chunks)} chunks, intent=legal")
        else:
            # Không tìm thấy trong DB → cảnh báo LLM không được bịa citation
            sys_prompt = sys_prompt + (
                "\n\n---\n"
                "⚠️ LƯU Ý QUAN TRỌNG: Cơ sở dữ liệu pháp lý nội bộ KHÔNG có thông tin về câu hỏi này "
                "(có thể điều khoản này chưa được nạp vào hệ thống).\n"
                "Hãy trả lời dựa trên kiến thức chung về kế toán Việt Nam (VAS, TT200/2014, TT133/2016) "
                "và BẮT BUỘC thêm ghi chú cuối câu trả lời:\n"
                "**📌 Lưu ý: Câu trả lời này dựa trên kiến thức chung, chưa được xác minh từ cơ sở dữ liệu pháp lý nội bộ.**"
            )
            logger.info(f"RAG: 0 chunks — disclaimer added, intent=legal")

    # ── Build user message (có thể kèm file context) ────────────────────
    user_content = message

    # Nếu có file đính kèm → thêm tóm tắt vào message
    if attached_files:
        file_summaries = []
        for af in attached_files:
            tmp = await _save_temp(af)
            try:
                info = analyze_file(tmp, af.filename or "file")
                file_summaries.append(f"[File: {af.filename}]\n{info['summary']}")
            finally:
                _cleanup(tmp)
        if file_summaries:
            user_content += "\n\n--- Tài liệu đính kèm ---\n" + "\n\n".join(file_summaries)

    messages = [
        {"role": "system", "content": sys_prompt},
        *conv_history,
        {"role": "user", "content": user_content},
    ]

    # ── Gọi LLM ──────────────────────────────────────────────────────────
    # Tool-calling CHỈ khi intent="tool" — legal/general stream thẳng không qua tool loop
    # Lý do: câu hỏi pháp lý/chung chung không cần tool, tránh LLM nhầm gọi tool sai
    use_tools = tool_capable and intent == "tool"

    # ── Rule-based tool selection (ưu tiên, không phụ thuộc LLM tool-calling) ──
    if use_tools:
        excel_count = sum(
            1 for af in attached_files
            if (af.filename or "").lower().endswith((".xlsx", ".xls"))
        )
        ruled = _select_tool_by_rules(message, excel_count)
        if ruled:
            tool_req = {"id": "call_rule", "name": ruled["name"], "arguments": ruled["arguments"]}
            logger.info(f"Rule-based tool: {ruled['name']} (excel={excel_count})")

            async def emit_tool_rule():
                yield f"data: __TOOL_REQUEST__{json.dumps(tool_req, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(emit_tool_rule(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    response = None
    if use_tools:
        for m in MODELS:
            if not getattr(settings, m["key_attr"], "") or not m["tool_capable"]:
                continue
            try:
                _client = AsyncOpenAI(api_key=getattr(settings, m["key_attr"]), base_url=m["base_url"])
                logger.info(f"Tool-detect: {m['id']}")
                response = await _client.chat.completions.create(
                    model=m["model"], messages=messages,
                    tools=TOOLS, tool_choice="auto", timeout=12,
                )
                client, llm_model = _client, m["model"]
                break
            except Exception as ex:
                logger.warning(f"{m['id']} failed: {ex}")
    else:
        # intent=legal hoặc general → stream trực tiếp, không dùng tool
        logger.info(f"Stream direct (intent={intent}, tool_capable={tool_capable})")
        async def gen_direct_no_tool():
            s = await client.chat.completions.create(model=llm_model, messages=messages, stream=True)
            async for chunk in s:
                t = chunk.choices[0].delta.content or ""
                if t: yield f"data: {t}\n\n"
            if rag_chunks:
                citations = format_citations(rag_chunks)
                yield f"data: __CITATIONS__{json.dumps(citations, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen_direct_no_tool(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if response is None:
        # Tool-calling LLM thất bại hết → trả thông báo thân thiện thay vì 503
        logger.warning("Tool-detect: tất cả providers fail → thông báo hướng dẫn")
        async def gen_fallback():
            msg_txt = (
                "⚠️ Hiện chưa xác định được loại phân tích phù hợp. "
                "Vui lòng nêu rõ yêu cầu, ví dụ: *phân tích báo cáo tài chính*, "
                "*phân tích tuổi nợ*, *đối chiếu ngân hàng*, hoặc *phân tích chênh lệch ngân sách* "
                "— và đính kèm file Excel tương ứng."
            )
            for i in range(0, len(msg_txt), 6):
                yield f"data: {msg_txt[i:i+6]}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen_fallback(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    choice = response.choices[0]

    # LLM muốn gọi tool
    if choice.finish_reason == "tool_calls":
        tc = choice.message.tool_calls[0]
        try: args = json.loads(tc.function.arguments)
        except: args = {}
        tool_req = {"id": tc.id, "name": tc.function.name, "arguments": args}

        async def emit_tool():
            yield f"data: __TOOL_REQUEST__{json.dumps(tool_req, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(emit_tool(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # LLM trả lời trực tiếp — stream lại
    direct = choice.message.content or ""

    async def emit_direct():
        for i in range(0, len(direct), 6):
            yield f"data: {direct[i:i+6]}\n\n"
        if rag_chunks:
            citations = format_citations(rag_chunks)
            yield f"data: __CITATIONS__{json.dumps(citations, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(emit_direct(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/health")
async def agent_health():
    available = _get_available_models()
    return {
        "status": "ok",
        "module": "agent",
        "available_models": len(available),
        "default_model": _default_model_id() if available else "none",
        "tools": [t["function"]["name"] for t in TOOLS],
        "system_prompt_loaded": len(SYSTEM_PROMPT) > 100,
    }
