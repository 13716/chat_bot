"""
Test suite UC#7 — AR/AP Aging Analysis
Chạy: python test_aging.py
"""
import sys
from datetime import date, timedelta

sys.path.insert(0, ".")

from services.aging import (
    parse_excel_aging, summarize_aging, build_aging_prompt,
    _assign_bucket, _detect_aging_col, _parse_date, _vendor_risk, _portfolio_risk,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


print("=" * 60)
print("TEST 1: Bucket assignment (phan nhom tuoi no)")
print("=" * 60)
check("days=-5 -> current",   _assign_bucket(-5) == "current")
check("days=0 -> current",    _assign_bucket(0) == "current")
check("days=1 -> 1_30",       _assign_bucket(1) == "1_30")
check("days=30 -> 1_30",      _assign_bucket(30) == "1_30")
check("days=31 -> 31_60",     _assign_bucket(31) == "31_60")
check("days=60 -> 31_60",     _assign_bucket(60) == "31_60")
check("days=61 -> 61_90",     _assign_bucket(61) == "61_90")
check("days=90 -> 61_90",     _assign_bucket(90) == "61_90")
check("days=91 -> over_90",   _assign_bucket(91) == "over_90")
check("days=365 -> over_90",  _assign_bucket(365) == "over_90")

print()
print("=" * 60)
print("TEST 2: Column detection (co dau / khong dau)")
print("=" * 60)
check("'Khach hang' -> vendor",     _detect_aging_col("Khach hang") == "vendor")
check("'Khách hàng' -> vendor",     _detect_aging_col("Khách hàng") == "vendor")
check("'Customer' -> vendor",       _detect_aging_col("Customer") == "vendor")
check("'So tien' -> amount",        _detect_aging_col("So tien") == "amount")
check("'Số tiền (VND)' -> amount",  _detect_aging_col("Số tiền (VND)") == "amount")
check("'Ngay den han' -> due_date", _detect_aging_col("Ngay den han") == "due_date")
check("'Ngày đến hạn' -> due_date", _detect_aging_col("Ngày đến hạn") == "due_date")
check("'Số HĐ' -> invoice_no",      _detect_aging_col("Số HĐ") == "invoice_no")
check("'random col' -> None",       _detect_aging_col("xyz123") is None)

print()
print("=" * 60)
print("TEST 3: Date parsing (nhieu dinh dang)")
print("=" * 60)
check("'15/03/2026'",  _parse_date("15/03/2026") == date(2026, 3, 15))
check("'2026-03-15'",  _parse_date("2026-03-15") == date(2026, 3, 15))
check("'15-03-2026'",  _parse_date("15-03-2026") == date(2026, 3, 15))
check("datetime obj",  _parse_date(date(2026, 3, 15)) == date(2026, 3, 15))
check("None -> None",  _parse_date(None) is None)
check("garbage -> None", _parse_date("abc") is None)

print()
print("=" * 60)
print("TEST 4: Risk scoring")
print("=" * 60)
check("vendor 60% >90d -> CRITICAL", _vendor_risk(0.6, 100) == "CRITICAL")
check("vendor max 200d -> CRITICAL", _vendor_risk(0.1, 200) == "CRITICAL")
check("vendor max 100d -> HIGH",     _vendor_risk(0.1, 100) == "HIGH")
check("vendor max 70d -> MEDIUM",    _vendor_risk(0.1, 70) == "MEDIUM")
check("vendor clean -> LOW",         _vendor_risk(0.0, 10) == "LOW")
check("portfolio 50% -> CRITICAL",   _portfolio_risk(0.5) == "CRITICAL")
check("portfolio 35% -> HIGH",       _portfolio_risk(0.35) == "HIGH")
check("portfolio 20% -> MEDIUM",     _portfolio_risk(0.20) == "MEDIUM")
check("portfolio 3% -> LOW",         _portfolio_risk(0.03) == "LOW")

print()
print("=" * 60)
print("TEST 5: Parse Excel sample (end-to-end)")
print("=" * 60)
rows, val = parse_excel_aging(r"D:\python\VSF\data\CongNo_AR_mau_2025.xlsx")
check("parse valid", val.is_valid)
check("parse 12 rows", len(rows) == 12, f"got {len(rows)}")
check("rows have bucket", all("bucket" in r for r in rows))
check("rows have days_overdue", all("days_overdue" in r for r in rows))

summary = summarize_aging(rows)
check("total = 2.77 ty", summary["total_outstanding"] == 2_770_000_000,
      f"got {summary['total_outstanding']:,.0f}")
check("risk = HIGH", summary["risk_level"] == "HIGH", f"got {summary['risk_level']}")
check("5 buckets present", len(summary["buckets"]) == 5)
check("over_90 = 40.6%", abs(summary["buckets"]["over_90"]["pct"] - 40.6) < 0.1,
      f"got {summary['buckets']['over_90']['pct']}")
check("5 vendors", len(summary["vendors"]) == 5, f"got {len(summary['vendors'])}")
check("top vendor = Dai Viet",
      "Đại Việt" in summary["vendors"][0]["vendor"],
      f"got {summary['vendors'][0]['vendor']}")
check("risk_reasons non-empty", len(summary["risk_reasons"]) > 0)

print()
print("=" * 60)
print("TEST 6: Bucket totals sum check")
print("=" * 60)
bucket_sum = sum(b["amount"] for b in summary["buckets"].values())
check("buckets sum = total", bucket_sum == summary["total_outstanding"],
      f"buckets={bucket_sum:,.0f} vs total={summary['total_outstanding']:,.0f}")
pct_sum = sum(b["pct"] for b in summary["buckets"].values())
check("pct sum ~ 100%", abs(pct_sum - 100) < 0.5, f"got {pct_sum}")

print()
print("=" * 60)
print("TEST 7: Edge cases")
print("=" * 60)
# Empty rows
empty_summary = summarize_aging([])
check("empty rows -> empty summary", empty_summary == {})
# Prompt builder
prompt = build_aging_prompt(summary, "Cong no Phai Thu (AR)")
check("prompt non-empty", len(prompt) > 100)
check("prompt has total", "2,770,000,000" in prompt)
check("prompt has risk", "HIGH" in prompt)
check("empty summary -> safe prompt", "Khong co du lieu" in build_aging_prompt({}) or "Không có dữ liệu" in build_aging_prompt({}))

print()
print("=" * 60)
print(f"KET QUA: {PASS} PASS / {FAIL} FAIL  (tong {PASS+FAIL} test)")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
