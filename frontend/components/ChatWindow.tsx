"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import {
  streamChat, Message, Conversation,
  fetchConversations, createConversation,
  updateConversationTitle, deleteConversationAPI
} from "@/lib/api"
import ProfileSettings from "@/components/ProfileSettings"

const SUGGESTED = [
  "Explain how RAG pipelines work",
  "Write a Python async function example",
  "What is the difference between LSTM and Transformer?",
  "How does SSE streaming work in FastAPI?",
]

function makeTitle(content: string) {
  return content.length > 36 ? content.slice(0, 36) + "…" : content
}

export default function ChatWindow() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const active = conversations.find(c => c.id === activeId) ?? null
  const messages = active?.messages ?? []

  // Load conversations từ DB khi khởi động
  useEffect(() => {
    fetchConversations().then(data => {
      setConversations(data)
      if (data.length > 0) setActiveId(data[0].id)
      setHydrated(true)
    })
  }, [])

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [])

  useEffect(() => {
    if (!showScrollBtn) scrollToBottom()
  }, [messages, showScrollBtn, scrollToBottom])

  const handleScroll = () => {
    const el = messagesRef.current
    if (!el) return
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 120)
  }

  const newChat = async () => {
    if (loading) return
    const conv = await createConversation("New Chat")
    if (!conv) return
    setConversations(prev => [conv, ...prev])
    setActiveId(conv.id)
    setInput("")
    setShowScrollBtn(false)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const switchChat = (id: string) => {
    if (loading || id === activeId) return
    setActiveId(id)
    setShowScrollBtn(false)
  }

  const deleteChat = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (loading) return
    await deleteConversationAPI(id)
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id)
      if (activeId === id) setActiveId(next[0]?.id ?? null)
      return next
    })
  }

  const send = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || loading) return

    let currentId = activeId
    let isNewConv = false

    // Tạo conversation mới nếu chưa có
    if (!currentId) {
      const conv = await createConversation(makeTitle(content))
      if (!conv) return
      setConversations(prev => [conv, ...prev])
      setActiveId(conv.id)
      currentId = conv.id
      isNewConv = true
    }

    const userMsg: Message = { role: "user", content }
    setInput("")
    setLoading(true)
    setShowScrollBtn(false)

    // Cập nhật title nếu là tin nhắn đầu tiên
    const currentConv = conversations.find(c => c.id === currentId)
    if (!isNewConv && currentConv && currentConv.messages.length === 0) {
      const title = makeTitle(content)
      await updateConversationTitle(currentId!, title)
      setConversations(prev => prev.map(c => c.id === currentId ? { ...c, title } : c))
    }

    // Thêm messages vào local state
    setConversations(prev => prev.map(c =>
      c.id === currentId
        ? { ...c, messages: [...c.messages, userMsg, { role: "assistant", content: "" }] }
        : c
    ))

    const snapshot = [...(conversations.find(c => c.id === currentId)?.messages ?? []), userMsg]

    await streamChat(
      snapshot,
      "You are a helpful assistant.",
      currentId,
      (token: string) => {
        setConversations(prev => prev.map(c => {
          if (c.id !== currentId) return c
          const msgs = [...c.messages]
          msgs[msgs.length - 1] = { role: "assistant", content: msgs[msgs.length - 1].content + token }
          return { ...c, messages: msgs }
        }))
      },
      () => { setLoading(false); inputRef.current?.focus() }
    )
  }

  if (!hydrated) {
    return (
      <div style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center", background: "#0a0a0f", color: "rgba(255,255,255,0.3)", fontFamily: "monospace", fontSize: 13 }}>
        loading...
      </div>
    )
  }

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700&family=JetBrains+Mono:wght@300;400&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0a0a0f; font-family: 'Syne', sans-serif; overflow: hidden; }
        .chat-root { display: flex; height: 100vh; width: 100%; background: #0a0a0f; position: relative; overflow: hidden; }
        .blob { position: absolute; border-radius: 50%; filter: blur(90px); pointer-events: none; opacity: 0.15; }
        .blob-1 { width: 520px; height: 520px; background: radial-gradient(circle, #3b82f6, transparent); top: -120px; left: -120px; animation: drift1 14s ease-in-out infinite; }
        .blob-2 { width: 420px; height: 420px; background: radial-gradient(circle, #7c3aed, transparent); bottom: -100px; right: -100px; animation: drift2 18s ease-in-out infinite; }
        .blob-3 { width: 320px; height: 320px; background: radial-gradient(circle, #0891b2, transparent); top: 45%; left: 50%; transform: translate(-50%,-50%); animation: drift3 22s ease-in-out infinite; }
        @keyframes drift1 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(30px,20px)} }
        @keyframes drift2 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-20px,-30px)} }
        @keyframes drift3 { 0%,100%{transform:translate(-50%,-50%)} 50%{transform:translate(-46%,-54%)} }
        .sidebar { width: 236px; flex-shrink: 0; border-right: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; padding: 20px 12px 16px; gap: 4px; background: rgba(255,255,255,0.015); backdrop-filter: blur(16px); position: relative; z-index: 1; }
        .sidebar-logo { font-size: 12px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: rgba(255,255,255,0.85); padding: 0 6px 16px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
        .logo-dot { width: 8px; height: 8px; border-radius: 50%; background: #3b82f6; box-shadow: 0 0 10px #3b82f6; animation: pulse-dot 2.5s ease-in-out infinite; }
        @keyframes pulse-dot { 0%,100%{opacity:1;box-shadow:0 0 10px #3b82f6} 50%{opacity:0.5;box-shadow:0 0 22px #3b82f6} }
        .new-chat-btn { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-family: 'Syne', sans-serif; font-weight: 500; color: rgba(255,255,255,0.75); cursor: pointer; background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.18); transition: all 0.18s; margin-bottom: 8px; width: 100%; text-align: left; }
        .new-chat-btn:hover:not(:disabled) { background: rgba(59,130,246,0.18); color: white; }
        .new-chat-btn:disabled { opacity: 0.4; cursor: default; }
        .sidebar-label { font-size: 10px; font-weight: 600; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(255,255,255,0.2); padding: 4px 6px 6px; }
        .conv-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
        .conv-list::-webkit-scrollbar { width: 2px; }
        .conv-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); border-radius: 2px; }
        .conv-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; color: rgba(255,255,255,0.4); font-size: 12px; animation: conv-in 0.2s ease-out; }
        @keyframes conv-in { from{opacity:0;transform:translateX(-6px)} to{opacity:1;transform:translateX(0)} }
        .conv-item:hover { background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.7); }
        .conv-item.active { background: rgba(59,130,246,0.08); border-color: rgba(59,130,246,0.15); color: rgba(255,255,255,0.85); }
        .conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.3; }
        .conv-delete { width: 18px; height: 18px; border-radius: 4px; flex-shrink: 0; background: transparent; border: none; cursor: pointer; color: rgba(255,255,255,0.2); font-size: 11px; display: flex; align-items: center; justify-content: center; transition: all 0.15s; opacity: 0; }
        .conv-item:hover .conv-delete { opacity: 1; }
        .conv-delete:hover { background: rgba(239,68,68,0.15); color: rgba(239,68,68,0.8); }
        .sidebar-empty { padding: 20px 6px; text-align: center; font-size: 11px; color: rgba(255,255,255,0.15); font-family: 'JetBrains Mono', monospace; line-height: 1.6; }
        .chat-main { flex: 1; display: flex; flex-direction: column; position: relative; z-index: 1; overflow: hidden; }
        .topbar { padding: 18px 28px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: space-between; background: rgba(255,255,255,0.01); backdrop-filter: blur(8px); }
        .topbar-left { display: flex; align-items: center; gap: 10px; }
        .status-dot { width: 7px; height: 7px; border-radius: 50%; transition: all 0.3s; }
        .status-dot.online { background: #22c55e; box-shadow: 0 0 8px #22c55e; }
        .status-dot.thinking { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; animation: thinking-pulse 1s ease-in-out infinite; }
        @keyframes thinking-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        .topbar-title { font-size: 14px; font-weight: 600; color: rgba(255,255,255,0.65); letter-spacing: 0.04em; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .status-label { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: rgba(255,255,255,0.25); transition: color 0.3s; }
        .status-label.thinking { color: #f59e0b; }
        .model-badge { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: rgba(59,130,246,0.75); background: rgba(59,130,246,0.07); border: 1px solid rgba(59,130,246,0.13); padding: 4px 10px; border-radius: 20px; letter-spacing: 0.04em; }
        .messages { flex: 1; overflow-y: auto; padding: 28px 28px 12px; display: flex; flex-direction: column; gap: 20px; position: relative; }
        .messages::-webkit-scrollbar { width: 3px; }
        .messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.07); border-radius: 3px; }
        .empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 40px 0 20px; animation: fade-in 0.35s ease-out; }
        @keyframes fade-in { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        .empty-icon { width: 54px; height: 54px; border-radius: 16px; background: rgba(59,130,246,0.09); border: 1px solid rgba(59,130,246,0.18); display: flex; align-items: center; justify-content: center; font-size: 22px; animation: icon-float 4s ease-in-out infinite; }
        @keyframes icon-float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
        .empty-title { font-size: 17px; font-weight: 600; color: rgba(255,255,255,0.5); }
        .empty-sub { font-size: 12px; color: rgba(255,255,255,0.18); font-family: 'JetBrains Mono', monospace; }
        .suggestions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; max-width: 540px; margin-top: 8px; }
        .suggestion-chip { padding: 10px 14px; border-radius: 10px; font-size: 12px; color: rgba(255,255,255,0.4); background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); cursor: pointer; text-align: left; transition: all 0.18s; line-height: 1.4; font-family: 'Syne', sans-serif; }
        .suggestion-chip:hover { background: rgba(59,130,246,0.08); border-color: rgba(59,130,246,0.2); color: rgba(255,255,255,0.75); transform: translateY(-1px); }
        .msg-row { display: flex; gap: 12px; align-items: flex-start; animation: msg-in 0.22s cubic-bezier(0.16,1,0.3,1); }
        @keyframes msg-in { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        .msg-row.user { flex-direction: row-reverse; }
        .avatar { width: 30px; height: 30px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; margin-top: 2px; }
        .avatar-ai { background: rgba(59,130,246,0.12); border: 1px solid rgba(59,130,246,0.22); color: #60a5fa; }
        .avatar-user { background: rgba(139,92,246,0.12); border: 1px solid rgba(139,92,246,0.22); color: #a78bfa; }
        .bubble { max-width: 68%; padding: 11px 15px; border-radius: 14px; font-size: 14px; line-height: 1.68; white-space: pre-wrap; word-break: break-word; }
        .bubble-ai { background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.07); color: rgba(255,255,255,0.82); border-top-left-radius: 4px; }
        .bubble-user { background: rgba(59,130,246,0.13); border: 1px solid rgba(59,130,246,0.18); color: rgba(255,255,255,0.88); border-top-right-radius: 4px; }
        .dots { display: flex; gap: 5px; align-items: center; height: 18px; }
        .dot { width: 5px; height: 5px; border-radius: 50%; background: rgba(255,255,255,0.28); animation: bounce 1.2s ease-in-out infinite; }
        .dot:nth-child(2){animation-delay:0.15s} .dot:nth-child(3){animation-delay:0.3s}
        @keyframes bounce { 0%,80%,100%{transform:translateY(0);opacity:0.28} 40%{transform:translateY(-5px);opacity:1} }
        .cursor { display:inline-block; width:2px; height:13px; background:#60a5fa; margin-left:2px; vertical-align:middle; animation:blink 0.75s step-end infinite; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        .scroll-btn { position: absolute; bottom: 16px; right: 20px; width: 34px; height: 34px; border-radius: 50%; background: rgba(59,130,246,0.18); border: 1px solid rgba(59,130,246,0.25); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.18s; color: #60a5fa; animation: fade-in 0.2s ease-out; }
        .scroll-btn:hover { background: rgba(59,130,246,0.28); transform: translateY(-2px); }
        .input-area { padding: 16px 24px 20px; border-top: 1px solid rgba(255,255,255,0.05); background: rgba(255,255,255,0.01); backdrop-filter: blur(8px); }
        .input-wrap { display: flex; gap: 10px; align-items: center; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 13px; padding: 5px 5px 5px 16px; transition: border-color 0.2s, box-shadow 0.2s; }
        .input-wrap:focus-within { border-color: rgba(59,130,246,0.35); box-shadow: 0 0 0 3px rgba(59,130,246,0.06); }
        .chat-input { flex: 1; background: transparent; border: none; outline: none; font-size: 14px; font-family: 'Syne', sans-serif; color: rgba(255,255,255,0.85); padding: 8px 0; caret-color: #3b82f6; }
        .chat-input::placeholder { color: rgba(255,255,255,0.18); }
        .chat-input:disabled { opacity: 0.45; }
        .send-btn { width: 38px; height: 38px; border-radius: 9px; background: #3b82f6; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.15s; flex-shrink: 0; }
        .send-btn:hover:not(:disabled) { background: #2563eb; }
        .send-btn:active:not(:disabled) { transform: scale(0.92); }
        .send-btn:disabled { background: rgba(255,255,255,0.06); cursor: default; }
        .input-hint { text-align: center; font-size: 11px; font-family: 'JetBrains Mono', monospace; color: rgba(255,255,255,0.1); margin-top: 9px; letter-spacing: 0.05em; }
      `}</style>

      <div className="chat-root">
        <div className="blob blob-1"/><div className="blob blob-2"/><div className="blob blob-3"/>
        <div className="sidebar">
          <div className="sidebar-logo"><div className="logo-dot"/>AXON</div>
          <button className="new-chat-btn" onClick={newChat} disabled={loading}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Chat
          </button>
          {conversations.length > 0 && <div className="sidebar-label">History</div>}
          <div className="conv-list">
            {conversations.length === 0 ? (
              <div className="sidebar-empty">no conversations yet<br/>start a new chat</div>
            ) : conversations.map(c => (
              <div key={c.id} className={`conv-item ${c.id === activeId ? "active" : ""}`} onClick={() => switchChat(c.id)}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{flexShrink:0,opacity:0.5}}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                <span className="conv-title">{c.title}</span>
                <button className="conv-delete" onClick={(e) => deleteChat(c.id, e)}>✕</button>
              </div>
            ))}
          </div>

          <button
            onClick={() => setShowProfile(true)}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "9px 12px", borderRadius: 8, fontSize: 13,
              fontFamily: "'Syne', sans-serif", fontWeight: 500,
              color: "rgba(255,255,255,0.3)", cursor: "pointer",
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.06)",
              transition: "all 0.18s", width: "100%", textAlign: "left",
              marginTop: 8,
            }}
          >
            ⚙ Profile
          </button>
        </div>

        <div className="chat-main">
          <div className="topbar">
            <div className="topbar-left">
              <div className={`status-dot ${loading ? "thinking" : "online"}`}/>
              <span className="topbar-title">{active?.title ?? "Assistant"}</span>
              <span className={`status-label ${loading ? "thinking" : ""}`}>{loading ? "thinking..." : "online"}</span>
            </div>
            <span className="model-badge">llama-3.1-8b · groq</span>
          </div>

          <div className="messages" ref={messagesRef} onScroll={handleScroll}>
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">⚡</div>
                <div className="empty-title">Ready</div>
                <div className="empty-sub">type something to begin</div>
                <div className="suggestions">
                  {SUGGESTED.map((s, i) => <button key={i} className="suggestion-chip" onClick={() => send(s)}>{s}</button>)}
                </div>
              </div>
            ) : messages.map((m, i) => (
              <div key={i} className={`msg-row ${m.role === "user" ? "user" : ""}`}>
                <div className={`avatar ${m.role === "assistant" ? "avatar-ai" : "avatar-user"}`}>{m.role === "assistant" ? "AI" : "U"}</div>
                <div className={`bubble ${m.role === "assistant" ? "bubble-ai" : "bubble-user"}`}>
                  {m.role === "assistant" && m.content === "" && loading ? (
                    <div className="dots"><div className="dot"/><div className="dot"/><div className="dot"/></div>
                  ) : (
                    <>{m.content}{loading && i === messages.length - 1 && m.role === "assistant" && m.content !== "" && <span className="cursor"/>}</>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef}/>
            {showScrollBtn && (
              <button className="scroll-btn" onClick={scrollToBottom}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
              </button>
            )}
          </div>

          <div className="input-area">
            <div className="input-wrap">
              <input ref={inputRef} className="chat-input"
                placeholder={active ? "Message the assistant..." : "Start a new chat or type to begin..."}
                value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
                disabled={loading}
              />
              <button className="send-btn" onClick={() => send()} disabled={loading || !input.trim()}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
              </button>
            </div>
            <div className="input-hint">enter to send · built on groq</div>
          </div>
        </div>
      </div>
      {showProfile && <ProfileSettings onClose={() => setShowProfile(false)} />}
    </>
  )
}