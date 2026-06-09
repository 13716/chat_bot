"""
RAG Retriever — tìm kiếm chunks pháp lý từ pgvector (Supabase)

Schema: law_chunks(id, source, article, article_title, topic, content, embedding vector(384))
Model: all-MiniLM-L6-v2 (384 chiều, offline cache)
"""

import os
import re
from typing import Optional
from loguru import logger
from core.config import get_settings

settings = get_settings()

# Lazy singleton — load sentence-transformers 1 lần duy nhất khi cần
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model loaded: all-MiniLM-L6-v2")
    return _embedder


def _embed(text: str) -> list[float]:
    model = _get_embedder()
    return model.encode([text], normalize_embeddings=True)[0].tolist()


def _extract_article_num(query: str) -> Optional[str]:
    """
    Trích xuất số điều nếu user hỏi trực tiếp.
    VD: "Điều 11 là gì?" → "11"
        "theo điều 19a thì..." → "19a"
    """
    m = re.search(r"đi[eề]u\s+(\d+[a-z]?)", query, re.IGNORECASE)
    return m.group(1) if m else None


def retrieve(query: str, top_k: int = 5, min_score: float = 0.45) -> list[dict]:
    """
    Tìm kiếm chunks pháp lý liên quan đến query.

    Chiến lược hybrid:
    - Nếu query nhắc đến "Điều X" cụ thể → filter trực tiếp theo article number
      (không dùng min_score, đảm bảo tìm thấy dù câu ngắn)
    - Nếu không → cosine similarity thuần với min_score threshold

    Returns: list of {source, article, article_title, topic, content, score}
    """
    if not settings.DATABASE_URL:
        logger.warning("DATABASE_URL chưa cấu hình — bỏ qua RAG")
        return []

    try:
        import psycopg2

        embedding = _embed(query)
        vec_str   = f"[{','.join(map(str, embedding))}]"
        article_num = _extract_article_num(query)

        conn = psycopg2.connect(settings.DATABASE_URL, connect_timeout=5)
        with conn.cursor() as cur:

            if article_num:
                # ── Hybrid: filter theo số điều + sort theo score ──────────
                # Không dùng min_score — nếu user hỏi Điều X thì trả về dù score thấp
                cur.execute(
                    """
                    SELECT source, article, article_title, topic, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM law_chunks
                    WHERE article = %s
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (vec_str, article_num, top_k),
                )
                rows = cur.fetchall()

                # Nếu số điều chưa có trong DB → fallback cosine search
                if not rows:
                    logger.warning(f"Điều {article_num} chưa có trong DB → fallback vector search")
                    cur.execute(
                        """
                        SELECT source, article, article_title, topic, content,
                               1 - (embedding <=> %s::vector) AS score
                        FROM law_chunks
                        WHERE 1 - (embedding <=> %s::vector) > %s
                        ORDER BY score DESC
                        LIMIT %s
                        """,
                        (vec_str, vec_str, min_score, top_k),
                    )
                    rows = cur.fetchall()
                    logger.info(f"RAG fallback vector: '{query[:50]}' → {len(rows)} chunks")
                else:
                    logger.info(f"RAG article filter: Điều {article_num} → {len(rows)} chunks")

            else:
                # ── Thuần cosine similarity ───────────────────────────────
                cur.execute(
                    """
                    SELECT source, article, article_title, topic, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM law_chunks
                    WHERE 1 - (embedding <=> %s::vector) > %s
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (vec_str, vec_str, min_score, top_k),
                )
                rows = cur.fetchall()
                logger.info(f"RAG vector: '{query[:50]}' → {len(rows)} chunks")

        conn.close()

        return [
            {
                "source":        r[0],
                "article":       r[1] or "",
                "article_title": r[2] or "",
                "topic":         r[3] or "",
                "content":       r[4],
                "score":         round(float(r[5]), 3),
            }
            for r in rows
        ]

    except Exception as exc:
        logger.warning(f"RAG retrieve failed: {exc}")
        return []


def format_context(chunks: list[dict]) -> str:
    """
    Format retrieved chunks thành context block để gắn vào system prompt.
    Giới hạn mỗi chunk 600 ký tự để không làm bùng ngữ cảnh.
    """
    if not chunks:
        return ""

    lines = [
        "\n\n---",
        "## Căn cứ pháp lý từ cơ sở dữ liệu (tìm kiếm vector)\n",
        "Sử dụng các trích dẫn dưới đây để trả lời. Khi trích dẫn, ghi rõ số Điều và Thông tư.",
        "",
    ]
    for i, c in enumerate(chunks, 1):
        citation = (
            f"{c['source']} — Điều {c['article']}" if c["article"] else c["source"]
        )
        lines.append(f"**[{i}] {citation}**")
        lines.append(c["content"][:600])
        lines.append("")

    return "\n".join(lines)


def format_citations(chunks: list[dict]) -> list[dict]:
    """
    Tạo danh sách citation badges để frontend hiển thị sau response.
    Deduplicate theo (source, article).
    """
    seen: set[str] = set()
    citations: list[dict] = []

    for c in chunks:
        key = f"{c['source']}-{c['article']}"
        if key in seen:
            continue
        seen.add(key)

        label = (
            f"📎 {c['source']} — Điều {c['article']}"
            if c["article"]
            else f"📎 {c['source']}"
        )
        citations.append(
            {
                "source": c["source"],
                "article": c["article"],
                "article_title": c["article_title"],
                "topic": c["topic"],
                "score": c["score"],
                "label": label,
            }
        )

    return citations
