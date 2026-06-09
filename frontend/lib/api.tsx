const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

export interface Message {
  role: "user" | "assistant"
  content: string
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
}

// ── Conversations ─────────────────────────────────────────
export async function fetchConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BACKEND_URL}/conversations`)
  if (!res.ok) return []
  return res.json()
}

export async function createConversation(title: string): Promise<Conversation | null> {
  const res = await fetch(`${BACKEND_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) return null
  return res.json()
}

export async function updateConversationTitle(id: string, title: string): Promise<void> {
  await fetch(`${BACKEND_URL}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
}

export async function deleteConversationAPI(id: string): Promise<void> {
  await fetch(`${BACKEND_URL}/conversations/${id}`, { method: "DELETE" })
}

// ── Chat stream ───────────────────────────────────────────
export async function streamChat(
  messages: Message[],
  system: string,
  conversationId: string | null,
  onToken: (token: string) => void,
  onDone: () => void
) {
  const res = await fetch(`${BACKEND_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, system, conversation_id: conversationId }),
  })

  if (!res.ok || !res.body) {
    onToken("[ERROR] Cannot connect to backend.")
    onDone()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data: ")) continue
      const data = line.slice("data: ".length)
      if (data === "[DONE]") { onDone(); return }
      if (data) onToken(data)
    }
  }
  onDone()
}
// ── THÊM VÀO frontend/lib/api.tsx ────────────────────────────
// Paste đoạn này vào cuối file api.tsx hiện tại

export type AccountingUseCase = "variance" | "bank-recon"

export interface VarianceMeta {
  type: "metadata"
  total_rows: number
  flagged_count: number
  threshold: number
  period: string | null
  flagged_items: Array<{
    item: string
    variance_pct: number | null
    direction: string
    line_type: string
  }>
}

export interface ReconResult {
  type: "recon_result"
  summary: {
    total_bank: number
    total_book: number
    matched: number
    partial: number
    unmatched_bank: number
    unmatched_book: number
    match_rate: number
  }
  matched_count: number
  unmatched_bank: Array<{ vendor: string; amount: number; date: string }>
  unmatched_book: Array<{ vendor: string; amount: number; date: string }>
  partial: Array<{
    bank: { vendor: string; amount: number }
    book: { vendor: string; amount: number }
    confidence: number
  }>
}

export async function streamVariance(
  file: File,
  period: string,
  onMeta: (meta: VarianceMeta) => void,
  onToken: (token: string) => void,
  onDone: () => void
) {
  const form = new FormData()
  form.append("file", file)
  form.append("period", period)
  form.append("threshold", "0.15")

  const res = await fetch(`${BACKEND_URL}/accounting/variance`, {
    method: "POST",
    body: form,
  })

  if (!res.ok || !res.body) {
    onToken(`[Lỗi] Không kết nối được backend: ${res.status}`)
    onDone()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data: ")) continue
      const data = line.slice("data: ".length)
      if (data === "[DONE]") { onDone(); return }
      if (data.startsWith("__META__")) {
        try { onMeta(JSON.parse(data.slice("__META__".length))) } catch {}
      } else if (data) {
        onToken(data)
      }
    }
  }
  onDone()
}

// ── Agent tool-calling ────────────────────────────────────
export interface ToolRequest {
  id: string
  name: "analyze_variance" | "bank_reconciliation" | "analyze_financial_statement" | "ar_ap_aging"
  arguments: Record<string, unknown>
}

// ── Aging types ────────────────────────────────────────────
export interface AgingBucketData {
  label: string
  count: number
  amount: number
  pct: number
}

export interface AgingVendor {
  vendor: string
  total: number
  buckets: Record<string, number>
  max_days: number
  invoice_count: number
  risk: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
}

export interface AgingSummary {
  total_outstanding: number
  invoice_count: number
  as_of: string
  buckets: Record<string, AgingBucketData>
  vendors: AgingVendor[]
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  risk_reasons: string[]
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
  tool_capable: boolean
}

export interface FileAnalysis {
  type: string
  filename: string
  summary: string
  tool_suggestions: string[]
  meta: Record<string, unknown>
}

export async function getAgentModels(): Promise<ModelInfo[]> {
  try {
    const res = await fetch(`${BACKEND_URL}/agent/models`)
    if (!res.ok) return []
    const data = await res.json()
    return data.models ?? []
  } catch { return [] }
}

export async function analyzeFile(file: File): Promise<FileAnalysis | null> {
  const form = new FormData()
  form.append("file", file)
  try {
    const res = await fetch(`${BACKEND_URL}/agent/analyze-file`, { method: "POST", body: form })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

export interface FSRatio {
  key: string
  label: string
  value: number
  unit: string
  status: "good" | "warning" | "critical" | "info"
  benchmark_good?: number | null
  benchmark_ok?: number | null
  dir?: "high_good" | "low_good" | null
}

export interface VarianceChartItem {
  item: string
  budget: number | null
  actual: number | null
  variance_abs: number | null
  variance_pct: number | null
  line_type: string
  direction: string
}

export interface AgentMeta {
  // variance meta
  total_rows?: number
  flagged_count?: number
  threshold?: number
  period?: string | null
  flagged_items?: VarianceChartItem[]
  // bank recon meta
  summary?: ReconResult["summary"]
  matched_count?: number
  unmatched_bank?: ReconResult["unmatched_bank"]
  unmatched_book?: ReconResult["unmatched_book"]
  // financial statement meta
  ratios?: FSRatio[]
  critical_count?: number
  warning_count?: number
  // aging meta (UC#7)
  aging_summary?: AgingSummary
  ar_type?: string
  invoice_count?: number
}

export interface Citation {
  source: string
  article: string
  article_title: string
  topic: string
  score: number
  label: string
}

export async function streamAgentChat(params: {
  message: string
  history: Message[]
  modelId?: string
  outputFormat?: "markdown" | "json" | "html"
  attachedFiles?: File[]
  onToolRequest: (req: ToolRequest) => void
  onMeta: (meta: AgentMeta) => void
  onToken: (token: string) => void
  onCitations?: (citations: Citation[]) => void
  onDone: () => void
  pendingTool?: ToolRequest
  varianceFile?: File
  bankFile?: File
  bookFile?: File
  agingFile?: File
}) {
  const { message, history, modelId, outputFormat, attachedFiles,
          onToolRequest, onMeta, onToken, onCitations, onDone,
          pendingTool, varianceFile, bankFile, bookFile, agingFile } = params

  const form = new FormData()
  form.append("message", message)
  form.append("history", JSON.stringify(history))
  if (modelId) form.append("model_id", modelId)
  if (outputFormat) form.append("output_format", outputFormat)
  if (pendingTool) form.append("pending_tool", JSON.stringify(pendingTool))
  if (varianceFile) form.append("variance_file", varianceFile)
  if (bankFile) form.append("bank_file", bankFile)
  if (bookFile) form.append("book_file", bookFile)
  if (agingFile) form.append("aging_file", agingFile)
  if (attachedFiles) attachedFiles.forEach(f => form.append("attached_files", f))

  const res = await fetch(`${BACKEND_URL}/agent/chat`, { method: "POST", body: form })

  if (!res.ok || !res.body) {
    onToken(`[Lỗi] Không kết nối được backend: ${res.status}`)
    onDone()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data: ")) continue
      const data = line.slice("data: ".length)
      if (data === "[DONE]") { onDone(); return }
      if (data.startsWith("__TOOL_REQUEST__")) {
        try { onToolRequest(JSON.parse(data.slice("__TOOL_REQUEST__".length))) } catch {}
      } else if (data.startsWith("__META__")) {
        try { onMeta(JSON.parse(data.slice("__META__".length))) } catch {}
      } else if (data.startsWith("__CITATIONS__")) {
        try { onCitations?.(JSON.parse(data.slice("__CITATIONS__".length))) } catch {}
      } else if (data) {
        onToken(data)
      }
    }
  }
  onDone()
}

export async function streamBankRecon(
  bankFile: File,
  bookFile: File,
  onRecon: (result: ReconResult) => void,
  onToken: (token: string) => void,
  onDone: () => void
) {
  const form = new FormData()
  form.append("bank_file", bankFile)
  form.append("book_file", bookFile)
  form.append("fuzzy_threshold", "85")
  form.append("with_commentary", "true")

  const res = await fetch(`${BACKEND_URL}/accounting/bank-recon`, {
    method: "POST",
    body: form,
  })

  if (!res.ok || !res.body) {
    onToken(`[Lỗi] Không kết nối được backend: ${res.status}`)
    onDone()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data: ")) continue
      const data = line.slice("data: ".length)
      if (data === "[DONE]") { onDone(); return }
      if (data.startsWith("__RECON__")) {
        try { onRecon(JSON.parse(data.slice("__RECON__".length))) } catch {}
      } else if (data) {
        onToken(data)
      }
    }
  }
  onDone()
}