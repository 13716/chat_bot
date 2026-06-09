"""
UC#7 — AR/AP Aging Analysis
Phân tích tuổi nợ Phải Thu (Accounts Receivable) / Phải Trả (Accounts Payable)

Input:  Excel với cột: vendor/customer, invoice_no, invoice_date, due_date, amount
Output: Phân nhóm tuổi nợ (Current/1-30/31-60/61-90/>90 ngày) + LLM commentary
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────
# BUCKET DEFINITIONS
# ─────────────────────────────────────────────────────────────

AGING_BUCKETS = [
    # (key,      label,           min_days_overdue, max_days_overdue)
    # None = no limit on that side
    ("current",  "Chưa đến hạn",  None, 0),   # days_overdue <= 0
    ("1_30",     "1–30 ngày",       1,  30),
    ("31_60",    "31–60 ngày",     31,  60),
    ("61_90",    "61–90 ngày",     61,  90),
    ("over_90",  ">90 ngày",       91, None),
]

# Ngưỡng rủi ro (% tổng dư nợ nằm ở bucket >90 ngày)
RISK_THRESHOLDS = {
    "low":      0.05,   # <5%  → LOW
    "medium":   0.15,   # <15% → MEDIUM
    "high":     0.30,   # <30% → HIGH
    "critical": 1.0,    #  30%+ → CRITICAL
}


# ─────────────────────────────────────────────────────────────
# COLUMN ALIASES (tên cột linh hoạt, hỗ trợ dấu / không dấu)
# ─────────────────────────────────────────────────────────────

COLUMN_ALIASES = {
    "vendor": [
        "đối tác", "doi tac", "khách hàng", "khach hang", "vendor", "customer",
        "tên", "ten", "nhà cung cấp", "nha cung cap", "supplier",
        "nội dung", "noi dung", "người bán", "nguoi ban", "người mua", "nguoi mua",
        "tên công ty", "ten cong ty", "tên khách hàng", "ten khach hang",
    ],
    "invoice_no": [
        "số hóa đơn", "so hoa don", "invoice", "invoice no", "invoice number",
        "mã hóa đơn", "ma hoa don", "số chứng từ", "so chung tu", "số ct", "so ct",
        "ref", "mã gd", "ma gd", "số invoice", "so invoice",
        "số hđ", "so hd", "mã hđ", "ma hd", "hóa đơn số", "hoa don so",
    ],
    "invoice_date": [
        "ngày hóa đơn", "ngay hoa don", "invoice date", "ngày ct", "ngay ct",
        "ngày phát sinh", "ngay phat sinh", "ngày giao dịch", "ngay giao dich",
        "ngày", "ngay", "date", "issue date", "ngày xuất hóa đơn", "ngay xuat hoa don",
    ],
    "due_date": [
        "ngày đến hạn", "ngay den han", "due date", "hạn thanh toán",
        "han thanh toan", "ngày thanh toán", "ngay thanh toan", "maturity date",
        "hạn nộp", "han nop", "ngày hết hạn", "ngay het han",
        "payment due", "due", "expiry date",
    ],
    "amount": [
        "số tiền", "so tien", "amount", "tiền", "tien", "giá trị", "gia tri",
        "số tiền còn lại", "so tien con lai", "outstanding", "dư nợ", "du no",
        "tiền còn lại", "tien con lai", "số dư", "so du", "balance",
        "số tiền chưa thanh toán", "so tien chua thanh toan",
        "số tiền phải thu", "so tien phai thu", "số tiền phải trả", "so tien phai tra",
    ],
    "ar_type": [
        "loại", "loai", "type", "ar/ap", "ar", "ap",
        "phải thu", "phai thu", "phải trả", "phai tra",
        "accounts receivable", "accounts payable",
    ],
}


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
# COLUMN DETECTION (3-lớp, hỗ trợ dấu / không dấu)
# ─────────────────────────────────────────────────────────────

def _norm_col(text: str) -> str:
    s = str(text).strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _detect_aging_col(col_raw: str) -> Optional[str]:
    """
    Nhận diện loại cột theo độ-khớp-cụ-thể-nhất (longest-match-wins).

    Lý do KHÔNG dùng first-canonical-wins: alias generic như "ngày"/"date"
    (thuộc invoice_date) là substring của "ngày đến hạn" (due_date) → nếu
    duyệt invoice_date trước sẽ nuốt mất cột due_date. Vì vậy:
      - Pass 1: khớp CHÍNH XÁC ở bất kỳ canonical nào → thắng ngay.
      - Pass 2: khớp substring, chọn alias DÀI NHẤT (cụ thể nhất) trên toàn bộ.
    """
    normed = _norm_col(col_raw)
    if not normed:
        return None

    # Pass 1: exact match ở bất kỳ canonical nào → ưu tiên tuyệt đối
    for canonical, aliases in COLUMN_ALIASES.items():
        if normed in [_norm_col(a) for a in aliases]:
            return canonical

    # Pass 2: substring match — alias dài nhất (cụ thể nhất) thắng
    best_canonical: Optional[str] = None
    best_len = 0
    for canonical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            na = _norm_col(a)
            if not na:
                continue
            # alias nằm trong tên cột HOẶC tên cột nằm trong alias (cột rất ngắn)
            if (na in normed) or (len(normed) >= 3 and normed in na):
                if len(na) > best_len:
                    best_len = len(na)
                    best_canonical = canonical
    return best_canonical


# ─────────────────────────────────────────────────────────────
# DATE PARSING (linh hoạt)
# ─────────────────────────────────────────────────────────────

_DATE_FMTS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y",
    "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d",
]


def _parse_date(val) -> Optional[date]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (datetime,)):
        return val.date()
    if isinstance(val, date):
        return val
    if hasattr(val, 'date'):   # pandas Timestamp
        return val.date()
    s = str(val).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────────────────────
# PARSE EXCEL
# ─────────────────────────────────────────────────────────────

def parse_excel_aging(
    filepath: str,
    as_of: Optional[date] = None,
    payment_terms_days: int = 30,
) -> tuple[list[dict], ValidationResult]:
    """
    Đọc file Excel danh sách công nợ AR/AP.

    Args:
        filepath: đường dẫn file .xlsx
        as_of: ngày tính aging (mặc định hôm nay)
        payment_terms_days: số ngày thanh toán mặc định nếu không có cột due_date (default: 30)

    Returns:
        (rows, validation_result)
        rows: [
            {
                "vendor": str,
                "invoice_no": str,
                "invoice_date": date | None,
                "due_date": date,
                "amount": float,
                "days_overdue": int,   # > 0 = quá hạn, <= 0 = chưa đến hạn
                "bucket": str,         # current / 1_30 / 31_60 / 61_90 / over_90
                "ar_type": str,        # "AR" | "AP" | "unknown"
            },
            ...
        ]
    """
    errors: list[ValidationError] = []
    ref_date = as_of or date.today()

    try:
        df = pd.read_excel(filepath, engine="openpyxl")
    except Exception as e:
        return [], ValidationResult(False, [ValidationError("file", f"Không đọc được file: {e}")])

    if df.empty:
        return [], ValidationResult(False, [ValidationError("file", "File không có dữ liệu")])

    # Auto-detect columns
    rename_map: dict[str, str] = {}
    for col in df.columns:
        canonical = _detect_aging_col(str(col))
        if canonical and canonical not in rename_map.values():
            rename_map[col] = canonical

    df = df.rename(columns=rename_map)

    # Cột bắt buộc: vendor + amount (invoice_date hoặc due_date cần ít nhất 1)
    if "vendor" not in df.columns:
        # Fallback: dùng cột text đầu tiên làm vendor
        text_cols = [c for c in df.columns if df[c].dtype == object]
        if text_cols:
            df = df.rename(columns={text_cols[0]: "vendor"})
            errors.append(ValidationError("columns", f"Không tìm thấy cột vendor/customer — tự động dùng '{text_cols[0]}'"))
        else:
            return [], ValidationResult(False, [ValidationError("columns", "Thiếu cột vendor/customer")])

    if "amount" not in df.columns:
        num_cols = [c for c in df.columns if df[c].dtype in ["float64", "int64"]]
        if num_cols:
            df = df.rename(columns={num_cols[0]: "amount"})
            errors.append(ValidationError("columns", f"Không tìm thấy cột amount — tự động dùng '{num_cols[0]}'"))
        else:
            return [], ValidationResult(False, [ValidationError("columns", "Thiếu cột số tiền (amount)")])

    has_due_date     = "due_date"     in df.columns
    has_invoice_date = "invoice_date" in df.columns

    if not has_due_date and not has_invoice_date:
        errors.append(ValidationError(
            "columns",
            f"Không có cột due_date lẫn invoice_date — sẽ tính due_date = today - {payment_terms_days} ngày",
        ))

    rows: list[dict] = []

    for idx, row in df.iterrows():
        vendor = str(row["vendor"]).strip() if pd.notna(row.get("vendor")) else ""
        if not vendor or vendor.lower() in ("nan", "none", ""):
            continue

        # Amount
        try:
            amount = float(row["amount"]) if pd.notna(row.get("amount")) else None
            if amount is None or amount <= 0:
                continue
        except (ValueError, TypeError):
            errors.append(ValidationError(f"row_{idx}_amount", f"Dòng '{vendor}': amount không phải số"))
            continue

        # Invoice date
        inv_date = _parse_date(row.get("invoice_date")) if has_invoice_date else None

        # Due date
        if has_due_date:
            due = _parse_date(row.get("due_date"))
        elif inv_date:
            due = inv_date + timedelta(days=payment_terms_days)
        else:
            due = ref_date - timedelta(days=payment_terms_days)  # assume already overdue

        if due is None:
            due = ref_date  # fallback: treat as due today

        # Days overdue: positive = quá hạn, negative/zero = chưa đến hạn
        days_overdue = (ref_date - due).days

        # Bucket
        bucket = _assign_bucket(days_overdue)

        # AR type
        ar_type = "unknown"
        if "ar_type" in df.columns:
            raw_t = str(row.get("ar_type", "")).strip().lower()
            if any(k in raw_t for k in ["ar", "phải thu", "phai thu", "receivable"]):
                ar_type = "AR"
            elif any(k in raw_t for k in ["ap", "phải trả", "phai tra", "payable"]):
                ar_type = "AP"

        rows.append({
            "vendor":       vendor,
            "invoice_no":   str(row.get("invoice_no", "")).strip() if pd.notna(row.get("invoice_no")) else "",
            "invoice_date": inv_date,
            "due_date":     due,
            "amount":       round(amount, 2),
            "days_overdue": days_overdue,
            "bucket":       bucket,
            "ar_type":      ar_type,
        })

    is_valid = len(rows) > 0 and not any(e.field not in ("columns",) for e in errors)
    return rows, ValidationResult(is_valid, errors)


def _assign_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    elif days_overdue <= 30:
        return "1_30"
    elif days_overdue <= 60:
        return "31_60"
    elif days_overdue <= 90:
        return "61_90"
    else:
        return "over_90"


# ─────────────────────────────────────────────────────────────
# BUCKET SUMMARY
# ─────────────────────────────────────────────────────────────

def summarize_aging(rows: list[dict]) -> dict:
    """
    Tổng hợp aging theo bucket và theo vendor.

    Returns:
    {
        "total_outstanding": float,
        "as_of": str,
        "buckets": {
            "current":  {"label": "Chưa đến hạn", "count": int, "amount": float, "pct": float},
            "1_30":     {...},
            "31_60":    {...},
            "61_90":    {...},
            "over_90":  {...},
        },
        "vendors": [
            {"vendor": str, "total": float, "buckets": {...}, "max_days": int, "risk": str},
            ...
        ],
        "risk_level":  "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
        "risk_reasons": [str, ...],
    }
    """
    if not rows:
        return {}

    total = sum(r["amount"] for r in rows)
    if total == 0:
        return {}

    # ── Bucket totals ──────────────────────────────────────────
    bucket_data: dict[str, dict] = {
        k: {"label": lbl, "count": 0, "amount": 0.0}
        for k, lbl, *_ in AGING_BUCKETS
    }
    for r in rows:
        b = r["bucket"]
        bucket_data[b]["count"]  += 1
        bucket_data[b]["amount"] += r["amount"]

    for b in bucket_data:
        bucket_data[b]["pct"] = round(bucket_data[b]["amount"] / total * 100, 1)
        bucket_data[b]["amount"] = round(bucket_data[b]["amount"], 0)

    # ── Per-vendor summary ─────────────────────────────────────
    vendor_map: dict[str, dict] = {}
    for r in rows:
        v = r["vendor"]
        if v not in vendor_map:
            vendor_map[v] = {
                "vendor": v,
                "total": 0.0,
                "buckets": {k: 0.0 for k, *_ in AGING_BUCKETS},
                "max_days": 0,
                "invoice_count": 0,
            }
        vendor_map[v]["total"]             += r["amount"]
        vendor_map[v]["buckets"][r["bucket"]] += r["amount"]
        vendor_map[v]["max_days"]           = max(vendor_map[v]["max_days"], r["days_overdue"])
        vendor_map[v]["invoice_count"]      += 1

    # Compute vendor risk
    vendors = []
    for v_data in vendor_map.values():
        v_data["total"] = round(v_data["total"], 0)
        v_data["buckets"] = {k: round(amt, 0) for k, amt in v_data["buckets"].items()}
        over90_pct = v_data["buckets"]["over_90"] / v_data["total"] if v_data["total"] else 0
        v_data["risk"] = _vendor_risk(over90_pct, v_data["max_days"])
        vendors.append(v_data)

    # Sort: highest total first
    vendors.sort(key=lambda x: x["total"], reverse=True)

    # ── Portfolio-level risk ───────────────────────────────────
    over90_pct  = bucket_data["over_90"]["amount"] / total
    critical_61 = (bucket_data["61_90"]["amount"] + bucket_data["over_90"]["amount"]) / total

    risk_level   = _portfolio_risk(over90_pct)
    risk_reasons = _build_risk_reasons(bucket_data, total, over90_pct, critical_61, rows)

    return {
        "total_outstanding": round(total, 0),
        "invoice_count":     len(rows),
        "as_of":             date.today().isoformat(),
        "buckets":           bucket_data,
        "vendors":           vendors,
        "risk_level":        risk_level,
        "risk_reasons":      risk_reasons,
    }


def _vendor_risk(over90_pct: float, max_days: int) -> str:
    if max_days > 180 or over90_pct > 0.5:
        return "CRITICAL"
    if max_days > 90 or over90_pct > 0.3:
        return "HIGH"
    if max_days > 60 or over90_pct > 0.15:
        return "MEDIUM"
    return "LOW"


def _portfolio_risk(over90_pct: float) -> str:
    if over90_pct >= RISK_THRESHOLDS["high"]:
        return "CRITICAL" if over90_pct >= 0.5 else "HIGH"
    if over90_pct >= RISK_THRESHOLDS["medium"]:
        return "MEDIUM"
    return "LOW"


def _build_risk_reasons(
    bucket_data: dict,
    total: float,
    over90_pct: float,
    critical_61: float,
    rows: list[dict],
) -> list[str]:
    reasons = []
    if over90_pct >= 0.30:
        reasons.append(
            f"⚠️ {over90_pct*100:.1f}% tổng dư nợ quá hạn >90 ngày "
            f"({bucket_data['over_90']['amount']:,.0f} đ) — rủi ro mất vốn cao"
        )
    elif over90_pct >= 0.15:
        reasons.append(
            f"⚠️ {over90_pct*100:.1f}% dư nợ quá hạn >90 ngày — cần theo dõi chặt"
        )

    if critical_61 >= 0.40:
        reasons.append(
            f"⚠️ {critical_61*100:.1f}% dư nợ đã quá hạn 61+ ngày — cần hành động ngay"
        )

    # Tìm vendor tập trung rủi ro cao nhất
    over90_rows = [r for r in rows if r["bucket"] == "over_90"]
    if over90_rows:
        from collections import Counter
        top_vendor = Counter()
        for r in over90_rows:
            top_vendor[r["vendor"]] += r["amount"]
        if top_vendor:
            name, amt = top_vendor.most_common(1)[0]
            reasons.append(f"📌 Đối tác rủi ro cao nhất: {name} — {amt:,.0f} đ quá hạn >90 ngày")

    if not reasons:
        reasons.append("✅ Danh mục công nợ trong giới hạn an toàn")

    return reasons


# ─────────────────────────────────────────────────────────────
# LLM PROMPT BUILDER
# ─────────────────────────────────────────────────────────────

def build_aging_prompt(summary: dict, ar_type_label: str = "Công nợ") -> str:
    """
    Tạo prompt tiếng Việt từ aging summary để gửi LLM commentary.
    """
    if not summary:
        return "Không có dữ liệu công nợ để phân tích."

    total     = summary["total_outstanding"]
    buckets   = summary["buckets"]
    vendors   = summary["vendors"]
    risk      = summary["risk_level"]
    reasons   = summary["risk_reasons"]
    as_of     = summary["as_of"]
    inv_count = summary.get("invoice_count", len(vendors))

    # Bucket summary lines
    bucket_lines = []
    for key, bdata in buckets.items():
        bucket_lines.append(
            f"  • {bdata['label']:15s}: {bdata['count']:3d} hóa đơn  |  "
            f"{bdata['amount']:>15,.0f} đ  ({bdata['pct']:.1f}%)"
        )

    # Top 5 vendors by total
    top5 = vendors[:5]
    vendor_lines = []
    for v in top5:
        over90 = v["buckets"].get("over_90", 0)
        vendor_lines.append(
            f"  • {v['vendor'][:35]:<35s}: {v['total']:>12,.0f} đ  "
            f"(>90 ngày: {over90:>10,.0f} đ  |  Risk: {v['risk']})"
        )

    risk_str = "\n".join(f"  {r}" for r in reasons)

    return f"""Bạn là chuyên gia kế toán cao cấp. Dưới đây là báo cáo Aging {ar_type_label} \
tính đến ngày {as_of}:

TỔNG DƯ NỢ: {total:,.0f} đ  |  {inv_count} hóa đơn  |  Rủi ro tổng thể: {risk}

PHÂN TÍCH THEO TUỔI NỢ:
{chr(10).join(bucket_lines)}

TOP ĐỐI TÁC (theo dư nợ lớn nhất):
{chr(10).join(vendor_lines)}

CẢNH BÁO RỦI RO:
{risk_str}

Hãy viết báo cáo phân tích aging theo cấu trúc sau (tiếng Việt, chuẩn nội bộ doanh nghiệp):

1. TÓM TẮT (2–3 câu): Tổng quan tình hình {ar_type_label}, đánh giá mức rủi ro {risk}.
2. PHÂN TÍCH CHI TIẾT:
   - Nhận xét về cấu trúc tuổi nợ (bucket nào chiếm tỷ trọng lớn, xu hướng đáng lo ngại)
   - Các đối tác rủi ro cao cần ưu tiên xử lý
3. HÀNH ĐỘNG ĐỀ XUẤT (3–5 hành động cụ thể):
   - Gắn với số liệu và tên đối tác cụ thể
   - Phân biệt hành động ngay (trong tuần) vs dài hạn
4. KẾT LUẬN: Đánh giá tổng thể và khuyến nghị cho Ban Giám đốc

Yêu cầu: thuật ngữ kế toán chuẩn VAS, không chung chung, độ dài 200–300 từ."""
