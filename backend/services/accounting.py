"""
Accounting Agent — Core Business Logic
UC#2: Variance Commentary
UC#5: Bank Reconciliation

Tất cả hàm được thiết kế để test độc lập (TDD).
LLM call tách riêng — không mix vào business logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ─────────────────────────────────────────────────────────────
# SHARED TYPES
# ─────────────────────────────────────────────────────────────

@dataclass
class ValidationError:
    field: str
    message: str


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# UC#2 — VARIANCE COMMENTARY
# ─────────────────────────────────────────────────────────────

# Tên cột có thể gặp trong file thực tế (Việt + Anh)
COLUMN_ALIASES = {
    "item": ["khoản mục", "mục", "item", "chỉ tiêu", "nội dung", "description"],
    "budget": ["ngân sách", "budget", "kế hoạch", "plan", "dự toán"],
    "actual": ["thực tế", "actual", "thực hiện", "realized", "chi tiêu"],
    "line_type": ["loại", "type", "line_type", "phân loại"],
}

SKIP_KEYWORDS = [
    "tổng", "total", "subtotal", "cộng", "grand total",
    "tổng cộng", "tổng doanh thu", "tổng chi phí",
]


def normalize_column_name(raw: str) -> Optional[str]:
    """Map tên cột thực tế → tên chuẩn (item/budget/actual/line_type)."""
    cleaned = raw.strip().lower()
    for canonical, aliases in COLUMN_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return None


def parse_excel_variance(
    filepath: str,
    column_map: Optional[dict[str, str]] = None,
) -> tuple[list[dict], ValidationResult]:
    """
    Đọc file Excel variance, trả về list of rows + validation result.

    Args:
        filepath: đường dẫn file .xlsx
        column_map: override tên cột nếu cần
                    VD: {"Ngân sách 2024": "budget", "Thực chi": "actual"}

    Returns:
        (rows, validation_result)
        rows: [{"item": str, "budget": float, "actual": float, "line_type": str}, ...]
    """
    errors: list[ValidationError] = []

    try:
        df = pd.read_excel(filepath, engine="openpyxl")
    except Exception as e:
        return [], ValidationResult(False, [ValidationError("file", f"Không đọc được file: {e}")])

    if df.empty:
        return [], ValidationResult(False, [ValidationError("file", "File không có dữ liệu")])

    # Auto-detect hoặc dùng column_map
    rename_map: dict[str, str] = {}
    if column_map:
        rename_map = column_map
    else:
        for col in df.columns:
            canonical = normalize_column_name(str(col))
            if canonical:
                rename_map[col] = canonical

    df = df.rename(columns=rename_map)

    # Kiểm tra cột bắt buộc
    required = ["item", "budget", "actual"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [], ValidationResult(
            False,
            [ValidationError("columns", f"Thiếu cột: {', '.join(missing)}. Các cột hiện có: {list(df.columns)}")]
        )

    # Thêm line_type mặc định nếu chưa có
    if "line_type" not in df.columns:
        df["line_type"] = "expense"

    rows: list[dict] = []
    for idx, row in df.iterrows():
        item = str(row["item"]).strip() if pd.notna(row["item"]) else ""

        # Bỏ qua dòng trống
        if not item:
            continue

        # Bỏ qua dòng Total/Subtotal
        if any(kw in item.lower() for kw in SKIP_KEYWORDS):
            continue

        # Validate budget
        try:
            budget = float(row["budget"]) if pd.notna(row["budget"]) else None
        except (ValueError, TypeError):
            errors.append(ValidationError(f"row_{idx}_budget", f"Dòng '{item}': budget không phải số"))
            continue

        # Validate actual
        try:
            actual = float(row["actual"]) if pd.notna(row["actual"]) else None
        except (ValueError, TypeError):
            errors.append(ValidationError(f"row_{idx}_actual", f"Dòng '{item}': actual không phải số"))
            continue

        line_type = str(row.get("line_type", "expense")).strip().lower()
        if line_type not in ("expense", "revenue"):
            line_type = "expense"

        rows.append({
            "item": item,
            "budget": budget,
            "actual": actual,
            "line_type": line_type,
        })

    is_valid = len(errors) == 0 and len(rows) > 0
    return rows, ValidationResult(is_valid, errors)


def flag_variance(
    rows: list[dict],
    threshold: float = 0.15,
) -> list[dict]:
    """
    Tính variance % và flag khoản vượt ngưỡng.

    Logic kế toán chuẩn:
    - expense: actual > budget → Unfavorable (chi tiêu vượt)
    - expense: actual < budget → Favorable (tiết kiệm)
    - revenue: actual > budget → Favorable (doanh thu vượt kế hoạch)
    - revenue: actual < budget → Unfavorable (doanh thu hụt)

    Edge cases:
    - budget = 0 hoặc None → skip (variance_pct = None, flagged = False)
    - actual = None → skip
    """
    result = []
    for row in rows:
        budget = row.get("budget")
        actual = row.get("actual")
        line_type = row.get("line_type", "expense")

        # Skip nếu thiếu dữ liệu hoặc budget = 0
        if budget is None or actual is None or budget == 0:
            result.append({
                **row,
                "variance_abs": None,
                "variance_pct": None,
                "flagged": False,
                "direction": "N/A",
            })
            continue

        variance_pct = round((actual - budget) / abs(budget), 4)
        variance_abs = round(actual - budget, 2)

        # Xác định direction theo line_type
        if line_type == "revenue":
            # Revenue tăng = Favorable
            direction = "Favorable" if actual >= budget else "Unfavorable"
        else:
            # Expense tăng = Unfavorable
            direction = "Unfavorable" if actual >= budget else "Favorable"

        flagged = abs(variance_pct) > threshold

        result.append({
            **row,
            "variance_abs": variance_abs,
            "variance_pct": variance_pct,
            "flagged": flagged,
            "direction": direction,
        })

    return result


def build_variance_prompt(
    flagged_rows: list[dict],
    period: Optional[str] = None,
    threshold: float = 0.15,
) -> str:
    """
    Tạo prompt tiếng Việt từ flagged rows để gửi LLM.

    Args:
        flagged_rows: output từ flag_variance(), chỉ lấy dòng flagged=True
        period: VD "Tháng 5/2026", "Q1 2026"
        threshold: ngưỡng đang dùng (để mention trong prompt)
    """
    flagged = [r for r in flagged_rows if r.get("flagged")]

    if not flagged:
        return (
            "Dữ liệu variance cho thấy tất cả khoản mục đều nằm trong ngưỡng cho phép "
            f"({int(threshold * 100)}%). Không có khoản mục bất thường cần báo cáo. "
            "Hãy viết một đoạn commentary ngắn xác nhận kết quả tích cực này."
        )

    period_str = f"kỳ {period}" if period else "kỳ báo cáo"

    lines = []
    for r in flagged:
        pct = r["variance_pct"]
        pct_str = f"+{pct*100:.1f}%" if pct and pct > 0 else f"{pct*100:.1f}%"
        abs_str = f"{abs(r['variance_abs']):,.0f} đ" if r["variance_abs"] else "N/A"
        lines.append(
            f"- {r['item']} ({r['line_type']}): "
            f"Budget={r['budget']:,.0f}đ, Actual={r['actual']:,.0f}đ, "
            f"Chênh lệch={pct_str} ({abs_str}), Đánh giá={r['direction']}"
        )

    data_str = "\n".join(lines)

    return f"""Bạn là chuyên gia kế toán cao cấp. Dưới đây là dữ liệu variance {period_str} \
(ngưỡng flag: {int(threshold * 100)}%):

{data_str}

Hãy viết commentary theo cấu trúc sau (tiếng Việt, chuẩn báo cáo nội bộ):

1. TỔNG QUAN (2-3 câu): Nhận xét chung về tình hình tài chính kỳ này.
2. PHÂN TÍCH TRỌNG ĐIỂM: Với mỗi khoản mục bất thường, phân tích nguyên nhân \
tiêu biểu và tác động tài chính.
3. KHUYẾN NGHỊ: 2-3 hành động cụ thể cho Ban Giám đốc trong kỳ tới.

Yêu cầu:
- Dùng thuật ngữ kế toán chuẩn Việt Nam
- Phân biệt rõ Revenue Favorable vs Expense Unfavorable
- Không đề xuất hành động chung chung, phải gắn với số liệu cụ thể
- Độ dài: 150-250 từ"""


# ─────────────────────────────────────────────────────────────
# UC#5 — BANK RECONCILIATION
# ─────────────────────────────────────────────────────────────

BANK_COLUMN_ALIASES = {
    "date": ["ngày", "date", "ngày giao dịch", "transaction date", "ngày vd"],
    "vendor": ["đối tác", "vendor", "tên", "nội dung", "description", "beneficiary", "người thụ hưởng", "nội dung / đối tác"],
    "amount": ["số tiền", "amount", "tiền", "giá trị", "debit", "credit", "phát sinh"],
    "ref": ["mã gd", "reference", "ref", "số ct", "transaction id", "mã tham chiếu", "mã gd"],
}


def normalize_vendor_name(name: str) -> str:
    """
    Chuẩn hóa tên vendor để fuzzy match.
    Bỏ prefix công ty, lowercase, bỏ dấu câu thừa.
    """
    if not name:
        return ""
    name = name.lower().strip()
    # Bỏ các prefix phổ biến
    prefixes = [
        r"^công ty tnhh\s+", r"^công ty cp\s+", r"^cty tnhh\s+",
        r"^cty cp\s+", r"^công ty\s+", r"^cty\s+",
        r"^tnhh\s+", r"^jsc\s+", r"^ltd\s+", r"^co\.,?\s*ltd\s*",
    ]
    for p in prefixes:
        name = re.sub(p, "", name)
    # Bỏ ký tự đặc biệt
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def parse_excel_bank(
    filepath: str,
    sheet_name: int = 0,
) -> tuple[list[dict], ValidationResult]:
    """Đọc file sao kê ngân hàng hoặc sổ sách, trả về list of transactions."""
    errors: list[ValidationError] = []

    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
    except Exception as e:
        return [], ValidationResult(False, [ValidationError("file", f"Không đọc được file: {e}")])

    if df.empty:
        return [], ValidationResult(False, [ValidationError("file", "File không có dữ liệu")])

    # Auto-detect cột
    rename_map: dict[str, str] = {}
    for col in df.columns:
        cleaned = str(col).strip().lower()
        for canonical, aliases in BANK_COLUMN_ALIASES.items():
            if cleaned in aliases:
                rename_map[col] = canonical
                break

    df = df.rename(columns=rename_map)

    required = ["vendor", "amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [], ValidationResult(
            False,
            [ValidationError("columns", f"Thiếu cột: {', '.join(missing)}")]
        )

    rows: list[dict] = []
    for idx, row in df.iterrows():
        vendor = str(row.get("vendor", "")).strip()
        if not vendor or vendor.lower() in ("nan", "none", ""):
            continue

        try:
            amount = float(row["amount"]) if pd.notna(row["amount"]) else None
        except (ValueError, TypeError):
            errors.append(ValidationError(f"row_{idx}", f"Số tiền không hợp lệ tại dòng {idx}"))
            continue

        rows.append({
            "vendor": vendor,
            "vendor_normalized": normalize_vendor_name(vendor),
            "amount": amount,
            "date": str(row.get("date", "")).strip() if "date" in df.columns else None,
            "ref": str(row.get("ref", "")).strip() if "ref" in df.columns else None,
        })

    return rows, ValidationResult(len(errors) == 0 and len(rows) > 0, errors)


def reconcile_bank(
    bank_rows: list[dict],
    book_rows: list[dict],
    fuzzy_threshold: int = 85,
    date_tolerance_days: int = 2,
) -> dict:
    """
    Đối chiếu sao kê ngân hàng với sổ sách.

    Returns:
        {
            "matched": [...],       # khớp hoàn toàn
            "partial": [...],       # khớp một phần (cần xác nhận)
            "unmatched_bank": [...],  # có trong NH, không có trong sổ
            "unmatched_book": [...],  # có trong sổ, không có trong NH
            "summary": {...}
        }
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        raise ImportError("Cần cài rapidfuzz: pip install rapidfuzz")

    matched = []
    partial = []
    unmatched_bank = []
    used_book_indices = set()

    for bank_tx in bank_rows:
        best_score = 0
        best_idx = -1
        best_book = None

        for i, book_tx in enumerate(book_rows):
            if i in used_book_indices:
                continue

            # So sánh vendor (fuzzy)
            name_score = fuzz.ratio(
                bank_tx["vendor_normalized"],
                book_tx["vendor_normalized"]
            )

            # So sánh amount (exact)
            amount_match = (
                bank_tx["amount"] is not None
                and book_tx["amount"] is not None
                and abs(bank_tx["amount"] - book_tx["amount"]) < 1
            )

            if name_score > best_score and amount_match:
                best_score = name_score
                best_idx = i
                best_book = book_tx

        if best_score >= fuzzy_threshold and best_book is not None:
            if best_score == 100:
                matched.append({
                    "bank": bank_tx,
                    "book": best_book,
                    "confidence": best_score,
                })
            else:
                partial.append({
                    "bank": bank_tx,
                    "book": best_book,
                    "confidence": best_score,
                    "note": f"Tên vendor khớp {best_score}% — cần xác nhận",
                })
            used_book_indices.add(best_idx)
        else:
            unmatched_bank.append(bank_tx)

    # Các dòng sổ sách không khớp
    unmatched_book = [
        book_rows[i] for i in range(len(book_rows))
        if i not in used_book_indices
    ]

    total = len(bank_rows)
    summary = {
        "total_bank": total,
        "total_book": len(book_rows),
        "matched": len(matched),
        "partial": len(partial),
        "unmatched_bank": len(unmatched_bank),
        "unmatched_book": len(unmatched_book),
        "match_rate": round(len(matched) / total * 100, 1) if total > 0 else 0,
    }

    return {
        "matched": matched,
        "partial": partial,
        "unmatched_bank": sorted(unmatched_bank, key=lambda x: abs(x["amount"] or 0), reverse=True),
        "unmatched_book": sorted(unmatched_book, key=lambda x: abs(x["amount"] or 0), reverse=True),
        "summary": summary,
    }


def build_recon_prompt(recon_result: dict) -> str:
    """Tạo prompt từ kết quả reconciliation để LLM viết nhận xét."""
    s = recon_result["summary"]
    unmatched_bank = recon_result["unmatched_bank"][:5]
    partial = recon_result["partial"][:5]

    unmatched_str = "\n".join([
        f"- {r['vendor']}: {r['amount']:,.0f}đ (ngày: {r.get('date','N/A')})"
        for r in unmatched_bank
    ]) or "Không có"

    partial_str = "\n".join([
        f"- NH: {r['bank']['vendor']} | Sổ: {r['book']['vendor']} | "
        f"Điểm khớp: {r['confidence']}% | {r['bank'].get('amount', 0):,.0f}đ"
        for r in partial
        if r.get("bank") and r.get("book")
    ])

    return f"""Bạn là chuyên gia kế toán. Dưới đây là kết quả đối chiếu sao kê ngân hàng với sổ sách:

TỔNG KẾT:
- Tổng giao dịch ngân hàng: {s['total_bank']}
- Khớp hoàn toàn: {s['matched']} ({s['match_rate']}%)
- Cần xác nhận: {s['partial']}
- Không khớp (NH): {s['unmatched_bank']}
- Không khớp (Sổ): {s['unmatched_book']}

TOP GIAO DỊCH KHÔNG KHỚP (ngân hàng):
{unmatched_str}

GIAO DỊCH CẦN XÁC NHẬN:
{partial_str}

Hãy viết nhận xét đối chiếu theo cấu trúc (tiếng Việt):
1. TỔNG QUAN: Đánh giá chất lượng đối chiếu kỳ này
2. RỦI RO: Các khoản không khớp có giá trị lớn cần xử lý ngay
3. HÀNH ĐỘNG: Bước xử lý cụ thể cho kế toán viên
Độ dài: 100-150 từ, ngắn gọn, thực tế."""