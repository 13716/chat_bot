"""
RAG Ingestion Pipeline — TT99/2025 (và các thông tư khác)
Chạy 1 lần/năm khi có thông tư mới

Usage:
    python scripts/ingest_laws.py --file data/TT99_2025.pdf --source TT99/2025

Requirements:
    pip install pymupdf google-genai pgvector psycopg2-binary sentence-transformers
"""

import argparse
import os
import sys
import time
import json
import re
import tempfile
from pathlib import Path
from typing import Optional

# ── Add backend root to path ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

import fitz  # PyMuPDF
from google import genai
from loguru import logger
import psycopg2
from psycopg2.extras import execute_values

# ── Config ────────────────────────────────────────────────────────────────

# Fallback chain: thử lần lượt từng model khi bị rate limit / lỗi
# Mỗi model có quota riêng → tổng cộng nhiều hơn dùng 1 model
FALLBACK_MODELS = [
    "gemini-2.5-flash",        # Primary: tốt nhất, nhưng quota 20/ngày
    "gemini-2.5-flash-lite",   # Fallback 1: nhẹ hơn, quota khác
    "gemini-3.1-flash-lite",   # Fallback 2: gen mới
    "gemini-3.5-flash",        # Fallback 3: gen mới nhất
]

PAGES_PER_CALL = 4          # 4 trang/call → ~156 calls cho 622 trang
DELAY_SECONDS  = 20         # 20s giữa calls
RENDER_DPI     = 150        # DPI render ảnh → đủ để OCR, không quá nặng
CHUNK_SIZE_MAX = 800        # Ký tự tối đa mỗi chunk
CHUNK_OVERLAP  = 100        # Overlap giữa chunk

# Checkpoint: lưu tiến độ sau mỗi batch → resume nếu crash
CHECKPOINT_DIR = Path(__file__).parent.parent / "data" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL   = os.getenv("DATABASE_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Gemini client ─────────────────────────────────────────────────────────

# ── Checkpoint functions ──────────────────────────────────────────────────

def checkpoint_path(source: str) -> Path:
    """Đường dẫn file checkpoint cho một source cụ thể."""
    safe_name = source.replace("/", "_").replace(" ", "_")
    return CHECKPOINT_DIR / f"{safe_name}.json"


def load_checkpoint(source: str) -> dict:
    """
    Load checkpoint nếu có.
    Trả về dict với:
    - completed_batches: list[{start, end, text}] — các batch đã thành công
    - failed_pages: list[int] — các trang bị lỗi
    """
    path = checkpoint_path(source)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        completed = len(data.get("completed_batches", []))
        last_page = data.get("last_completed_page", 0)
        logger.info(f"📂 Tìm thấy checkpoint: {completed} batches, đến trang {last_page}")
        return data
    return {"completed_batches": [], "failed_pages": [], "last_completed_page": 0}


def save_checkpoint(source: str, checkpoint: dict) -> None:
    """Lưu checkpoint sau mỗi batch thành công."""
    path = checkpoint_path(source)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_checkpoint(source: str) -> None:
    """Xóa checkpoint sau khi ingest hoàn tất."""
    path = checkpoint_path(source)
    if path.exists():
        path.unlink()
        logger.info("🗑️ Đã xóa checkpoint file")


def get_completed_text(checkpoint: dict) -> str:
    """Ghép toàn bộ text từ các batches đã completed."""
    batches = sorted(checkpoint.get("completed_batches", []), key=lambda b: b["start"])
    return "\n".join(b["text"] for b in batches)


def get_next_start_page(checkpoint: dict, default_start: int) -> int:
    """Trang tiếp theo cần xử lý (bỏ qua những trang đã xong)."""
    if not checkpoint.get("completed_batches"):
        return default_start
    return checkpoint["last_completed_page"] + 1


# ── Gemini client ─────────────────────────────────────────────────────────

def get_gemini_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình trong .env")
    return genai.Client(api_key=GEMINI_API_KEY)


EXTRACT_PROMPT = """Bạn đang xem {n} trang từ văn bản pháp lý kế toán Việt Nam.
Hãy trích xuất TOÀN BỘ nội dung text, giữ nguyên:
- Cấu trúc: Chương, Điều, Khoản, Điểm (a, b, c...)
- Tiêu đề, số điều khoản
- Nội dung đầy đủ, không bỏ sót

CHỈ trả về text thuần, không thêm giải thích hay markdown.
Nếu trang trống hoặc chỉ có hình ảnh/bảng biểu không đọc được, ghi: [TRANG TRỐNG]"""


def extract_text_from_pages(client: genai.Client, images: list[bytes]) -> str:
    """
    Gửi batch ảnh lên Gemini để extract text.

    Fallback chain: thử lần lượt FALLBACK_MODELS khi gặp:
    - 429 RESOURCE_EXHAUSTED: quota hết → thử model tiếp theo
    - 503 UNAVAILABLE: server overload → chờ rồi thử lại
    - Server disconnected → thử lại với model khác

    Nếu tất cả model đều fail → raise Exception để caller ghi vào failed_pages
    """
    from google.genai import types

    parts = [types.Part.from_text(text=EXTRACT_PROMPT.format(n=len(images)))]
    for img_bytes in images:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

    last_error = None

    # Thử từng model trong fallback chain
    for model in FALLBACK_MODELS:
        max_retries = 2  # Mỗi model thử tối đa 2 lần
        for attempt in range(max_retries):
            try:
                logger.debug(f"Thử {model} (attempt {attempt+1})...")
                response = client.models.generate_content(
                    model=model,
                    contents=[types.Content(parts=parts, role="user")],
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=8192,
                    ),
                )
                if model != FALLBACK_MODELS[0]:
                    logger.info(f"✅ Fallback thành công với {model}")
                return response.text or ""

            except Exception as e:
                err_str = str(e)
                last_error = e

                if "429" in err_str:
                    # Quota hết cho model này → không retry, thử model tiếp theo
                    logger.warning(f"⚠️ {model}: quota hết, thử model tiếp theo...")
                    break  # Thoát vòng retry, sang model tiếp

                elif "503" in err_str or "disconnected" in err_str.lower():
                    # Server tạm thời quá tải → chờ ngắn rồi thử lại
                    wait = 30
                    logger.warning(f"⚠️ {model}: server lỗi, chờ {wait}s rồi retry...")
                    time.sleep(wait)
                    # Nếu đã retry hết → thử model tiếp
                else:
                    # Lỗi khác (network, timeout...) → thử model tiếp
                    logger.warning(f"⚠️ {model}: lỗi {type(e).__name__}, thử model tiếp...")
                    break

    # Tất cả models đều fail
    raise Exception(f"Tất cả {len(FALLBACK_MODELS)} models đều thất bại. Lỗi cuối: {last_error}")


# ── PDF → Images ──────────────────────────────────────────────────────────

def pdf_to_page_images(pdf_path: str, start: int = 0, end: Optional[int] = None) -> list[bytes]:
    """Convert PDF pages to PNG bytes."""
    doc = fitz.open(pdf_path)
    total = len(doc)
    end = min(end or total, total)
    images = []
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    for i in range(start, end):
        pix = doc[i].get_pixmap(matrix=mat, colorspace=fitz.csGRAY)  # grayscale → nhỏ hơn
        images.append(pix.tobytes("png"))
    doc.close()
    return images


# ── Smart Chunking theo cấu trúc pháp lý VN ─────────────────────────────

def smart_chunk(text: str, source: str) -> list[dict]:
    """
    Chia text thành chunks theo cấu trúc Điều/Khoản.
    Trả về list[{content, metadata}]
    """
    chunks = []

    # Regex detect điều
    dieu_pattern = re.compile(
        r'(Điều\s+\d+[a-z]?\.\s+[^\n]+)', re.IGNORECASE | re.UNICODE
    )

    # Split text tại các Điều
    parts = dieu_pattern.split(text)

    current_article = "Tổng quát"
    current_content = ""

    for part in parts:
        if dieu_pattern.match(part.strip()):
            # Lưu chunk trước
            if current_content.strip():
                chunks.extend(_make_chunks(current_content, source, current_article))
            current_article = part.strip()
            current_content = part
        else:
            current_content += part

    # Chunk cuối
    if current_content.strip():
        chunks.extend(_make_chunks(current_content, source, current_article))

    return chunks


def _make_chunks(text: str, source: str, article: str) -> list[dict]:
    """Chia đoạn text thành chunks nhỏ nếu quá dài."""
    text = text.strip()
    if not text or text == "[TRANG TRỐNG]":
        return []

    # Extract số điều nếu có
    m = re.match(r'Điều\s+(\d+[a-z]?)', article, re.IGNORECASE)
    article_num = m.group(1) if m else ""

    # Detect topic từ tiêu đề điều
    topic = _detect_topic(article)

    chunks = []
    if len(text) <= CHUNK_SIZE_MAX:
        chunks.append({
            "content": text,
            "source": source,
            "article": article_num,
            "article_title": article[:100],
            "topic": topic,
        })
    else:
        # Chia nhỏ với overlap
        words = text.split()
        current = []
        current_len = 0
        for word in words:
            current.append(word)
            current_len += len(word) + 1
            if current_len >= CHUNK_SIZE_MAX:
                chunk_text = " ".join(current)
                chunks.append({
                    "content": chunk_text,
                    "source": source,
                    "article": article_num,
                    "article_title": article[:100],
                    "topic": topic,
                })
                # Overlap: giữ lại N từ cuối
                overlap_words = int(CHUNK_OVERLAP / 5)  # ~5 chars/word
                current = current[-overlap_words:]
                current_len = sum(len(w) + 1 for w in current)
        if current:
            chunks.append({
                "content": " ".join(current),
                "source": source,
                "article": article_num,
                "article_title": article[:100],
                "topic": topic,
            })

    return chunks


def _detect_topic(text: str) -> str:
    """Detect chủ đề từ tiêu đề điều."""
    text_lower = text.lower()
    topics = {
        "GTGT": ["giá trị gia tăng", "gtgt", "thuế đầu vào", "thuế đầu ra"],
        "TNDN": ["thu nhập doanh nghiệp", "tndn"],
        "TNCN": ["thu nhập cá nhân", "tncn"],
        "TSCĐ": ["tài sản cố định", "tscđ", "khấu hao"],
        "Doanh thu": ["doanh thu", "bán hàng"],
        "Chi phí": ["chi phí", "giá vốn"],
        "Tiền mặt": ["tiền mặt", "tiền gửi", "ngân hàng"],
        "Công nợ": ["phải thu", "phải trả", "công nợ"],
        "BCTC": ["báo cáo tài chính", "bảng cân đối", "kết quả kinh doanh"],
        "Hóa đơn": ["hóa đơn", "chứng từ"],
    }
    for topic, keywords in topics.items():
        if any(kw in text_lower for kw in keywords):
            return topic
    return "Khác"


# ── Embedding ─────────────────────────────────────────────────────────────

def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Tạo embeddings bằng sentence-transformers (offline mode).

    Tại sao offline mode?
    - Model 'paraphrase-multilingual-mpnet-base-v2' đã có trong cache (~450MB)
    - HF_HUB_OFFLINE=1: ngăn thư viện gọi mạng để verify/update model
    - Tránh lỗi mạng và symlink trên Windows

    Vector 768 chiều — khớp với schema pgvector đã tạo.
    """
    import os
    # Force offline: dùng model đã cache, không gọi HuggingFace
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    from sentence_transformers import SentenceTransformer
    # all-MiniLM-L6-v2: 384 chiều, đã có trong cache, load được offline
    # paraphrase-multilingual-mpnet-base-v2: 768 chiều nhưng cache bị hỏng symlink Windows
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,  # Normalize → cosine similarity chuẩn hơn
    )
    return embeddings.tolist()


# ── Database ──────────────────────────────────────────────────────────────

def setup_db(conn) -> None:
    """Tạo bảng law_chunks nếu chưa có."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS law_chunks (
                id          SERIAL PRIMARY KEY,
                source      TEXT NOT NULL,           -- VD: TT99/2025
                article     TEXT,                    -- VD: 15
                article_title TEXT,                  -- VD: Điều 15. Khấu trừ thuế...
                topic       TEXT,                    -- VD: GTGT
                content     TEXT NOT NULL,
                embedding   vector(384),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS law_chunks_embedding_idx
            ON law_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        conn.commit()
    logger.info("✅ DB setup hoàn tất")


def save_chunks(conn, chunks: list[dict], embeddings: list[list[float]]) -> int:
    """Lưu chunks + embeddings vào PostgreSQL."""
    records = [
        (
            c["source"], c["article"], c["article_title"],
            c["topic"], c["content"], f"[{','.join(map(str, e))}]"
        )
        for c, e in zip(chunks, embeddings)
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO law_chunks (source, article, article_title, topic, content, embedding)
            VALUES %s
        """, records)
        conn.commit()
    return len(records)


def delete_existing(conn, source: str) -> int:
    """Xóa chunks cũ của source này (khi update thông tư mới)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM law_chunks WHERE source = %s", (source,))
        deleted = cur.rowcount
        conn.commit()
    return deleted


# ── Main Pipeline ─────────────────────────────────────────────────────────

def run_ingestion(pdf_path: str, source: str, start_page: int = 0, end_page: Optional[int] = None,
                  wipe: bool = True):
    logger.info(f"🚀 Bắt đầu ingest: {pdf_path}")
    logger.info(f"   Source: {source}")

    # Validate
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"Không tìm thấy file: {pdf_path}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    end_page = end_page or total_pages
    logger.info(f"   Tổng trang: {total_pages} | Xử lý: {start_page}–{end_page}")

    # Setup Gemini client
    gemini = get_gemini_client()

    # Kết nối DB chỉ để setup schema + xóa chunks cũ, rồi đóng lại
    # Lý do: extraction + embedding mất 5-50 phút → Supabase timeout connection idle
    conn_setup = psycopg2.connect(DATABASE_URL)
    setup_db(conn_setup)

    # Xóa chunks cũ — CHỈ khi wipe=True (re-ingest từ đầu).
    # Khi append/resume batch mới (wipe=False) → KHÔNG xóa, giữ data batch trước.
    if wipe:
        deleted = delete_existing(conn_setup, source)
        if deleted:
            logger.info(f"   🗑️ Đã xóa {deleted} chunks cũ của {source}")
    else:
        logger.info(f"   ➕ APPEND mode — giữ nguyên chunks cũ của {source}")
    conn_setup.close()  # Đóng sau khi setup xong

    # ── Phase 1: Extract text qua Gemini (có checkpoint + fallback) ──
    logger.info("📖 Phase 1: Extract text từ PDF qua Gemini Vision...")

    # Load checkpoint: nếu đã chạy trước, skip các trang đã xong
    ckpt = load_checkpoint(source)
    actual_start = get_next_start_page(ckpt, start_page)
    failed_pages: list[int] = ckpt.get("failed_pages", [])
    total_calls = len(ckpt.get("completed_batches", []))

    if actual_start > start_page:
        logger.info(f"   ⏭️ Resume từ trang {actual_start} (đã có {total_calls} batches trong checkpoint)")

    for batch_start in range(actual_start, end_page, PAGES_PER_CALL):
        batch_end = min(batch_start + PAGES_PER_CALL, end_page)
        pages_label = f"{batch_start+1}–{batch_end}"

        try:
            images = pdf_to_page_images(pdf_path, batch_start, batch_end)
            text = extract_text_from_pages(gemini, images)
            total_calls += 1

            pages_done = batch_end - start_page
            pages_total = end_page - start_page
            pct = pages_done / pages_total * 100
            logger.info(f"   ✅ Trang {pages_label} | {pct:.0f}% | Call #{total_calls}")

            # Lưu checkpoint ngay sau mỗi batch thành công
            # → Nếu crash bất cứ lúc nào, text này không bị mất
            ckpt["completed_batches"].append({
                "start": batch_start,
                "end": batch_end - 1,
                "text": text,
            })
            ckpt["last_completed_page"] = batch_end - 1
            # Xóa khỏi failed nếu trang này đã retry thành công
            ckpt["failed_pages"] = [p for p in ckpt["failed_pages"]
                                     if p not in range(batch_start, batch_end)]
            save_checkpoint(source, ckpt)  # Ghi file JSON ngay lập tức

        except Exception as e:
            logger.warning(f"   ⚠️ Lỗi trang {pages_label}: {e}")
            new_failed = list(range(batch_start, batch_end))
            failed_pages.extend(new_failed)
            ckpt["failed_pages"] = list(set(ckpt.get("failed_pages", []) + new_failed))
            save_checkpoint(source, ckpt)  # Lưu cả danh sách trang lỗi

        if batch_end < end_page:
            time.sleep(DELAY_SECONDS)

    # Ghép toàn bộ text từ checkpoint (đúng thứ tự trang)
    all_text = get_completed_text(ckpt)
    logger.info(f"✅ Extract xong | Tổng text: {len(all_text):,} ký tự | Lỗi: {len(failed_pages)} trang")

    # Save raw text để debug
    raw_path = Path(pdf_path).parent / f"{source.replace('/', '_')}_raw.txt"
    raw_path.write_text(all_text, encoding="utf-8")
    logger.info(f"💾 Raw text lưu tại: {raw_path}")

    # ── Phase 2: Chunking ──
    logger.info("✂️ Phase 2: Smart chunking...")
    chunks = smart_chunk(all_text, source)
    logger.info(f"   Tổng chunks: {len(chunks)}")

    # Stats
    topics = {}
    for c in chunks:
        topics[c["topic"]] = topics.get(c["topic"], 0) + 1
    logger.info(f"   Phân bổ topic: {topics}")

    # ── Phase 3: Embedding ──
    logger.info("🔢 Phase 3: Tạo embeddings...")
    texts = [c["content"] for c in chunks]
    embeddings = get_embeddings(texts)
    logger.info(f"   Embedding shape: {len(embeddings)} x {len(embeddings[0])}")

    # ── Phase 4: Save to DB ──
    logger.info("💾 Phase 4: Lưu vào pgvector...")
    # Reconnect mới — connection cũ đã timeout sau quá trình extraction + embedding
    conn = psycopg2.connect(DATABASE_URL)
    saved = save_chunks(conn, chunks, embeddings)
    conn.close()

    # Xóa checkpoint — ingest hoàn tất, không cần resume nữa
    clear_checkpoint(source)

    logger.info(f"""
╔══════════════════════════════════════╗
║  ✅ INGEST HOÀN TẤT                 ║
╠══════════════════════════════════════╣
║  Source:    {source:<26} ║
║  Trang:     {end_page - start_page:<26} ║
║  Gemini calls: {total_calls:<23} ║
║  Chunks:    {saved:<26} ║
║  Failed:    {len(failed_pages):<26} ║
╚══════════════════════════════════════╝
    """)

    if failed_pages:
        logger.warning(f"⚠️ Các trang bị lỗi (retry thủ công): {failed_pages}")

    return {"saved": saved, "failed": failed_pages, "source": source}


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest văn bản pháp lý vào pgvector")
    parser.add_argument("--file",   required=True,  help="Đường dẫn file PDF")
    parser.add_argument("--source", required=True,  help="Tên nguồn VD: TT99/2025")
    parser.add_argument("--start",  type=int, default=0,    help="Trang bắt đầu (0-indexed)")
    parser.add_argument("--end",    type=int, default=None, help="Trang kết thúc")
    parser.add_argument("--test",   action="store_true",    help="Test 10 trang đầu")
    parser.add_argument("--resume", action="store_true",    help="Tiếp tục từ checkpoint (không xóa data cũ)")
    args = parser.parse_args()

    if args.test:
        logger.info("🧪 TEST MODE: chỉ xử lý 10 trang đầu")
        run_ingestion(args.file, args.source + "_TEST", start_page=0, end_page=10)
    elif args.resume:
        # Resume: không xóa chunks cũ trong DB, tiếp tục từ checkpoint
        logger.info("⏭️ RESUME MODE: tiếp tục từ checkpoint")
        ckpt = load_checkpoint(args.source)
        next_page = get_next_start_page(ckpt, args.start or 0)
        logger.info(f"   Tiếp tục từ trang {next_page + 1}")
        run_ingestion(args.file, args.source, start_page=args.start or 0, end_page=args.end, wipe=False)
    else:
        run_ingestion(args.file, args.source, start_page=args.start, end_page=args.end)
