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