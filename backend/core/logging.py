"""
Centralized logging configuration — loguru + structured JSON
"""
import sys
import uuid
import time
from pathlib import Path
from loguru import logger
from contextvars import ContextVar

# ── Request context (mỗi request có request_id riêng) ────────────────────
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

def get_request_id() -> str:
    return request_id_var.get()

# ── Log directory ─────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Setup loguru ──────────────────────────────────────────────────────────

def setup_logging(debug: bool = False):
    logger.remove()  # Xóa handler mặc định

    level = "DEBUG" if debug else "INFO"

    # ── Console: màu sắc, dễ đọc khi dev ──
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[req_id]}</cyan> | "
            "<blue>{name}</blue>:<yellow>{line}</yellow> | "
            "{message}"
        ),
    )

    # ── File: JSON structured, rotation hàng ngày ──
    logger.add(
        LOG_DIR / "app_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="00:00",       # Xoay file lúc nửa đêm
        retention="30 days",    # Giữ 30 ngày
        compression="gz",       # Nén file cũ
        serialize=True,         # JSON format
        enqueue=True,           # Thread-safe
    )

    # ── Error file riêng: chỉ ERROR trở lên ──
    logger.add(
        LOG_DIR / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation="00:00",
        retention="90 days",
        serialize=True,
        enqueue=True,
    )

    # Patch logger để luôn có request_id
    logger.configure(
        patcher=lambda record: record["extra"].update(
            req_id=request_id_var.get()
        )
    )

    logger.info(f"Logging setup OK — logs tại: {LOG_DIR}")
