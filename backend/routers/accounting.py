"""
Accounting Router — FastAPI
POST /accounting/variance   → UC#2 Variance Commentary
POST /accounting/bank-recon → UC#5 Bank Reconciliation
"""

import json
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger

from services.llm import llm_service
from services.accounting import (
    parse_excel_variance,
    flag_variance,
    build_variance_prompt,
    parse_excel_bank,
    reconcile_bank,
    build_recon_prompt,
)

router = APIRouter(prefix="/accounting", tags=["accounting"])

ACCOUNTING_CORE_PROMPT = """Bạn là chuyên gia kế toán cao cấp với hơn 10 năm kinh nghiệm \
thực tế tại các doanh nghiệp Việt Nam. Am hiểu VAS, Thông tư 200/2014/TT-BTC, hệ thống thuế \
Việt Nam, và IFRS.

Nguyên tắc:
- Chính xác nghiệp vụ, trích dẫn thông tư khi cần
- Dùng thuật ngữ kế toán chuẩn tiếng Việt
- Phân biệt Revenue Favorable vs Expense Unfavorable
- Định dạng số: 1.000.000 đ"""


async def _save_temp(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        return tmp.name


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except Exception:
        pass


# ── UC#2 ──────────────────────────────────────────────────────

@router.post("/variance")
async def variance_commentary(
    file: UploadFile = File(...),
    period: Optional[str] = Form(None),
    threshold: str = Form("0.15"),
    column_map: Optional[str] = Form(None),
):
    if not (file.filename or "").endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Chỉ nhận file .xlsx hoặc .xls")
    threshold_val = float(threshold)
    col_map = None
    if column_map and column_map.strip():
        try:
            col_map = json.loads(column_map.strip())
        except Exception:
            raise HTTPException(400, "column_map phải là JSON string")

    tmp = await _save_temp(file)
    try:
        rows, validation = parse_excel_variance(tmp, column_map=col_map)
        if not validation.is_valid:
            msgs = "; ".join(e.message for e in validation.errors)
            raise HTTPException(422, f"File không hợp lệ: {msgs}")

        flagged_rows = flag_variance(rows, threshold=threshold_val)
        flagged_count = sum(1 for r in flagged_rows if r["flagged"])
        logger.info(f"Variance: {flagged_count}/{len(rows)} flagged")

        prompt = build_variance_prompt(flagged_rows, period=period, threshold=threshold_val)
        messages = [{"role": "user", "content": prompt}]

        async def generate():
            meta = {
                "type": "metadata",
                "total_rows": len(rows),
                "flagged_count": flagged_count,
                "threshold": threshold_val,
                "period": period,
                "flagged_items": [
                    {
                        "item": r["item"],
                        "variance_pct": round(r["variance_pct"] * 100, 1) if r["variance_pct"] else None,
                        "direction": r["direction"],
                        "line_type": r["line_type"],
                    }
                    for r in flagged_rows if r["flagged"]
                ],
            }
            yield f"data: __META__{json.dumps(meta, ensure_ascii=False)}\n\n"

            async for token in llm_service.stream(messages, ACCOUNTING_CORE_PROMPT):
                yield f"data: {token}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    finally:
        _cleanup(tmp)


# ── UC#5 ──────────────────────────────────────────────────────

@router.post("/bank-recon")
async def bank_reconciliation(
    bank_file: UploadFile = File(...),
    book_file: UploadFile = File(...),
    fuzzy_threshold: int = Form(85),
    with_commentary: bool = Form(True),
):
    for f in [bank_file, book_file]:
        if not (f.filename or "").endswith((".xlsx", ".xls")):
            raise HTTPException(400, f"'{f.filename}' phải là .xlsx")
    
    bank_tmp = await _save_temp(bank_file)
    book_tmp = await _save_temp(book_file)
    try:
        bank_rows, bv = parse_excel_bank(bank_tmp)
        if not bv.is_valid:
            raise HTTPException(422, "; ".join(e.message for e in bv.errors))

        book_rows, bkv = parse_excel_bank(book_tmp)
        if not bkv.is_valid:
            raise HTTPException(422, "; ".join(e.message for e in bkv.errors))

        result = reconcile_bank(bank_rows, book_rows, fuzzy_threshold=fuzzy_threshold)
        logger.info(f"Bank recon: match_rate={result['summary']['match_rate']}%")

        async def generate():
            recon_payload = {
                "type": "recon_result",
                "summary": result["summary"],
                "unmatched_bank": result["unmatched_bank"][:20],
                "unmatched_book": result["unmatched_book"][:20],
                "partial": result["partial"][:20],
                "matched_count": len(result["matched"]),
            }
            yield f"data: __RECON__{json.dumps(recon_payload, ensure_ascii=False)}\n\n"

            if with_commentary:
                prompt = build_recon_prompt(result)
                messages = [{"role": "user", "content": prompt}]
                async for token in llm_service.stream(messages, ACCOUNTING_CORE_PROMPT):
                    yield f"data: {token}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    finally:
        _cleanup(bank_tmp)
        _cleanup(book_tmp)


@router.get("/health")
async def accounting_health():
    return {"status": "ok", "module": "accounting", "uc": ["variance", "bank-recon"]}