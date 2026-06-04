"use client"

import { useRef, useState } from "react"
import { streamVariance, streamBankRecon, VarianceMeta, ReconResult } from "@/lib/api"

interface Props {
  onResult: (userMsg: string, assistantMsg: string) => void
  onStreaming: (token: string) => void
  onDone: () => void
  disabled: boolean
}

type Mode = "variance" | "bank-recon"

export default function AccountingUpload({ onResult, onStreaming, onDone, disabled }: Props) {
  const [mode, setMode] = useState<Mode>("variance")
  const [period, setPeriod] = useState("")
  const [file1, setFile1] = useState<File | null>(null)
  const [file2, setFile2] = useState<File | null>(null)
  const [meta, setMeta] = useState<VarianceMeta | null>(null)
  const [recon, setRecon] = useState<ReconResult | null>(null)
  const ref1 = useRef<HTMLInputElement>(null)
  const ref2 = useRef<HTMLInputElement>(null)

  const reset = () => {
    setFile1(null); setFile2(null)
    setMeta(null); setRecon(null)
    if (ref1.current) ref1.current.value = ""
    if (ref2.current) ref2.current.value = ""
  }

  const run = async () => {
    if (disabled) return
    if (mode === "variance" && !file1) return
    if (mode === "bank-recon" && (!file1 || !file2)) return

    setMeta(null); setRecon(null)
    let commentary = ""

    if (mode === "variance") {
      const userMsg = `📊 Phân tích variance: **${file1!.name}**${period ? ` — ${period}` : ""}`
      onResult(userMsg, "")
      await streamVariance(
        file1!,
        period || "Kỳ báo cáo",
        (m) => setMeta(m),
        (token) => { commentary += token; onStreaming(token) },
        () => { onDone(); reset() }
      )
    } else {
      const userMsg = `🏦 Đối chiếu ngân hàng: **${file1!.name}** ↔ **${file2!.name}**`
      onResult(userMsg, "")
      await streamBankRecon(
        file1!,
        file2!,
        (r) => setRecon(r),
        (token) => { commentary += token; onStreaming(token) },
        () => { onDone(); reset() }
      )
    }
  }

  return (
    <>
      <style>{`
        .acc-panel {
          border-top: 1px solid rgba(255,255,255,0.06);
          padding: 10px 16px 8px;
          background: rgba(255,255,255,0.015);
        }
        .acc-tabs {
          display: flex; gap: 6px; margin-bottom: 10px;
        }
        .acc-tab {
          font-size: 11px; padding: 4px 12px;
          border-radius: 6px; cursor: pointer;
          border: 1px solid rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.35);
          background: transparent;
          font-family: 'Syne', sans-serif;
          transition: all .15s;
        }
        .acc-tab.active {
          background: rgba(59,130,246,0.12);
          border-color: rgba(59,130,246,0.3);
          color: rgba(255,255,255,0.8);
        }
        .acc-row {
          display: flex; gap: 8px; align-items: center;
          flex-wrap: wrap;
        }
        .acc-upload {
          display: flex; align-items: center; gap: 6px;
          padding: 5px 10px; border-radius: 7px;
          border: 1px dashed rgba(255,255,255,0.12);
          cursor: pointer; background: transparent;
          color: rgba(255,255,255,0.35); font-size: 12px;
          font-family: 'Syne', sans-serif;
          transition: all .15s; white-space: nowrap;
        }
        .acc-upload:hover { border-color: rgba(59,130,246,0.3); color: rgba(255,255,255,0.7); }
        .acc-upload.has-file { border-color: rgba(45,212,160,0.4); color: rgba(45,212,160,0.9); border-style: solid; }
        .acc-period {
          flex: 1; min-width: 120px; max-width: 180px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 7px; padding: 5px 10px;
          font-size: 12px; color: rgba(255,255,255,0.7);
          outline: none; font-family: 'Syne', sans-serif;
        }
        .acc-period::placeholder { color: rgba(255,255,255,0.18); }
        .acc-period:focus { border-color: rgba(59,130,246,0.3); }
        .acc-run {
          padding: 5px 16px; border-radius: 7px;
          background: rgba(59,130,246,0.18);
          border: 1px solid rgba(59,130,246,0.3);
          color: rgba(255,255,255,0.85); font-size: 12px;
          font-family: 'Syne', sans-serif; font-weight: 500;
          cursor: pointer; transition: all .15s; white-space: nowrap;
        }
        .acc-run:hover:not(:disabled) { background: rgba(59,130,246,0.28); }
        .acc-run:disabled { opacity: 0.35; cursor: default; }
        .acc-hint {
          font-size: 10px; color: rgba(255,255,255,0.18);
          font-family: 'JetBrains Mono', monospace;
          margin-top: 5px; letter-spacing: 0.04em;
        }
      `}</style>

      <div className="acc-panel">
        <div className="acc-tabs">
          <button
            className={`acc-tab ${mode === "variance" ? "active" : ""}`}
            onClick={() => { setMode("variance"); reset() }}
          >
            📊 Variance
          </button>
          <button
            className={`acc-tab ${mode === "bank-recon" ? "active" : ""}`}
            onClick={() => { setMode("bank-recon"); reset() }}
          >
            🏦 Bank Recon
          </button>
        </div>

        <div className="acc-row">
          {/* File 1 */}
          <input
            ref={ref1} type="file" accept=".xlsx,.xls"
            style={{ display: "none" }}
            onChange={e => setFile1(e.target.files?.[0] ?? null)}
          />
          <button
            className={`acc-upload ${file1 ? "has-file" : ""}`}
            onClick={() => ref1.current?.click()}
          >
            {file1 ? `✓ ${file1.name.length > 20 ? file1.name.slice(0, 18) + "…" : file1.name}` : (
              mode === "variance" ? "↑ Budget vs Actual" : "↑ Sao kê ngân hàng"
            )}
          </button>

          {/* File 2 — chỉ hiện khi bank-recon */}
          {mode === "bank-recon" && (
            <>
              <input
                ref={ref2} type="file" accept=".xlsx,.xls"
                style={{ display: "none" }}
                onChange={e => setFile2(e.target.files?.[0] ?? null)}
              />
              <button
                className={`acc-upload ${file2 ? "has-file" : ""}`}
                onClick={() => ref2.current?.click()}
              >
                {file2 ? `✓ ${file2.name.length > 20 ? file2.name.slice(0, 18) + "…" : file2.name}` : "↑ Sổ sách nội bộ"}
              </button>
            </>
          )}

          {/* Period — chỉ cho variance */}
          {mode === "variance" && (
            <input
              className="acc-period"
              placeholder="VD: Tháng 6/2026"
              value={period}
              onChange={e => setPeriod(e.target.value)}
            />
          )}

          {/* Run button */}
          <button
            className="acc-run"
            onClick={run}
            disabled={
              disabled ||
              !file1 ||
              (mode === "bank-recon" && !file2)
            }
          >
            Phân tích ▶
          </button>
        </div>

        <div className="acc-hint">
          {mode === "variance"
            ? "xlsx có cột: Khoản mục · Ngân sách · Thực tế · Loại (revenue/expense)"
            : "2 file xlsx: sao kê ngân hàng + sổ sách nội bộ"}
        </div>
      </div>
    </>
  )
}