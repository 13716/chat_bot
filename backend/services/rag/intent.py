"""
Intent Detection — phân loại câu hỏi để quyết định flow xử lý:
- legal   → dùng RAG (câu hỏi về thông tư, điều khoản pháp lý)
- tool    → gọi tool: variance / bank_reconciliation / financial_statement / aging
- general → trả lời trực tiếp bằng LLM

Lưu ý: khi user đính kèm file Excel, router (agent.py) ép intent="tool" bất kể
keyword, vì đính Excel là tín hiệu mạnh muốn phân tích số liệu.
"""

import unicodedata
from typing import Literal

Intent = Literal["legal", "tool", "general"]


def _strip_accents(text: str) -> str:
    """Bỏ dấu + lowercase để so khớp không phụ thuộc dấu tiếng Việt.
    'Phân tích' và 'phan tich' đều thành 'phan tich'.
    Lưu ý: 'đ' (U+0111) KHÔNG bị NFD tách → phải thay thủ công thành 'd'."""
    s = text.lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

_LEGAL_KEYWORDS = [
    "thông tư", "điều ", "khoản ", "quy định", "pháp lý", "nghị định",
    "luật kế toán", "chuẩn mực", "vas ", "tt99", "tt200", "tt133",
    "chế độ kế toán", "hạch toán", "tài khoản số", "định khoản",
    "bút toán", "kết chuyển", "ghi nhận doanh thu", "điều kiện ghi nhận",
    "trích khấu hao", "phương pháp khấu hao", "vốn hóa", "phân bổ chi phí",
    "dự phòng", "trích lập dự phòng", "khấu trừ thuế", "thuế gtgt",
    "thuế tndn", "hoàn thuế", "khai thuế", "chứng từ kế toán",
    "sổ kế toán", "báo cáo tài chính", "kiểm toán", "niên độ kế toán",
]

_TOOL_KEYWORDS = [
    # UC#2 — Variance
    "variance", "chênh lệch ngân sách", "thực tế vs kế hoạch",
    "actual vs budget", "phân tích p&l", "phân tích chênh lệch doanh thu",
    "phân tích chênh lệch chi phí", "vượt ngưỡng",
    # UC#5 — Bank Reconciliation
    "bank reconciliation", "đối chiếu ngân hàng", "sao kê ngân hàng",
    "reconcile", "giao dịch không khớp", "chênh lệch sổ sách vs ngân hàng",
    "outstanding items", "bank statement",
    # UC#1 — Financial Statement (cụm có "phân tích/đọc/tính" để không nuốt câu hỏi pháp lý)
    "phân tích báo cáo tài chính", "phân tích bctc", "đọc báo cáo tài chính",
    "phân tích tài chính", "tỷ số tài chính", "chỉ số tài chính", "phân tích tỷ số",
    "sức khỏe tài chính", "tính roe", "tính roa", "biên lợi nhuận",
    # UC#7 — AR/AP Aging
    "tuổi nợ", "aging", "công nợ phải thu", "công nợ phải trả",
    "nợ quá hạn", "phân tích công nợ", "danh sách công nợ",
    "ar aging", "ap aging", "phải thu phải trả",
]


def detect_intent(message: str) -> Intent:
    """
    Phân loại câu hỏi theo 3 intent (rule-based, không cần LLM).
    Tool keywords được check trước vì chúng có overlap với legal.
    So khớp không phụ thuộc dấu → người dùng gõ không dấu vẫn nhận đúng.
    """
    norm = _strip_accents(message)

    if any(_strip_accents(kw) in norm for kw in _TOOL_KEYWORDS):
        return "tool"

    if any(_strip_accents(kw) in norm for kw in _LEGAL_KEYWORDS):
        return "legal"

    return "general"
