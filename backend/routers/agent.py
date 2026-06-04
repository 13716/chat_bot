"""
Agent Router — tool-calling loop, model selection, file analysis
POST /agent/chat
POST /agent/analyze-file
GET  /agent/models
GET  /agent/health
"""

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

Bạn có các công cụ chuyên biệt sau. Khi user yêu cầu phân tích số liệu từ file, **hãy chủ động gọi tool phù hợp** thay vì trả lời chung chung:

### analyze_variance
Gọi khi user muốn:
- Phân tích chênh lệch thực tế vs kế hoạch / ngân sách (variance analysis)
- So sánh Actual vs Budget trên P&L, báo cáo kết quả kinh doanh
- Viết commentary variance cho ban lãnh đạo / CFO
- Tìm khoản mục vượt ngưỡng, giải thích nguyên nhân chênh lệch
- Từ khóa kích hoạt: variance, chênh lệch, thực tế vs kế hoạch, budget, actual, P&L

### bank_reconciliation
Gọi khi user muốn:
- Đối chiếu sao kê ngân hàng với sổ sách kế toán
- Tìm giao dịch không khớp / chênh lệch ngân hàng vs sổ sách
- Kiểm tra reconciliation, đối chiếu số dư cuối kỳ
- Phát hiện giao dịch bị bỏ sót hoặc ghi nhầm
- Từ khóa kích hoạt: bank reconciliation, đối chiếu ngân hàng, sao kê, reconcile

**Lưu ý**: Khi không có file Excel nhưng user yêu cầu → hỏi upload file trước khi gọi tool.
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
    return {
        "prompt": build_variance_prompt(flagged, period=period, threshold=threshold),
        "meta": {"total_rows": len(rows), "flagged_count": fc, "threshold": threshold, "period": period},
    }

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

        tool_name = tc.get("name"); tool_args = tc.get("arguments", {}); tc_id = tc.get("id", "call_0")
        tmps: list[str] = []
        tool_result = ""; tool_meta: dict = {}

        try:
            if tool_name == "analyze_variance":
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

    # ── Gọi LLM với tool-calling nếu model hỗ trợ ──────────────────────
    response = None
    if tool_capable:
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
        # Model không hỗ trợ tool → stream trực tiếp
        async def gen_direct_no_tool():
            s = await client.chat.completions.create(model=llm_model, messages=messages, stream=True)
            async for chunk in s:
                t = chunk.choices[0].delta.content or ""
                if t: yield f"data: {t}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen_direct_no_tool(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if response is None:
        raise HTTPException(503, "Tất cả providers không phản hồi")

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
