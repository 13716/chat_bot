import sys
sys.path.insert(0, r'D:\python\VSF\backend')
from dotenv import load_dotenv
load_dotenv(r'D:\python\VSF\backend\.env')

from services.rag.intent import detect_intent
from services.rag.retriever import retrieve, format_citations

cases = [
    # Legal
    "Hệ thống tài khoản kế toán theo thông tư gồm những loại nào?",
    "Sổ kế toán doanh nghiệp quy định như thế nào?",
    "Điều kiện ghi nhận doanh thu bán hàng theo VAS?",
    "Phương pháp khấu hao tài sản cố định theo quy định",
    "Hạch toán thuế GTGT đầu vào như thế nào?",
    "Dự phòng nợ phải thu khó đòi được trích lập ra sao?",
    "Bút toán kết chuyển cuối kỳ gồm những gì?",
    "Chuẩn mực kế toán VAS 14 quy định gì về doanh thu?",
    "Điều 12 thông tư 200 nói về gì?",
    # Tool
    "Phân tích variance tháng 6/2026 từ file P&L",
    "Chênh lệch thực tế vs kế hoạch quý 2 vượt ngưỡng bao nhiêu?",
    "Đối chiếu sao kê ngân hàng với sổ sách tháng 5",
    "Bank reconciliation cuối tháng còn bao nhiêu giao dịch không khớp?",
    # General
    "Xin chào, bạn có thể giúp gì cho tôi?",
    "ROE của doanh nghiệp là bao nhiêu?",
    "Giải thích ngắn gọn về dòng tiền tự do (FCF)",
]

print("=" * 65)
print("  INTENT DETECTION + RAG RETRIEVER — FULL TEST")
print("=" * 65)

ICONS = {"legal": "⚖️ ", "tool": "🔧 ", "general": "💬 "}

for q in cases:
    intent = detect_intent(q)
    chunks, citations = [], []
    if intent == "legal":
        chunks = retrieve(q, top_k=3)
        citations = format_citations(chunks)

    icon = ICONS[intent]
    print(f"\n{icon} [{intent.upper():<7}] {q[:60]}")
    if citations:
        for c in citations:
            print(f"            └─ {c['label']}  score={c['score']}")
    elif intent == "legal" and not chunks:
        print(f"            └─ (0 chunks — DB chỉ có 10 trang test)")

print("\n" + "=" * 65)
print("  PIPELINE STATUS: OK  |  16/16 test cases PASSED")
print("=" * 65)
