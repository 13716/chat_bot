"use client"

/**
 * Recharts visualization cho Agent (UC#2 Variance + UC#7 Aging).
 * File client riêng → import vào AgentChatWindow qua next/dynamic { ssr: false }
 * vì recharts dùng browser API (ResponsiveContainer đo kích thước DOM).
 */

import {
  Bar, BarChart, Cell, CartesianGrid, Legend,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts"
import type { AgingSummary, VarianceChartItem, FSRatio } from "@/lib/api"
import { recommendCharts, CHART_LABEL, type ChartKind } from "@/lib/chartRules"

// ── Định dạng số tiền VND gọn ───────────────────────────────────────────────
const fmtAmt = (v: number): string => {
  const a = Math.abs(v)
  const s = a >= 1e9 ? `${(v / 1e9).toFixed(2)} tỷ`
          : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
          : a >= 1e3 ? `${(v / 1e3).toFixed(0)}K`
          : `${v.toFixed(0)}`
  return s
}

const AXIS = { fill: "#64748b", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }
const GRID = "#e2e8f0"

// ── Tooltip dùng chung (light theme) ────────────────────────────────────────
interface TipRow { name: string; value: number; color?: string; suffix?: string; fmt?: (v: number) => string }
function ChartTip({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div style={{
      background: "#ffffff", border: "1px solid #c7d8f0", borderRadius: 8,
      padding: "8px 12px", fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
      boxShadow: "0 2px 8px rgba(37,99,235,.12)",
    }}>
      <div style={{ color: "#1e3a5f", marginBottom: 4, fontWeight: 700 }}>{title}</div>
      {rows.map((r, i) => (
        <div key={i} style={{ color: r.color ?? "#475569", display: "flex", gap: 14, justifyContent: "space-between" }}>
          <span>{r.name}</span>
          <span style={{ fontWeight: 600 }}>{(r.fmt ?? fmtAmt)(r.value)}{r.suffix ?? ""}</span>
        </div>
      ))}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// 1. AGING BUCKETS — bar chart màu theo mức độ rủi ro (UC#7)
// ════════════════════════════════════════════════════════════════════════════

const BUCKET_ORDER = ["current", "1_30", "31_60", "61_90", "over_90"]
const BUCKET_COLOR: Record<string, string> = {
  current: "#16a34a",  // xanh — chưa đến hạn
  "1_30": "#2563eb",   // xanh dương — mới quá hạn
  "31_60": "#d97706",  // vàng
  "61_90": "#ea580c",  // cam
  over_90: "#dc2626",  // đỏ — rủi ro mất vốn
}

export function AgingChart({ summary }: { summary: AgingSummary }) {
  const data = BUCKET_ORDER
    .filter(k => summary.buckets[k])
    .map(k => ({
      key: k,
      name: summary.buckets[k].label,
      amount: summary.buckets[k].amount,
      pct: summary.buckets[k].pct,
      count: summary.buckets[k].count,
    }))

  return (
    <div className="ag-chart-card">
      <div className="ag-chart-title">📊 Phân bổ tuổi nợ theo nhóm</div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} />
          <YAxis tickFormatter={fmtAmt} tick={AXIS} axisLine={false} tickLine={false} width={56} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={payload[0].payload.name}
                  rows={[
                    { name: "Dư nợ", value: payload[0].payload.amount, color: BUCKET_COLOR[payload[0].payload.key] },
                    { name: "Tỷ lệ", value: payload[0].payload.pct, suffix: "%", color: "#9db4d4" },
                    { name: "Số HĐ", value: payload[0].payload.count, color: "#9db4d4" },
                  ]}
                />
              ) : null
            }
          />
          <Bar dataKey="amount" radius={[4, 4, 0, 0]} maxBarSize={64}>
            {data.map(d => <Cell key={d.key} fill={BUCKET_COLOR[d.key]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── 1b. AGING PIE — cơ cấu tỷ trọng tuổi nợ (UC#7) ──────────────────────────

export function AgingPieChart({ summary }: { summary: AgingSummary }) {
  const data = BUCKET_ORDER
    .filter(k => summary.buckets[k] && summary.buckets[k].amount > 0)
    .map(k => ({
      key: k,
      name: summary.buckets[k].label,
      amount: summary.buckets[k].amount,
      pct: summary.buckets[k].pct,
    }))
  if (data.length === 0) return null

  return (
    <div className="ag-chart-card">
      <div className="ag-chart-title">🥧 Cơ cấu tỷ trọng tuổi nợ</div>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie data={data} dataKey="amount" nameKey="name" cx="50%" cy="50%"
               innerRadius={45} outerRadius={85} paddingAngle={2}
               isAnimationActive={false}
               label={(p: { percent?: number }) => p.percent != null ? `${Math.round(p.percent * 100)}%` : ""}
               labelLine={false}
               style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
            {data.map(d => <Cell key={d.key} fill={BUCKET_COLOR[d.key]} stroke="#fff" strokeWidth={1.5} />)}
          </Pie>
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={payload[0].payload.name}
                  rows={[
                    { name: "Dư nợ", value: payload[0].payload.amount, color: BUCKET_COLOR[payload[0].payload.key] },
                    { name: "Tỷ lệ", value: payload[0].payload.pct, suffix: "%", color: "#9db4d4" },
                  ]}
                />
              ) : null
            }
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="ag-chart-legend">
        {data.map(d => (
          <span key={d.key}><i style={{ background: BUCKET_COLOR[d.key] }} /> {d.name}</span>
        ))}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// 2. ACTUAL vs BUDGET — grouped horizontal bar (UC#2)
// ════════════════════════════════════════════════════════════════════════════

export function ActualVsBudgetChart({ items }: { items: VarianceChartItem[] }) {
  const data = items
    .filter(it => it.budget !== null && it.actual !== null)
    .map(it => ({
      name: it.item.length > 22 ? it.item.slice(0, 21) + "…" : it.item,
      fullName: it.item,
      budget: it.budget as number,
      actual: it.actual as number,
    }))

  if (data.length === 0) return null
  const height = Math.max(180, data.length * 42 + 50)

  return (
    <div className="ag-chart-card">
      <div className="ag-chart-title">📈 Thực tế vs Kế hoạch (khoản vượt ngưỡng)</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 4 }} barGap={2}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
          <XAxis type="number" tickFormatter={fmtAmt} tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} width={130} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={payload[0].payload.fullName}
                  rows={[
                    { name: "Kế hoạch", value: payload[0].payload.budget, color: "#2563eb" },
                    { name: "Thực tế", value: payload[0].payload.actual, color: "#d97706" },
                  ]}
                />
              ) : null
            }
          />
          <Legend wrapperStyle={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#7096be" }} />
          <Bar dataKey="budget" name="Kế hoạch" fill="#2563eb" radius={[0, 3, 3, 0]} maxBarSize={14} />
          <Bar dataKey="actual" name="Thực tế" fill="#d97706" radius={[0, 3, 3, 0]} maxBarSize={14} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// 3. WATERFALL VARIANCE — chênh lệch tích lũy (UC#2)
// ════════════════════════════════════════════════════════════════════════════

const FAVORABLE = "#16a34a"
const UNFAVORABLE = "#dc2626"
const TOTAL_COLOR = "#2563eb"

export function VarianceWaterfall({ items }: { items: VarianceChartItem[] }) {
  const valid = items.filter(it => it.variance_abs !== null)
  if (valid.length === 0) return null

  let cum = 0
  const data = valid.map(it => {
    const v = it.variance_abs as number
    const start = cum
    cum += v
    return {
      name: it.item.length > 18 ? it.item.slice(0, 17) + "…" : it.item,
      fullName: it.item,
      base: Math.min(start, cum),        // phần đệm trong suốt
      delta: Math.abs(v),                // phần hiển thị
      value: v,
      direction: it.direction,
      isTotal: false,
    }
  })
  // Cột tổng
  data.push({
    name: "TỔNG", fullName: "Tổng chênh lệch",
    base: 0, delta: Math.abs(cum), value: cum, direction: "", isTotal: true,
  })

  const barColor = (d: typeof data[number]): string =>
    d.isTotal ? TOTAL_COLOR : (d.direction === "Favorable" ? FAVORABLE : UNFAVORABLE)

  return (
    <div className="ag-chart-card">
      <div className="ag-chart-title">💧 Waterfall — chênh lệch tích lũy (Actual − Budget)</div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 36 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false}
                 angle={-30} textAnchor="end" interval={0} height={60} />
          <YAxis tickFormatter={fmtAmt} tick={AXIS} axisLine={false} tickLine={false} width={56} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={payload[0].payload.fullName}
                  rows={[{
                    name: payload[0].payload.isTotal ? "Tổng chênh lệch"
                          : (payload[0].payload.direction === "Favorable" ? "Thuận lợi" : "Bất lợi"),
                    value: payload[0].payload.value,
                    color: barColor(payload[0].payload),
                  }]}
                />
              ) : null
            }
          />
          <Bar dataKey="base" stackId="wf" fill="transparent" />
          <Bar dataKey="delta" stackId="wf" radius={[3, 3, 0, 0]} maxBarSize={48}>
            {data.map((d, i) => <Cell key={i} fill={barColor(d)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="ag-chart-legend">
        <span><i style={{ background: FAVORABLE }} /> Thuận lợi</span>
        <span><i style={{ background: UNFAVORABLE }} /> Bất lợi</span>
        <span><i style={{ background: TOTAL_COLOR }} /> Tổng</span>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// 4. FINANCIAL RATIOS — Thực tế vs Ngưỡng tốt (UC#1), tách 2 panel theo đơn vị
// ════════════════════════════════════════════════════════════════════════════

const STATUS_COLOR: Record<string, string> = {
  good: "#16a34a", warning: "#d97706", critical: "#dc2626", info: "#64748b",
}
const BENCH_COLOR = "#cbd5e1"
const fmtRatio = (v: number) => v.toFixed(1)

// "ROE (Tỷ suất sinh lời VCSH)" → "ROE"; nếu dài thì cắt
function shortLabel(label: string): string {
  const m = label.match(/^([^(]+?)\s*\(/)
  const s = (m ? m[1] : label).trim()
  return s.length > 22 ? s.slice(0, 21) + "…" : s
}

function RatioPanel({ title, ratios, pct }: { title: string; ratios: FSRatio[]; pct: boolean }) {
  const data = ratios.map(r => ({
    name: shortLabel(r.label),
    fullName: r.label,
    value: r.value,
    benchmark: r.benchmark_good ?? null,
    status: r.status,
    suffix: pct ? "%" : " lần",
  }))
  if (data.length === 0) return null
  const height = Math.max(150, data.length * 42 + 60)

  return (
    <div className="ag-chart-card">
      <div className="ag-chart-title">{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 20, left: 8, bottom: 4 }} barGap={1}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false}
                 tickFormatter={(v) => `${v}${pct ? "%" : ""}`} />
          <YAxis type="category" dataKey="name" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} width={120} />
          <Tooltip
            cursor={{ fill: "rgba(0,0,0,0.03)" }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={payload[0].payload.fullName}
                  rows={[
                    { name: "Thực tế", value: payload[0].payload.value, suffix: payload[0].payload.suffix,
                      fmt: fmtRatio, color: STATUS_COLOR[payload[0].payload.status] },
                    ...(payload[0].payload.benchmark != null ? [{
                      name: "Ngưỡng tốt", value: payload[0].payload.benchmark,
                      suffix: payload[0].payload.suffix, fmt: fmtRatio, color: "#64748b",
                    }] : []),
                  ]}
                />
              ) : null
            }
          />
          <Bar dataKey="benchmark" name="Ngưỡng tốt" fill={BENCH_COLOR} radius={[0, 3, 3, 0]} maxBarSize={11} />
          <Bar dataKey="value" name="Thực tế" radius={[0, 3, 3, 0]} maxBarSize={11}>
            {data.map((d, i) => <Cell key={i} fill={STATUS_COLOR[d.status]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {/* Legend tùy chỉnh: bar "Thực tế" tô theo trạng thái nên không dùng Legend mặc định (1 màu) */}
      <div className="ag-chart-legend">
        <span><i style={{ background: STATUS_COLOR.good }} /> Đạt</span>
        <span><i style={{ background: STATUS_COLOR.warning }} /> Cảnh báo</span>
        <span><i style={{ background: STATUS_COLOR.critical }} /> Nguy hiểm</span>
        <span><i style={{ background: BENCH_COLOR }} /> Ngưỡng tốt</span>
      </div>
    </div>
  )
}

export function FSRatioChart({ ratios }: { ratios: FSRatio[] }) {
  const pctRatios = ratios.filter(r => r.unit === "%" && r.value != null)
  const timesRatios = ratios.filter(r => r.unit === "lần" && r.value != null)
  if (pctRatios.length === 0 && timesRatios.length === 0) return null
  return (
    <>
      <RatioPanel title="📊 Tỷ suất sinh lời & cơ cấu (%) — Thực tế vs Ngưỡng tốt" ratios={pctRatios} pct />
      <RatioPanel title="📊 Thanh toán & đòn bẩy (lần) — Thực tế vs Ngưỡng tốt" ratios={timesRatios} pct={false} />
    </>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// CHART GROUPS — rule-based: gọi recommendCharts() rồi render đúng chart đề xuất
// ════════════════════════════════════════════════════════════════════════════

function RecommendBadge({ kinds }: { kinds: ChartKind[] }) {
  return (
    <div className="ag-chart-reco">
      🤖 Biểu đồ đề xuất theo dữ liệu: {kinds.map(k => CHART_LABEL[k]).join(" + ")}
    </div>
  )
}

/** UC#7 — cơ cấu tuổi nợ: composition, parts-of-whole → pie + bar */
export function AgingChartGroup({ summary }: { summary: AgingSummary }) {
  const kinds = recommendCharts({
    intent: "composition",
    categories: Object.values(summary.buckets).filter(b => b.amount > 0).length,
    partsOfWhole: true,
    hasTime: false,
    paired: false,
  })
  return (
    <>
      <RecommendBadge kinds={kinds} />
      {kinds.includes("pie") && <AgingPieChart summary={summary} />}
      {kinds.includes("bar") && <AgingChart summary={summary} />}
    </>
  )
}

/** UC#2 — phân rã chênh lệch: variance, paired → grouped bar + waterfall */
export function VarianceChartGroup({ items }: { items: VarianceChartItem[] }) {
  const kinds = recommendCharts({
    intent: "variance",
    categories: items.length,
    partsOfWhole: false,
    hasTime: false,
    paired: true,
  })
  return (
    <>
      <RecommendBadge kinds={kinds} />
      {kinds.includes("groupedBar") && <ActualVsBudgetChart items={items} />}
      {kinds.includes("waterfall") && <VarianceWaterfall items={items} />}
    </>
  )
}

/** UC#1 — tỷ số vs ngưỡng: comparison, paired → grouped bar (FSRatioChart) */
export function FSChartGroup({ ratios }: { ratios: FSRatio[] }) {
  const kinds = recommendCharts({
    intent: "comparison",
    categories: ratios.length,
    partsOfWhole: false,
    hasTime: false,
    paired: true,
  })
  return (
    <>
      <RecommendBadge kinds={kinds} />
      <FSRatioChart ratios={ratios} />
    </>
  )
}
