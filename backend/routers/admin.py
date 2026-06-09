"""
Admin Router — log viewer, metrics
GET  /admin/logs          → xem log gần nhất
GET  /admin/metrics       → tổng quan hệ thống
GET  /admin/errors        → chỉ error logs
"""

from datetime import date
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])

LOG_DIR = Path(__file__).parent.parent / "logs"


def _read_log(filename: str, tail: int = 100, level_filter: str | None = None) -> list[dict]:
    """Đọc log file JSON, trả về list records."""
    import json

    path = LOG_DIR / filename
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    records = []
    for line in lines[-tail * 3:]:   # Đọc nhiều hơn để sau filter còn đủ
        try:
            r = json.loads(line)
            if level_filter and r.get("record", {}).get("level", {}).get("name") != level_filter:
                continue
            rec = r.get("record", r)
            records.append({
                "time":    rec.get("time", {}).get("repr", ""),
                "level":   rec.get("level", {}).get("name", ""),
                "message": rec.get("message", ""),
                "req_id":  rec.get("extra", {}).get("req_id", "-"),
                "file":    f"{rec.get('name','')}:{rec.get('line','')}",
            })
        except Exception:
            continue

    return records[-tail:]


@router.get("/logs")
async def get_logs(
    tail: int = Query(50, ge=1, le=500, description="Số dòng cuối cần lấy"),
    level: str | None = Query(None, description="Filter: DEBUG/INFO/WARNING/ERROR"),
):
    """Xem log của ngày hôm nay."""
    today = date.today().strftime("%Y-%m-%d")
    filename = f"app_{today}.log"
    records = _read_log(filename, tail=tail, level_filter=level)

    if not records:
        # Thử đọc console log nếu file chưa có
        return {
            "date": today,
            "file": filename,
            "count": 0,
            "logs": [],
            "note": "Log file chưa có hoặc trống — server mới khởi động?",
        }

    return {"date": today, "file": filename, "count": len(records), "logs": records}


@router.get("/errors")
async def get_errors(tail: int = Query(30, ge=1, le=200)):
    """Xem chỉ error logs."""
    today = date.today().strftime("%Y-%m-%d")
    filename = f"error_{today}.log"
    records = _read_log(filename, tail=tail)

    # Fallback sang app log nếu error log chưa có
    if not records:
        filename = f"app_{today}.log"
        records = _read_log(filename, tail=tail * 3, level_filter="ERROR")

    return {
        "date": today,
        "count": len(records),
        "errors": records,
    }


@router.get("/metrics")
async def get_metrics():
    """Tổng quan hệ thống: log counts, file sizes, uptime."""
    import os, psutil
    from datetime import datetime
    from core.config import get_settings

    settings = get_settings()
    today = date.today().strftime("%Y-%m-%d")

    # Đếm log
    app_log  = LOG_DIR / f"app_{today}.log"
    err_log  = LOG_DIR / f"error_{today}.log"

    def count_lines(path: Path) -> int:
        if not path.exists(): return 0
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))

    def file_size_kb(path: Path) -> float:
        return round(path.stat().st_size / 1024, 1) if path.exists() else 0

    # System info
    try:
        proc = psutil.Process(os.getpid())
        mem_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
        cpu_pct = proc.cpu_percent(interval=0.1)
    except Exception:
        mem_mb = cpu_pct = 0

    return {
        "app": settings.APP_NAME,
        "date": today,
        "logs": {
            "app_lines":  count_lines(app_log),
            "app_size_kb": file_size_kb(app_log),
            "error_lines": count_lines(err_log),
            "error_size_kb": file_size_kb(err_log),
            "log_dir": str(LOG_DIR),
        },
        "process": {
            "memory_mb": mem_mb,
            "cpu_percent": cpu_pct,
            "pid": os.getpid(),
        },
        "config": {
            "debug": settings.DEBUG,
            "llm_fallback_order": settings.LLM_FALLBACK_ORDER,
            "default_model": f"groq:{settings.GROQ_MODEL}",
        },
    }
