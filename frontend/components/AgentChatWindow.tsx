"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import {
  streamAgentChat, Message, ToolRequest, AgentMeta,
  ModelInfo, FileAnalysis, getAgentModels, analyzeFile,
} from "@/lib/api"
import ProfileSettings from "@/components/ProfileSettings"

// ── Types ──────────────────────────────────────────────────────────────────

type OutputFormat = "markdown" | "json" | "html"

interface AttachedFile {
  file: File
  analysis: FileAnalysis | null
  analyzing: boolean
  id: string
}

interface ChatMessage {
  role: "user" | "assistant" | "tool_prompt"
  content: string
  meta?: AgentMeta
  toolReq?: ToolRequest
  files?: { name: string; type: string }[]
}

interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
}

const SUGGESTED = [
  "Hướng dẫn hạch toán thuế GTGT đầu vào",
  "Phân tích variance tháng 6/2026",
  "Đối chiếu sao kê ngân hàng",
  "Cách lập BCĐKT theo TT200",
]

const TOOL_LABELS: Record<string, string> = {
  analyze_variance: "Phân tích Variance",
  bank_reconciliation: "Đối chiếu Ngân hàng",
}

const FILE_ICONS: Record<string, string> = {
  excel: "📊", csv: "📊", pdf: "📄", word: "📝",
  image: "🖼️", text: "📃", unknown: "📎",
}

// ── Download helper ────────────────────────────────────────────────────────

function downloadContent(content: string, format: OutputFormat, filename = "export") {
  const map: Record<OutputFormat, { mime: string; ext: string }> = {
    markdown: { mime: "text/markdown", ext: "md" },
    json:     { mime: "application/json", ext: "json" },
    html:     { mime: "text/html", ext: "html" },
  }
  const { mime, ext } = map[format]
  let blob: Blob
  if (format === "html") {
    const full = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${filename}</title>
<style>body{font-family:sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1e293b}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:8px 12px}
th{background:#eff6ff}code{background:#f1f5f9;padding:2px 6px;border-radius:4px}
pre{background:#f1f5f9;padding:16px;border-radius:8px;overflow:auto}</style>
</head><body>${content}</body></html>`
    blob = new Blob([full], { type: mime })
  } else {
    blob = new Blob([content], { type: mime })
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a"); a.href = url
  a.download = `${filename}.${ext}`; a.click()
  URL.revokeObjectURL(url)
}

// ── Rich text renderer ────────────────────────────────────────────────────

function renderMarkdown(raw: string): string {
  return raw
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^\| (.+) \|$/gm, (_, row) => {
      const cells = row.split(" | ").map((c: string) => `<td>${c}</td>`).join("")
      return `<tr>${cells}</tr>`
    })
    .replace(/(<tr>.*<\/tr>)/gm, m => `<table>${m}</table>`)
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    .replace(/^[-•] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gm, m => `<ul>${m}</ul>`)
    .replace(/\n\n+/g, "</p><p>")
    .replace(/\n/g, "<br>")
}

function extractCodeBlocks(content: string): { lang: string; code: string; before: string }[] {
  const blocks: { lang: string; code: string; before: string }[] = []
  const re = /```(\w*)\n([\s\S]*?)```/g
  let m; let last = 0
  while ((m = re.exec(content)) !== null) {
    blocks.push({ lang: m[1] || "text", code: m[2].trim(), before: content.slice(last, m.index) })
    last = m.index + m[0].length
  }
  return blocks
}

// ── Component ──────────────────────────────────────────────────────────────

export default function AgentChatWindow() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [pendingTool, setPendingTool] = useState<ToolRequest | null>(null)
  const [showProfile, setShowProfile] = useState(false)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("markdown")
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([])
  const [isDragging, setIsDragging] = useState(false)

  const varianceFileRef = useRef<HTMLInputElement>(null)
  const bankFileRef = useRef<HTMLInputElement>(null)
  const bookFileRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Load models ──────────────────────────────────────────────────────────
  useEffect(() => {
    getAgentModels().then(ms => {
      setModels(ms)
      if (ms.length > 0) setSelectedModel(ms[0].id)
    })
  }, [])

  // ── Load conversations từ localStorage khi mount ─────────────────────────
  useEffect(() => {
    try {
      const raw = localStorage.getItem("vsf-agent-chats")
      if (!raw) return
      const { conversations: savedConvs, activeConvId: savedId } = JSON.parse(raw)
      if (Array.isArray(savedConvs) && savedConvs.length > 0) {
        setConversations(savedConvs)
        if (savedId) {
          setActiveConvId(savedId)
          const conv = savedConvs.find((c: Conversation) => c.id === savedId)
          if (conv?.messages) setMessages(conv.messages)
        }
      }
    } catch {}
  }, []) // chỉ chạy 1 lần khi mount

  // ── Tự động lưu khi conversations hoặc messages thay đổi ────────────────
  const persistToStorage = useCallback((
    convs: Conversation[], msgs: ChatMessage[], aid: string | null
  ) => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      try {
        // Merge messages hiện tại vào conversation đang active
        const toSave = aid
          ? convs.map(c => c.id === aid ? { ...c, messages: msgs } : c)
          : convs
        localStorage.setItem("vsf-agent-chats", JSON.stringify({
          conversations: toSave,
          activeConvId: aid,
        }))
      } catch {}
    }, 800) // debounce 800ms
  }, [])

  useEffect(() => {
    persistToStorage(conversations, messages, activeConvId)
  }, [conversations, messages, activeConvId, persistToStorage])

  // ── Scroll to bottom ────────────────────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const apiHistory = useCallback((): Message[] =>
    messages
      .filter(m => m.role === "user" || m.role === "assistant")
      .map(m => ({ role: m.role as "user" | "assistant", content: m.content }))
  , [messages])

  // ── File attach ─────────────────────────────────────────────────────────

  const addFiles = async (files: File[]) => {
    const newEntries: AttachedFile[] = files.map(f => ({
      file: f, analysis: null, analyzing: true,
      id: `${f.name}-${Date.now()}-${Math.random()}`,
    }))
    setAttachedFiles(prev => [...prev, ...newEntries])

    for (const entry of newEntries) {
      const result = await analyzeFile(entry.file)
      setAttachedFiles(prev => prev.map(a =>
        a.id === entry.id ? { ...a, analysis: result, analyzing: false } : a
      ))
    }
  }

  const removeFile = (id: string) =>
    setAttachedFiles(prev => prev.filter(a => a.id !== id))

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files))
    e.target.value = ""
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false)
    if (e.dataTransfer.files) addFiles(Array.from(e.dataTransfer.files))
  }

  // ── Conversation management ──────────────────────────────────────────────

  const newConversation = () => {
    if (loading) return
    // Save current messages to conversation
    if (messages.length > 0 && activeConvId) {
      setConversations(prev => prev.map(c =>
        c.id === activeConvId ? { ...c, messages } : c
      ))
    }
    const id = `conv-${Date.now()}`
    setActiveConvId(null); setMessages([]); setAttachedFiles([]); setPendingTool(null); setInput("")
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const switchConversation = (id: string) => {
    if (loading || id === activeConvId) return
    if (messages.length > 0 && activeConvId) {
      setConversations(prev => prev.map(c => c.id === activeConvId ? { ...c, messages } : c))
    }
    const conv = conversations.find(c => c.id === id)
    if (conv) { setMessages(conv.messages); setActiveConvId(id) }
  }

  const deleteConversation = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id)
      // Cập nhật localStorage ngay lập tức
      try {
        const newActive = activeConvId === id ? (next[0]?.id ?? null) : activeConvId
        localStorage.setItem("vsf-agent-chats", JSON.stringify({
          conversations: next, activeConvId: newActive,
        }))
      } catch {}
      return next
    })
    if (activeConvId === id) {
      const next = conversations.filter(c => c.id !== id)
      const fallback = next[0]
      if (fallback) { setMessages(fallback.messages); setActiveConvId(fallback.id) }
      else { setMessages([]); setActiveConvId(null) }
    }
  }

  const clearAllHistory = () => {
    if (!confirm("Xóa toàn bộ lịch sử trò chuyện?")) return
    setConversations([]); setMessages([]); setActiveConvId(null)
    localStorage.removeItem("vsf-agent-chats")
  }

  // ── Append streaming token ───────────────────────────────────────────────

  const appendToken = (token: string) =>
    setMessages(prev => {
      const last = prev[prev.length - 1]
      if (last?.role === "assistant")
        return [...prev.slice(0, -1), { ...last, content: last.content + token }]
      return [...prev, { role: "assistant", content: token }]
    })

  // ── Core: gọi tool với file cụ thể ──────────────────────────────────────

  const runTool = async (req: ToolRequest, vf?: File, bf?: File, bkf?: File) => {
    const orig = messages.find(m => m.role === "user")?.content ?? ""
    const names = [vf, bf, bkf].filter(Boolean).map(f => f!.name).join(", ")
    if (names) setMessages(prev => [...prev, { role: "user", content: `📎 ${names}` }])

    await streamAgentChat({
      message: orig, history: apiHistory(), modelId: selectedModel,
      outputFormat, pendingTool: req,
      varianceFile: vf, bankFile: bf, bookFile: bkf,
      onToolRequest: () => {},
      onMeta: (meta) => setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.role === "assistant") return [...prev.slice(0, -1), { ...last, meta }]
        return [...prev, { role: "assistant", content: "", meta }]
      }),
      onToken: appendToken,
      onDone: () => {
        setPendingTool(null)
        if (varianceFileRef.current) varianceFileRef.current.value = ""
        if (bankFileRef.current) bankFileRef.current.value = ""
        if (bookFileRef.current) bookFileRef.current.value = ""
        setLoading(false); inputRef.current?.focus()
      },
    })
  }

  // ── Send ─────────────────────────────────────────────────────────────────

  const send = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || loading) return
    setInput(""); setLoading(true)

    const filesMeta = attachedFiles.map(a => ({ name: a.file.name, type: a.analysis?.type ?? "unknown" }))
    const files = attachedFiles.map(a => a.file)
    // Snapshot files trước khi clear
    const excelFiles = attachedFiles.filter(
      a => a.analysis?.type === "excel" || a.analysis?.type === "csv"
        || a.file.name.endsWith(".xlsx") || a.file.name.endsWith(".xls")
    ).map(a => a.file)

    const userMsg: ChatMessage = { role: "user", content, files: filesMeta.length ? filesMeta : undefined }
    setMessages(prev => [...prev, userMsg])
    setAttachedFiles([])

    const hist = apiHistory()

    // Create conversation if not exists
    let convId = activeConvId
    if (!convId) {
      convId = `conv-${Date.now()}`
      const title = content.length > 40 ? content.slice(0, 40) + "…" : content
      const newConv: Conversation = { id: convId, title, messages: [], createdAt: Date.now() }
      setConversations(prev => [newConv, ...prev])
      setActiveConvId(convId)
    }

    await streamAgentChat({
      message: content,
      history: hist,
      modelId: selectedModel,
      outputFormat,
      attachedFiles: files.length ? files : undefined,

      onToolRequest: async (req) => {
        setPendingTool(req)

        // ── Nếu đã có file đính kèm → tự execute luôn, không hỏi ──
        if (req.name === "analyze_variance" && excelFiles.length >= 1) {
          setMessages(prev => [...prev, {
            role: "tool_prompt", content: TOOL_LABELS[req.name], toolReq: req,
          }])
          await runTool(req, excelFiles[0])
          return
        }
        if (req.name === "bank_reconciliation" && excelFiles.length >= 2) {
          setMessages(prev => [...prev, {
            role: "tool_prompt", content: TOOL_LABELS[req.name], toolReq: req,
          }])
          await runTool(req, undefined, excelFiles[0], excelFiles[1])
          return
        }

        // ── Chưa có file → hiện tool card để user upload ──
        setMessages(prev => [...prev, {
          role: "tool_prompt",
          content: TOOL_LABELS[req.name] ?? req.name,
          toolReq: req,
        }])
        setLoading(false)
      },

      onMeta: (meta) => setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.role === "assistant") return [...prev.slice(0, -1), { ...last, meta }]
        return [...prev, { role: "assistant", content: "", meta }]
      }),
      onToken: appendToken,
      onDone: () => { setLoading(false); inputRef.current?.focus() },
    })
  }

  // ── Execute tool từ tool card (user upload thủ công) ─────────────────────

  const executeTool = async () => {
    if (!pendingTool) return
    setLoading(true)
    const vf = varianceFileRef.current?.files?.[0]
    const bf = bankFileRef.current?.files?.[0]
    const bkf = bookFileRef.current?.files?.[0]

    if (pendingTool.name === "analyze_variance" && !vf) {
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Vui lòng chọn file Excel." }])
      setLoading(false); return
    }
    if (pendingTool.name === "bank_reconciliation" && (!bf || !bkf)) {
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Cần cả 2 file." }])
      setLoading(false); return
    }
    await runTool(pendingTool, vf, bf, bkf)
  }

  const currentModel = models.find(m => m.id === selectedModel)

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
        html,body{height:100%;overflow:hidden;background:#f0f4f8}

        .ag-root{display:flex;height:100vh;width:100%;font-family:'Inter',sans-serif;overflow:hidden}

        /* SIDEBAR */
        .ag-sb{width:240px;min-width:240px;flex-shrink:0;display:flex;flex-direction:column;
          background:linear-gradient(160deg,#ffffff 0%,#e8f0fe 100%);
          border-right:1px solid #c7d8f0;padding:16px 12px 14px;overflow:hidden}
        .ag-logo{display:flex;align-items:center;gap:9px;padding-bottom:14px;border-bottom:1px solid #d1e0f5;margin-bottom:12px}
        .ag-logo-icon{width:30px;height:30px;border-radius:8px;
          background:linear-gradient(135deg,#2563eb,#60a5fa);
          display:flex;align-items:center;justify-content:center;
          box-shadow:0 2px 7px rgba(37,99,235,.3);flex-shrink:0}
        .ag-logo-name{font-size:13px;font-weight:700;color:#1e3a5f}
        .ag-logo-sub{font-size:10px;color:#7096be;font-family:'JetBrains Mono',monospace}
        .ag-new-btn{display:flex;align-items:center;gap:7px;width:100%;padding:8px 11px;
          border-radius:8px;border:1.5px solid #bbd0f0;
          background:linear-gradient(135deg,#eff6ff,#dbeafe);
          color:#2563eb;font-size:12px;font-weight:600;cursor:pointer;
          font-family:'Inter',sans-serif;margin-bottom:14px;transition:all .18s}
        .ag-new-btn:hover:not(:disabled){background:linear-gradient(135deg,#dbeafe,#bfdbfe);
          box-shadow:0 2px 7px rgba(37,99,235,.18)}
        .ag-new-btn:disabled{opacity:.4;cursor:default}
        .ag-sec{font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
          color:#94a3c4;padding:0 4px 7px;margin-top:4px}
        .ag-conv-list{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:2px;
          min-height:0}
        .ag-conv-list::-webkit-scrollbar{width:3px}
        .ag-conv-list::-webkit-scrollbar-thumb{background:#c7d8f0;border-radius:3px}
        .ag-conv-item{display:flex;align-items:center;gap:7px;padding:7px 9px;border-radius:7px;
          cursor:pointer;border:1px solid transparent;transition:all .15s;
          color:#4b6a8f;font-size:12px}
        .ag-conv-item:hover{background:#eff6ff;border-color:#bbd0f0}
        .ag-conv-item.active{background:linear-gradient(135deg,#eff6ff,#dbeafe);
          border-color:#93c5fd;color:#1d4ed8;font-weight:500}
        .ag-conv-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .ag-conv-del{width:16px;height:16px;border-radius:4px;border:none;background:transparent;
          cursor:pointer;color:#94a3c4;font-size:10px;display:flex;align-items:center;
          justify-content:center;opacity:0;transition:all .15s;flex-shrink:0}
        .ag-conv-item:hover .ag-conv-del{opacity:1}
        .ag-conv-del:hover{background:#fee2e2;color:#dc2626}
        .ag-conv-empty{padding:16px 4px;font-size:11px;color:#b0c4d8;
          font-family:'JetBrains Mono',monospace;line-height:1.7;text-align:center}
        .ag-profile-btn{display:flex;align-items:center;gap:7px;width:100%;margin-top:auto;
          padding:8px 11px;border-radius:7px;border:1px solid #d1e0f5;
          background:transparent;color:#7096be;font-size:12px;cursor:pointer;
          font-family:'Inter',sans-serif;transition:all .18s;text-align:left}
        .ag-profile-btn:hover{background:#eff6ff;color:#2563eb;border-color:#bbd0f0}

        /* MAIN */
        .ag-main{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}

        /* TOPBAR */
        .ag-top{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;
          padding:0 20px;height:54px;
          background:linear-gradient(90deg,#ffffff,#f5f9ff);
          border-bottom:1px solid #cdd9ee;
          box-shadow:0 1px 4px rgba(37,99,235,.06)}
        .ag-top-left{display:flex;align-items:center;gap:9px}
        .ag-sdot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:all .3s}
        .ag-sdot.online{background:#22c55e;box-shadow:0 0 6px #22c55e}
        .ag-sdot.busy{background:#f59e0b;box-shadow:0 0 6px #f59e0b;
          animation:ag-pulse 1s ease-in-out infinite}
        @keyframes ag-pulse{0%,100%{opacity:1}50%{opacity:.3}}
        .ag-top-title{font-size:14px;font-weight:700;color:#1e3a5f}
        .ag-top-sub{font-size:11px;color:#94a3c4;font-family:'JetBrains Mono',monospace}
        .ag-top-right{display:flex;align-items:center;gap:8px}

        /* Model selector */
        .ag-model-sel{font-size:12px;font-family:'JetBrains Mono',monospace;
          color:#2563eb;background:#eff6ff;border:1px solid #bfdbfe;
          padding:5px 10px;border-radius:8px;cursor:pointer;outline:none;
          transition:all .18s;font-weight:500}
        .ag-model-sel:hover{border-color:#93c5fd;background:#dbeafe}

        /* Format selector */
        .ag-fmt-group{display:flex;border:1px solid #c7d8f0;border-radius:8px;overflow:hidden}
        .ag-fmt-btn{padding:5px 9px;font-size:11px;font-weight:600;border:none;cursor:pointer;
          font-family:'JetBrains Mono',monospace;transition:all .15s;
          background:transparent;color:#7096be}
        .ag-fmt-btn.active{background:linear-gradient(135deg,#2563eb,#3b82f6);color:white}
        .ag-fmt-btn:hover:not(.active){background:#eff6ff;color:#2563eb}

        /* MESSAGES */
        .ag-msgs{flex:1;overflow-y:auto;overflow-x:hidden;padding:20px 24px 12px;
          display:flex;flex-direction:column;gap:16px;min-height:0}
        .ag-msgs::-webkit-scrollbar{width:4px}
        .ag-msgs::-webkit-scrollbar-thumb{background:#c7d8f0;border-radius:4px}

        /* EMPTY */
        .ag-empty{flex:1;display:flex;flex-direction:column;align-items:center;
          justify-content:center;gap:12px;animation:ag-in .3s ease-out}
        @keyframes ag-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        .ag-empty-icon{width:56px;height:56px;border-radius:16px;
          background:linear-gradient(135deg,#eff6ff,#dbeafe);
          border:1.5px solid #bfdbfe;display:flex;align-items:center;
          justify-content:center;font-size:24px;
          box-shadow:0 4px 14px rgba(37,99,235,.12);
          animation:ag-float 4s ease-in-out infinite}
        @keyframes ag-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
        .ag-empty-title{font-size:17px;font-weight:700;color:#1e3a5f}
        .ag-empty-sub{font-size:12px;color:#94a3c4;font-family:'JetBrains Mono',monospace}
        .ag-chips{display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:500px;width:100%;margin-top:4px}
        .ag-chip{padding:10px 13px;border-radius:10px;text-align:left;font-size:12px;
          font-family:'Inter',sans-serif;color:#3a5f8a;
          background:linear-gradient(135deg,#ffffff,#f0f7ff);
          border:1px solid #c7d8f0;cursor:pointer;transition:all .18s;line-height:1.45}
        .ag-chip:hover{background:linear-gradient(135deg,#eff6ff,#dbeafe);
          border-color:#93c5fd;color:#1d4ed8;
          box-shadow:0 2px 7px rgba(37,99,235,.12);transform:translateY(-1px)}

        /* ROWS */
        .ag-row{display:flex;gap:9px;align-items:flex-start;animation:ag-in .2s ease-out}
        .ag-row.user{flex-direction:row-reverse}
        .ag-av{width:28px;height:28px;border-radius:8px;flex-shrink:0;font-size:10px;
          font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:2px}
        .ag-av-ai{background:linear-gradient(135deg,#2563eb,#60a5fa);color:white;
          box-shadow:0 2px 5px rgba(37,99,235,.3)}
        .ag-av-u{background:linear-gradient(135deg,#7c3aed,#a78bfa);color:white;
          box-shadow:0 2px 5px rgba(124,58,237,.25)}
        .ag-bbl{max-width:72%;border-radius:13px;font-size:14px;line-height:1.7;word-break:break-word}
        .ag-bbl-ai{background:#ffffff;color:#1e3a5f;border:1px solid #c7d8f0;
          border-top-left-radius:3px;box-shadow:0 1px 5px rgba(37,99,235,.07)}
        .ag-bbl-u{background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;
          border-top-right-radius:3px;box-shadow:0 2px 7px rgba(37,99,235,.25);
          padding:10px 14px;white-space:pre-wrap}

        /* Rich AI bubble content */
        .ag-bbl-ai-inner{padding:11px 14px}
        .ag-bbl-ai-inner h1,.ag-bbl-ai-inner h2,.ag-bbl-ai-inner h3{color:#1d4ed8;margin:10px 0 6px;font-weight:700}
        .ag-bbl-ai-inner h1{font-size:16px}.ag-bbl-ai-inner h2{font-size:15px}.ag-bbl-ai-inner h3{font-size:14px}
        .ag-bbl-ai-inner p{margin-bottom:8px}.ag-bbl-ai-inner p:last-child{margin-bottom:0}
        .ag-bbl-ai-inner strong{color:#1d4ed8;font-weight:600}
        .ag-bbl-ai-inner em{color:#7c3aed}
        .ag-bbl-ai-inner code{background:#eff6ff;color:#1d4ed8;padding:2px 6px;
          border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:12px}
        .ag-bbl-ai-inner table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
        .ag-bbl-ai-inner th{background:linear-gradient(135deg,#eff6ff,#dbeafe);
          border:1px solid #bfdbfe;padding:7px 10px;color:#1d4ed8;font-weight:600;text-align:left}
        .ag-bbl-ai-inner td{border:1px solid #e2e8f0;padding:6px 10px;color:#1e3a5f}
        .ag-bbl-ai-inner tr:nth-child(even) td{background:#f8fbff}
        .ag-bbl-ai-inner ul,.ag-bbl-ai-inner ol{padding-left:18px;margin:6px 0}
        .ag-bbl-ai-inner li{margin-bottom:3px}

        /* Code block */
        .ag-code-block{margin:10px 0;border-radius:10px;overflow:hidden;
          border:1px solid #c7d8f0}
        .ag-code-header{display:flex;align-items:center;justify-content:space-between;
          padding:7px 12px;background:linear-gradient(90deg,#eff6ff,#e8f0fe);
          border-bottom:1px solid #c7d8f0}
        .ag-code-lang{font-family:'JetBrains Mono',monospace;font-size:11px;
          color:#2563eb;font-weight:600;text-transform:uppercase}
        .ag-code-actions{display:flex;gap:5px}
        .ag-code-btn{padding:3px 9px;border-radius:5px;font-size:11px;font-weight:600;
          border:1px solid #bfdbfe;cursor:pointer;font-family:'Inter',sans-serif;
          transition:all .15s}
        .ag-code-btn-dl{background:linear-gradient(135deg,#2563eb,#3b82f6);
          color:white;border-color:transparent;box-shadow:0 1px 4px rgba(37,99,235,.3)}
        .ag-code-btn-dl:hover{background:linear-gradient(135deg,#1d4ed8,#2563eb)}
        .ag-code-btn-cp{background:#eff6ff;color:#2563eb}
        .ag-code-btn-cp:hover{background:#dbeafe}
        .ag-code-body{padding:14px;background:#f8fbff;overflow-x:auto;
          font-family:'JetBrains Mono',monospace;font-size:12px;color:#1e3a5f;
          white-space:pre;line-height:1.6;max-height:400px;overflow-y:auto}

        /* File chips in user message */
        .ag-file-chips{display:flex;flex-wrap:wrap;gap:5px;padding:8px 14px 4px}
        .ag-file-chip{display:flex;align-items:center;gap:5px;padding:4px 9px;
          border-radius:20px;background:#eff6ff;border:1px solid #bfdbfe;
          font-size:11px;color:#2563eb;font-family:'JetBrains Mono',monospace}

        /* Typing dots */
        .ag-dots{display:flex;gap:5px;align-items:center;height:18px;padding:11px 14px}
        .ag-dot{width:5px;height:5px;border-radius:50%;background:#93c5fd;
          animation:ag-bounce 1.2s ease-in-out infinite}
        .ag-dot:nth-child(2){animation-delay:.15s}.ag-dot:nth-child(3){animation-delay:.3s}
        @keyframes ag-bounce{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-5px);opacity:1}}
        .ag-cursor{display:inline-block;width:2px;height:13px;background:#3b82f6;
          margin-left:2px;vertical-align:middle;animation:ag-blink .7s step-end infinite}
        @keyframes ag-blink{0%,100%{opacity:1}50%{opacity:0}}

        /* Meta tags */
        .ag-meta{display:flex;flex-wrap:wrap;gap:5px;padding:0 14px 10px}
        .ag-tag{font-size:11px;padding:3px 8px;border-radius:20px;
          font-family:'JetBrains Mono',monospace;font-weight:500}
        .ag-tag-warn{background:#fffbeb;border:1px solid #fcd34d;color:#b45309}
        .ag-tag-ok{background:#f0fdf4;border:1px solid #86efac;color:#15803d}
        .ag-tag-err{background:#fef2f2;border:1px solid #fca5a5;color:#dc2626}
        .ag-tag-info{background:#eff6ff;border:1px solid #93c5fd;color:#2563eb}

        /* Tool card */
        .ag-tool-card{max-width:72%;
          background:linear-gradient(135deg,#f8fbff,#eff6ff);
          border:1.5px solid #93c5fd;border-top-left-radius:3px;border-radius:13px;
          padding:14px;display:flex;flex-direction:column;gap:11px;
          box-shadow:0 2px 10px rgba(37,99,235,.1);animation:ag-in .2s ease-out}
        .ag-tool-hdr{display:flex;align-items:center;gap:7px}
        .ag-tool-badge{font-size:10px;font-weight:700;letter-spacing:.12em;
          text-transform:uppercase;padding:3px 8px;border-radius:20px;
          background:linear-gradient(135deg,#2563eb,#3b82f6);color:white}
        .ag-tool-title{font-size:13px;font-weight:700;color:#1d4ed8}
        .ag-tool-hint{font-size:12px;color:#4b6a8f;line-height:1.5}
        .ag-file-lbl{font-size:11px;color:#7096be;font-family:'JetBrains Mono',monospace;margin-bottom:4px}
        .ag-tool-finput{width:100%;font-size:12px;color:#3a5f8a}
        .ag-tool-finput::file-selector-button{margin-right:9px;padding:5px 11px;
          border-radius:7px;border:1.5px solid #93c5fd;
          background:linear-gradient(135deg,#eff6ff,#dbeafe);
          color:#2563eb;font-size:12px;font-weight:600;cursor:pointer;
          font-family:'Inter',sans-serif;transition:all .15s}
        .ag-tool-finput::file-selector-button:hover{background:linear-gradient(135deg,#dbeafe,#bfdbfe)}
        .ag-tool-submit{width:100%;padding:9px;border-radius:8px;
          background:linear-gradient(135deg,#2563eb,#3b82f6);border:none;
          color:white;font-size:13px;font-weight:600;cursor:pointer;
          font-family:'Inter',sans-serif;box-shadow:0 2px 7px rgba(37,99,235,.3);
          transition:all .18s}
        .ag-tool-submit:hover:not(:disabled){background:linear-gradient(135deg,#1d4ed8,#2563eb)}
        .ag-tool-submit:disabled{opacity:.4;cursor:default;box-shadow:none}

        /* File analysis card */
        .ag-fa-card{background:linear-gradient(135deg,#f0f9f4,#e6f5ec);
          border:1px solid #86efac;border-radius:10px;padding:11px 13px;
          font-size:12px;color:#1e4a30;margin-top:4px;line-height:1.6}
        .ag-fa-title{font-weight:700;color:#15803d;margin-bottom:5px;font-size:12px}
        .ag-tool-suggest{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
        .ag-tool-suggest-btn{padding:4px 10px;border-radius:20px;font-size:11px;
          font-weight:600;border:1.5px solid #2563eb;background:#eff6ff;
          color:#2563eb;cursor:pointer;font-family:'Inter',sans-serif;transition:all .15s}
        .ag-tool-suggest-btn:hover{background:linear-gradient(135deg,#2563eb,#3b82f6);color:white}

        /* INPUT AREA */
        .ag-input-area{flex-shrink:0;
          background:linear-gradient(180deg,#f5f9ff,#ffffff);
          border-top:1px solid #cdd9ee;
          box-shadow:0 -1px 5px rgba(37,99,235,.05)}

        /* Attached files preview */
        .ag-attach-preview{display:flex;flex-wrap:wrap;gap:6px;padding:10px 18px 0}
        .ag-attach-item{display:flex;align-items:center;gap:6px;padding:5px 10px;
          border-radius:8px;background:linear-gradient(135deg,#ffffff,#f0f7ff);
          border:1px solid #c7d8f0;font-size:12px;color:#3a5f8a;max-width:200px}
        .ag-attach-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
        .ag-attach-rm{background:none;border:none;cursor:pointer;color:#94a3c4;
          font-size:13px;padding:0 2px;line-height:1;flex-shrink:0}
        .ag-attach-rm:hover{color:#dc2626}
        .ag-attach-analysis{font-size:10px;color:#22c55e;font-family:'JetBrains Mono',monospace}
        .ag-attach-loading{font-size:10px;color:#f59e0b;font-family:'JetBrains Mono',monospace}

        /* Drag overlay */
        .ag-drag-overlay{position:absolute;inset:0;background:rgba(37,99,235,.08);
          border:2.5px dashed #3b82f6;border-radius:12px;z-index:10;
          display:flex;align-items:center;justify-content:center;
          font-size:16px;font-weight:600;color:#2563eb;
          pointer-events:none;backdrop-filter:blur(2px)}

        /* Input row */
        .ag-input-row{display:flex;align-items:center;gap:8px;padding:10px 16px 14px}
        .ag-attach-btn{width:34px;height:34px;border-radius:8px;border:1.5px solid #c7d8f0;
          background:#eff6ff;cursor:pointer;display:flex;align-items:center;
          justify-content:center;color:#2563eb;transition:all .15s;flex-shrink:0}
        .ag-attach-btn:hover{background:#dbeafe;border-color:#93c5fd}
        .ag-input-wrap{flex:1;display:flex;align-items:center;gap:8px;
          background:#ffffff;border:1.5px solid #c7d8f0;border-radius:12px;
          padding:5px 5px 5px 14px;
          transition:border-color .2s,box-shadow .2s;
          box-shadow:0 1px 3px rgba(37,99,235,.06)}
        .ag-input-wrap:focus-within{border-color:#3b82f6;
          box-shadow:0 0 0 3px rgba(59,130,246,.1),0 1px 3px rgba(37,99,235,.08)}
        .ag-input{flex:1;background:transparent;border:none;outline:none;font-size:14px;
          font-family:'Inter',sans-serif;color:#1e3a5f;padding:7px 0;caret-color:#3b82f6}
        .ag-input::placeholder{color:#a8c0d8}
        .ag-input:disabled{opacity:.5}
        .ag-send-btn{width:36px;height:36px;flex-shrink:0;border-radius:9px;
          background:linear-gradient(135deg,#2563eb,#3b82f6);border:none;cursor:pointer;
          display:flex;align-items:center;justify-content:center;transition:all .15s;
          box-shadow:0 2px 6px rgba(37,99,235,.35)}
        .ag-send-btn:hover:not(:disabled){background:linear-gradient(135deg,#1d4ed8,#2563eb);
          box-shadow:0 3px 9px rgba(37,99,235,.4)}
        .ag-send-btn:active:not(:disabled){transform:scale(.91)}
        .ag-send-btn:disabled{background:#e2eaf5;box-shadow:none;cursor:default}
        .ag-input-hint{text-align:center;padding-bottom:10px;font-size:11px;color:#b0c4d8;
          font-family:'JetBrains Mono',monospace;letter-spacing:.04em}
      `}</style>

      <div className="ag-root">

        {/* ── SIDEBAR ── */}
        <div className="ag-sb">
          <div className="ag-logo">
            <div className="ag-logo-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
            </div>
            <div>
              <div className="ag-logo-name">VSF Agent</div>
              <div className="ag-logo-sub">AI Kế Toán</div>
            </div>
          </div>

          <button className="ag-new-btn" onClick={newConversation} disabled={loading}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Cuộc trò chuyện mới
          </button>

          <div className="ag-sec" style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <span>Lịch sử</span>
            {conversations.length > 0 && (
              <button onClick={clearAllHistory}
                style={{fontSize:10,color:"#dc2626",background:"none",border:"none",cursor:"pointer",fontFamily:"'Inter',sans-serif"}}>
                Xóa tất cả
              </button>
            )}
          </div>
          <div className="ag-conv-list">
            {conversations.length === 0 ? (
              <div className="ag-conv-empty">Chưa có hội thoại nào.<br/>Bắt đầu nhắn tin!</div>
            ) : conversations.map(c => (
              <div key={c.id}
                className={`ag-conv-item${activeConvId === c.id ? " active" : ""}`}
                onClick={() => switchConversation(c.id)}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{flexShrink:0, opacity:.6}}>
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <span className="ag-conv-title">{c.title}</span>
                <button className="ag-conv-del" onClick={e => deleteConversation(c.id, e)}>✕</button>
              </div>
            ))}
          </div>

          <button className="ag-profile-btn" onClick={() => setShowProfile(true)}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
            Profile
          </button>
        </div>

        {/* ── MAIN ── */}
        <div className="ag-main" style={{position:"relative"}}
          onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}>

          {isDragging && (
            <div className="ag-drag-overlay">
              📂 Thả file vào đây
            </div>
          )}

          {/* Topbar */}
          <div className="ag-top">
            <div className="ag-top-left">
              <div className={`ag-sdot ${loading ? "busy" : "online"}`}/>
              <div>
                <div className="ag-top-title">AI Agent Kế Toán</div>
                <div className="ag-top-sub">{loading ? "đang xử lý…" : "sẵn sàng"}</div>
              </div>
            </div>
            <div className="ag-top-right">
              {/* Format selector */}
              <div className="ag-fmt-group">
                {(["markdown","json","html"] as OutputFormat[]).map(f => (
                  <button key={f} className={`ag-fmt-btn${outputFormat === f ? " active" : ""}`}
                    onClick={() => setOutputFormat(f)}>
                    {f}
                  </button>
                ))}
              </div>
              {/* Model selector */}
              {models.length > 0 && (
                <select className="ag-model-sel" value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}>
                  {models.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.provider})
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {/* Messages */}
          <div className="ag-msgs" ref={messagesRef}>
            {messages.length === 0 && (
              <div className="ag-empty">
                <div className="ag-empty-icon">📊</div>
                <div className="ag-empty-title">VSF Agent Kế Toán</div>
                <div className="ag-empty-sub">chat tự nhiên · kéo thả file · agent tự chọn tool</div>
                <div className="ag-chips">
                  {SUGGESTED.map((s, i) => (
                    <button key={i} className="ag-chip" onClick={() => send(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => {
              // Tool card
              if (msg.role === "tool_prompt" && msg.toolReq) {
                return (
                  <div key={i} className="ag-row">
                    <div className="ag-av ag-av-ai">AI</div>
                    <div className="ag-tool-card">
                      <div className="ag-tool-hdr">
                        <span className="ag-tool-badge">Tool</span>
                        <span className="ag-tool-title">{msg.content}</span>
                      </div>
                      <div className="ag-tool-hint">
                        {msg.toolReq.name === "analyze_variance"
                          ? "Upload file Excel Budget vs Actual (P&L) để phân tích."
                          : "Upload 2 file: sao kê ngân hàng và sổ sách kế toán."}
                      </div>
                      {msg.toolReq.name === "analyze_variance" && (
                        <div>
                          <div className="ag-file-lbl">File Excel (Budget vs Actual)</div>
                          <input ref={varianceFileRef} type="file" accept=".xlsx,.xls" disabled={loading} className="ag-tool-finput"/>
                        </div>
                      )}
                      {msg.toolReq.name === "bank_reconciliation" && (<>
                        <div>
                          <div className="ag-file-lbl">Sao kê ngân hàng</div>
                          <input ref={bankFileRef} type="file" accept=".xlsx,.xls" disabled={loading} className="ag-tool-finput"/>
                        </div>
                        <div>
                          <div className="ag-file-lbl">Sổ sách kế toán</div>
                          <input ref={bookFileRef} type="file" accept=".xlsx,.xls" disabled={loading} className="ag-tool-finput"/>
                        </div>
                      </>)}
                      <button className="ag-tool-submit" onClick={executeTool} disabled={loading}>
                        {loading ? "Đang phân tích…" : "Phân tích ngay →"}
                      </button>
                    </div>
                  </div>
                )
              }

              // User message
              if (msg.role === "user") {
                return (
                  <div key={i} className="ag-row user">
                    <div className="ag-av ag-av-u">U</div>
                    <div className="ag-bbl">
                      {msg.files && msg.files.length > 0 && (
                        <div className="ag-file-chips">
                          {msg.files.map((f, fi) => (
                            <span key={fi} className="ag-file-chip">
                              {FILE_ICONS[f.type] || "📎"} {f.name}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="ag-bbl-u">{msg.content}</div>
                    </div>
                  </div>
                )
              }

              // AI message — rich rendering
              return (
                <div key={i} className="ag-row">
                  <div className="ag-av ag-av-ai">AI</div>
                  <div className="ag-bbl ag-bbl-ai">
                    {msg.content === "" && loading ? (
                      <div className="ag-dots"><div className="ag-dot"/><div className="ag-dot"/><div className="ag-dot"/></div>
                    ) : (
                      <RichMessage content={msg.content} isStreaming={loading && i === messages.length - 1} outputFormat={outputFormat}/>
                    )}
                    {msg.meta && <MetaTags meta={msg.meta}/>}
                  </div>
                </div>
              )
            })}
            <div ref={bottomRef}/>
          </div>

          {/* Input area */}
          <div className="ag-input-area">
            {/* Attached files preview */}
            {attachedFiles.length > 0 && (
              <div className="ag-attach-preview">
                {attachedFiles.map(af => (
                  <div key={af.id} className="ag-attach-item">
                    <span>{FILE_ICONS[af.analysis?.type ?? "unknown"]}</span>
                    <span className="ag-attach-name" title={af.file.name}>{af.file.name}</span>
                    {af.analyzing
                      ? <span className="ag-attach-loading">…</span>
                      : <span className="ag-attach-analysis">✓</span>}
                    <button className="ag-attach-rm" onClick={() => removeFile(af.id)}>✕</button>
                  </div>
                ))}
              </div>
            )}

            {/* File analysis info + tool suggestions */}
            {attachedFiles.filter(a => !a.analyzing && a.analysis).map(af => (
              af.analysis?.tool_suggestions && af.analysis.tool_suggestions.length > 0 && (
                <div key={af.id} style={{padding:"6px 18px 0"}}>
                  <div className="ag-fa-card">
                    <div className="ag-fa-title">💡 Gợi ý cho {af.file.name}</div>
                    <div>{af.analysis.summary.split("\n")[0]}</div>
                    <div className="ag-tool-suggest">
                      {af.analysis.tool_suggestions.map(t => (
                        <button key={t} className="ag-tool-suggest-btn"
                          onClick={() => send(`Dùng tool ${TOOL_LABELS[t] ?? t} cho file ${af.file.name}`)}>
                          {TOOL_LABELS[t] ?? t}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )
            ))}

            <div className="ag-input-row">
              {/* Attach button */}
              <button className="ag-attach-btn" onClick={() => fileInputRef.current?.click()} title="Đính kèm file">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                </svg>
              </button>
              <input ref={fileInputRef} type="file" multiple accept="*/*"
                style={{display:"none"}} onChange={handleFileInputChange}/>

              <div className="ag-input-wrap">
                <input ref={inputRef} className="ag-input"
                  placeholder={pendingTool ? "Upload file bên trên trước…" : "Nhập yêu cầu kế toán hoặc kéo thả file…"}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
                  disabled={loading || !!pendingTool}/>
                <button className="ag-send-btn" onClick={() => send()} disabled={loading || !!pendingTool || !input.trim()}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                  </svg>
                </button>
              </div>
            </div>

            <div className="ag-input-hint">
              Enter gửi · Clip đính file · Kéo thả file/ảnh/thư mục · {currentModel ? currentModel.name : "loading…"}
            </div>
          </div>
        </div>
      </div>

      {showProfile && <ProfileSettings onClose={() => setShowProfile(false)}/>}
    </>
  )
}

// ── Rich message renderer ──────────────────────────────────────────────────

function RichMessage({ content, isStreaming, outputFormat }: {
  content: string; isStreaming: boolean; outputFormat: OutputFormat
}) {
  const blocks = extractCodeBlocks(content)
  const hasBlocks = blocks.length > 0

  const copyToClipboard = (text: string) => navigator.clipboard.writeText(text)

  const getDownloadFormat = (lang: string): OutputFormat => {
    if (lang === "json") return "json"
    if (lang === "html") return "html"
    return "markdown"
  }

  if (!hasBlocks) {
    return (
      <div className="ag-bbl-ai-inner">
        <span dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}/>
        {isStreaming && <span className="ag-cursor"/>}
      </div>
    )
  }

  // Message with code blocks
  let remaining = content
  const parts: React.ReactNode[] = []
  const re = /```(\w*)\n([\s\S]*?)```/g
  let m; let lastIdx = 0; let key = 0

  while ((m = re.exec(content)) !== null) {
    const before = content.slice(lastIdx, m.index)
    if (before.trim()) {
      parts.push(
        <div key={key++} className="ag-bbl-ai-inner" dangerouslySetInnerHTML={{ __html: renderMarkdown(before) }}/>
      )
    }
    const lang = m[1] || "text"
    const code = m[2].trim()
    const dlFmt = getDownloadFormat(lang)
    parts.push(
      <div key={key++} className="ag-code-block">
        <div className="ag-code-header">
          <span className="ag-code-lang">{lang || "code"}</span>
          <div className="ag-code-actions">
            <button className="ag-code-btn ag-code-btn-cp" onClick={() => copyToClipboard(code)}>Copy</button>
            <button className="ag-code-btn ag-code-btn-dl"
              onClick={() => downloadContent(code, dlFmt, `export-${lang}`)}>
              ⬇ {dlFmt.toUpperCase()}
            </button>
          </div>
        </div>
        <pre className="ag-code-body">{code}</pre>
      </div>
    )
    lastIdx = m.index + m[0].length
  }

  const after = content.slice(lastIdx)
  if (after.trim()) {
    parts.push(
      <div key={key++} className="ag-bbl-ai-inner" dangerouslySetInnerHTML={{ __html: renderMarkdown(after) }}/>
    )
  }

  return (
    <div>
      {parts}
      {isStreaming && <span className="ag-cursor" style={{margin:"0 0 8px 14px", display:"block"}}/>}
      {/* Download full response */}
      {!isStreaming && content.length > 100 && (
        <div style={{display:"flex",gap:6,padding:"4px 14px 10px",flexWrap:"wrap"}}>
          {(["markdown","json","html"] as OutputFormat[]).map(f => (
            <button key={f} className="ag-code-btn ag-code-btn-dl"
              style={{fontSize:10}}
              onClick={() => downloadContent(content, f, "analysis")}>
              ⬇ {f.toUpperCase()}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Meta tags ──────────────────────────────────────────────────────────────

function MetaTags({ meta }: { meta: AgentMeta }) {
  return (
    <div className="ag-meta">
      {meta.flagged_count !== undefined && <>
        <span className="ag-tag ag-tag-warn">⚠ {meta.flagged_count}/{meta.total_rows} vượt ngưỡng</span>
        {meta.period && <span className="ag-tag ag-tag-info">{meta.period}</span>}
        <span className="ag-tag ag-tag-info">Ngưỡng {((meta.threshold ?? 0.15)*100).toFixed(0)}%</span>
      </>}
      {meta.summary && <>
        <span className="ag-tag ag-tag-ok">✓ Khớp {meta.summary.match_rate}%</span>
        <span className="ag-tag ag-tag-err">✗ NH: {meta.summary.unmatched_bank}</span>
        <span className="ag-tag ag-tag-err">✗ SS: {meta.summary.unmatched_book}</span>
      </>}
    </div>
  )
}
