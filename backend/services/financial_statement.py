"""
UC#1 — Financial Statement Reader
Upload BCTC Excel/CSV → extract chỉ tiêu → tính ratios → LLM commentary

Hỗ trợ:
  - File 1 sheet (Balance Sheet + Income Statement gộp chung)
  - File 2 sheet (sheet CĐKT + sheet KQKD)
  - Cột label ở cột A, số liệu ở cột kỳ này (tự detect)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# TYPES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ValidationError:
    field: str
    message: str


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# ALIASES — nhận dạng tên chỉ tiêu (Việt + Anh, viết hoa/thường đều được)
# ─────────────────────────────────────────────────────────────────────────────

_BS = {   # Balance Sheet aliases
    "current_assets": [
        "tài sản ngắn hạn", "a. tài sản ngắn hạn", "total current assets",
        "current assets", "tsnh", "tong tai san ngan han",
    ],
    "inventory": [
        "hàng tồn kho", "ii. hàng tồn kho", "inventory", "hang ton kho",
        "4. hàng tồn kho",
    ],
    "current_liabilities": [
        "nợ ngắn hạn", "i. nợ ngắn hạn", "current liabilities",
        "no ngan han", "a. nợ ngắn hạn",
    ],
    "total_assets": [
        "tổng cộng tài sản", "tổng tài sản", "total assets",
        "tong cong tai san", "tong tai san",
    ],
    "total_liabilities": [
        "nợ phải trả", "b. nợ phải trả", "total liabilities",
        "no phai tra", "tong no",
    ],
    "equity": [
        "vốn chủ sở hữu", "b. vốn chủ sở hữu", "equity",
        "shareholders equity", "von chu so huu", "vcsh",
        "c. vốn chủ sở hữu",
    ],
}

_IS = {   # Income Statement aliases
    "revenue": [
        "doanh thu thuần", "doanh thu thuần về bán hàng",
        "doanh thu bán hàng và cung cấp dịch vụ",
        "1. doanh thu thuần", "net revenue", "revenue", "doanh thu",
        "doanh thu thuan", "oanh thu thuần (10=01-02)",
    ],
    "cogs": [
        "giá vốn hàng bán", "2. giá vốn hàng bán", "cost of goods sold",
        "cogs", "gia von hang ban",
    ],
    "gross_profit": [
        "lợi nhuận gộp", "3. lợi nhuận gộp", "gross profit",
        "loi nhuan gop",
    ],
    "net_profit": [
        "lợi nhuận sau thuế thu nhập doanh nghiệp",
        "lợi nhuận sau thuế", "profit after tax", "net profit",
        "net income", "loi nhuan sau thue", "60. lợi nhuận sau thuế",
        "loi nhuan sau thue tndn",
    ],
    "operating_profit": [
        "lợi nhuận từ hoạt động kinh doanh", "lợi nhuận hoạt động",
        "operating profit", "ebit", "loi nhuan hoat dong",
    ],
}


def _norm(text: str) -> str:
    """Chuẩn hóa text để so sánh: lowercase, bỏ số đầu dòng, trim."""
    t = str(text).strip().lower()
    # Bỏ mã số đầu dòng (VD: "100.", "I.", "(100)")
    t = re.sub(r"^\(?\d+\)?\.?\s*", "", t)
    t = re.sub(r"^[ivx]+\.\s*", "", t)
    return t.strip()


def _match(label: str, aliases: list[str]) -> bool:
    n = _norm(label)
    return any(a in n or n in a for a in aliases)


def _find_value(df: pd.DataFrame, aliases: list[str]) -> Optional[float]:
    """
    Tìm giá trị chỉ tiêu trong DataFrame.
    Label ở cột đầu tiên (hoặc cột nào đó), số ở cột numeric tiếp theo.
    """
    label_col = df.columns[0]

    # Tìm cột "kỳ này" — ưu tiên: tìm theo tên, fallback: cột số đầu tiên
    numeric_cols = [
        c for c in df.columns[1:]
        if pd.api.types.is_numeric_dtype(df[c]) or _has_numbers(df[c])
    ]
    if not numeric_cols:
        return None

    # Cố tìm cột "kỳ này" / "cuối kỳ" / "current" trước
    period_col = None
    for c in df.columns[1:]:
        n = _norm(str(c))
        if any(k in n for k in ["kỳ này", "ky nay", "cuối kỳ", "current", "period"]):
            period_col = c
            break
    val_col = period_col or numeric_cols[0]

    for _, row in df.iterrows():
        label = str(row[label_col])
        if _match(label, aliases):
            try:
                v = row[val_col]
                if pd.notna(v):
                    return float(v)
            except (ValueError, TypeError):
                pass
    return None


def _has_numbers(series: pd.Series) -> bool:
    return series.dropna().apply(lambda x: _is_number(x)).sum() > len(series) * 0.3


def _is_number(x) -> bool:
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PARSE
# ─────────────────────────────────────────────────────────────────────────────

def parse_excel_fs(filepath: str) -> tuple[dict, ValidationResult]:
    """
    Đọc file BCTC (Excel), extract các chỉ tiêu cần thiết.

    Returns:
        (data_dict, validation_result)
        data_dict: {
            "current_assets", "inventory", "current_liabilities",
            "total_assets", "total_liabilities", "equity",
            "revenue", "cogs", "gross_profit", "net_profit",
            "operating_profit"   ← optional
        }
    """
    errors: list[ValidationError] = []

    try:
        xl = pd.ExcelFile(filepath, engine="openpyxl")
    except Exception as e:
        return {}, ValidationResult(False, [ValidationError("file", f"Không đọc được: {e}")])

    sheets = xl.sheet_names
    data: dict[str, Optional[float]] = {}

    # Đọc tất cả sheet, ghép lại để tìm kiếm
    all_dfs: list[pd.DataFrame] = []
    for sheet in sheets:
        try:
            df = xl.parse(sheet, header=0)
            if not df.empty and len(df.columns) >= 2:
                all_dfs.append(df)
        except Exception:
            pass

    if not all_dfs:
        return {}, ValidationResult(False, [ValidationError("file", "File không có dữ liệu hợp lệ")])

    # Tìm từng chỉ tiêu qua tất cả sheet
    for key, aliases in {**_BS, **_IS}.items():
        for df in all_dfs:
            val = _find_value(df, aliases)
            if val is not None:
                data[key] = val
                break
        else:
            data[key] = None

    # Validate: cần ít nhất 4 chỉ tiêu để tính được ratio
    found = [k for k, v in data.items() if v is not None]
    if len(found) < 4:
        errors.append(ValidationError(
            "data",
            f"Chỉ tìm được {len(found)} chỉ tiêu ({', '.join(found)}). "
            "File cần có Bảng CĐKT và KQKD. "
            "Hãy đảm bảo file có sheet hoặc các dòng: "
            "Tổng tài sản, Nợ phải trả, Vốn chủ sở hữu, Doanh thu, Lợi nhuận sau thuế."
        ))
        return data, ValidationResult(False, errors)

    return data, ValidationResult(True, errors)


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE RATIOS
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(a: Optional[float], b: Optional[float], pct: bool = False) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    result = a / b
    return round(result * 100, 2) if pct else round(result, 3)


def compute_ratios(data: dict) -> dict:
    """
    Tính các tỷ số tài chính từ dữ liệu BCTC.

    Returns dict: { ratio_name: {"value": float|None, "label": str, "unit": str} }
    """
    ca   = data.get("current_assets")
    inv  = data.get("inventory")
    cl   = data.get("current_liabilities")
    ta   = data.get("total_assets")
    tl   = data.get("total_liabilities")
    eq   = data.get("equity")
    rev  = data.get("revenue")
    cogs = data.get("cogs")
    gp   = data.get("gross_profit")
    np_  = data.get("net_profit")

    # Tính gross profit nếu chưa có
    if gp is None and rev is not None and cogs is not None:
        gp = rev - cogs

    ratios = {
        "roe": {
            "label": "ROE (Tỷ suất sinh lời VCSH)",
            "value": _safe_div(np_, eq, pct=True),
            "unit": "%",
        },
        "roa": {
            "label": "ROA (Tỷ suất sinh lời tổng tài sản)",
            "value": _safe_div(np_, ta, pct=True),
            "unit": "%",
        },
        "current_ratio": {
            "label": "Hệ số thanh toán hiện hành",
            "value": _safe_div(ca, cl),
            "unit": "lần",
        },
        "quick_ratio": {
            "label": "Hệ số thanh toán nhanh",
            "value": _safe_div((ca - inv) if ca and inv else ca, cl),
            "unit": "lần",
        },
        "debt_to_equity": {
            "label": "Hệ số Nợ/VCSH",
            "value": _safe_div(tl, eq),
            "unit": "lần",
        },
        "debt_to_assets": {
            "label": "Tỷ lệ Nợ/Tổng tài sản",
            "value": _safe_div(tl, ta, pct=True),
            "unit": "%",
        },
        "gross_margin": {
            "label": "Biên lợi nhuận gộp",
            "value": _safe_div(gp, rev, pct=True),
            "unit": "%",
        },
        "net_margin": {
            "label": "Biên lợi nhuận ròng",
            "value": _safe_div(np_, rev, pct=True),
            "unit": "%",
        },
    }
    return ratios


# ─────────────────────────────────────────────────────────────────────────────
# FLAG — đánh giá sức khỏe tài chính
# ─────────────────────────────────────────────────────────────────────────────

# Ngưỡng tham chiếu thông thường cho DN Việt Nam sản xuất/thương mại
_BENCHMARKS = {
    "roe":            {"good": 15,  "ok": 8,   "dir": "high_good"},
    "roa":            {"good": 5,   "ok": 2,   "dir": "high_good"},
    "current_ratio":  {"good": 2.0, "ok": 1.0, "dir": "high_good"},
    "quick_ratio":    {"good": 1.0, "ok": 0.5, "dir": "high_good"},
    "debt_to_equity": {"good": 1.0, "ok": 2.0, "dir": "low_good"},
    "debt_to_assets": {"good": 40,  "ok": 60,  "dir": "low_good"},
    "gross_margin":   {"good": 30,  "ok": 15,  "dir": "high_good"},
    "net_margin":     {"good": 10,  "ok": 5,   "dir": "high_good"},
}


def flag_ratios(ratios: dict) -> list[dict]:
    """
    Đánh giá từng ratio: GOOD / WARNING / CRITICAL.
    Returns list dùng để render meta tags và build prompt.
    """
    flagged = []
    for key, info in ratios.items():
        val = info.get("value")
        if val is None:
            continue

        bench = _BENCHMARKS.get(key)
        if not bench:
            status = "info"
        elif bench["dir"] == "high_good":
            status = "good" if val >= bench["good"] else ("warning" if val >= bench["ok"] else "critical")
        else:  # low_good
            status = "good" if val <= bench["good"] else ("warning" if val <= bench["ok"] else "critical")

        flagged.append({
            "key": key,
            "label": info["label"],
            "value": val,
            "unit": info["unit"],
            "status": status,
            # Ngưỡng tham chiếu (cho chart so sánh thực tế vs mục tiêu)
            "benchmark_good": bench["good"] if bench else None,
            "benchmark_ok":   bench["ok"]   if bench else None,
            "dir":            bench["dir"]  if bench else None,
        })

    return flagged


# ─────────────────────────────────────────────────────────────────────────────
# BUILD PROMPT
# ─────────────────────────────────────────────────────────────────────────────

def build_fs_prompt(data: dict, ratios: dict, flagged: list[dict], period: Optional[str] = None) -> str:
    """Tạo prompt để LLM viết commentary phân tích BCTC."""
    period_str = period or "kỳ báo cáo"

    # Chỉ tiêu gốc
    def fmt(v):
        if v is None:
            return "N/A"
        if abs(v) >= 1_000_000_000:
            return f"{v/1_000_000_000:,.1f} tỷ đ"
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:,.0f} triệu đ"
        return f"{v:,.0f} đ"

    raw_lines = []
    fields = [
        ("total_assets",       "Tổng tài sản"),
        ("current_assets",     "Tài sản ngắn hạn"),
        ("inventory",          "Hàng tồn kho"),
        ("total_liabilities",  "Nợ phải trả"),
        ("current_liabilities","Nợ ngắn hạn"),
        ("equity",             "Vốn chủ sở hữu"),
        ("revenue",            "Doanh thu thuần"),
        ("cogs",               "Giá vốn"),
        ("gross_profit",       "Lợi nhuận gộp"),
        ("net_profit",         "Lợi nhuận sau thuế"),
    ]
    for key, lbl in fields:
        v = data.get(key)
        if v is not None:
            raw_lines.append(f"  {lbl}: {fmt(v)}")

    # Tỷ số
    ratio_lines = []
    status_icons = {"good": "✅", "warning": "⚠️", "critical": "🔴", "info": "ℹ️"}
    for f in flagged:
        icon = status_icons.get(f["status"], "")
        ratio_lines.append(
            f"  {icon} {f['label']}: {f['value']}{f['unit']} [{f['status'].upper()}]"
        )

    raw_str   = "\n".join(raw_lines) or "  (Không có dữ liệu)"
    ratio_str = "\n".join(ratio_lines) or "  (Không tính được tỷ số)"

    critical_count = sum(1 for f in flagged if f["status"] == "critical")
    warning_count  = sum(1 for f in flagged if f["status"] == "warning")

    return f"""Bạn là chuyên gia phân tích tài chính. Dưới đây là dữ liệu BCTC {period_str}:

CHỈ TIÊU GỐC:
{raw_str}

TỶ SỐ TÀI CHÍNH:
{ratio_str}

Tóm tắt: {critical_count} chỉ số CRITICAL, {warning_count} chỉ số WARNING.

Hãy viết báo cáo phân tích tài chính theo cấu trúc (tiếng Việt):

1. ĐÁNH GIÁ TỔNG QUAN (2-3 câu): Sức khỏe tài chính chung của doanh nghiệp.
2. ĐIỂM MẠNH: Các chỉ số tích cực và lý do.
3. RỦI RO & ĐIỂM YẾU: Phân tích các chỉ số CRITICAL/WARNING, nguyên nhân tiềm ẩn.
4. KHUYẾN NGHỊ: 3 hành động cụ thể, ưu tiên theo mức độ khẩn.

Yêu cầu:
- Dùng thuật ngữ chuẩn VAS/IFRS kết hợp với ngôn ngữ dễ hiểu cho Ban Giám đốc
- Liên kết số liệu cụ thể khi đưa ra nhận xét
- Độ dài: 200-300 từ"""
