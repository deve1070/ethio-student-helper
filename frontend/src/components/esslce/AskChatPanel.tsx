import { useState } from "react"
import { MessageCircle, Send } from "lucide-react"
import { Button } from "../ui/Button"
import { Card } from "../ui/Card"
import { Spinner } from "../ui/Primitives"
import { errorMessage, esslce } from "../../lib/api"

interface Message {
  role: "user" | "assistant"
  content: string
  imageBase64?: string | null
}

export function AskChatPanel({ questionId }: { questionId: number }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [error, setError] = useState("")

  async function send() {
    const text = draft.trim()
    if (!text) return
    setDraft("")
    setError("")
    const nextMessages = [...messages, { role: "user" as const, content: text }]
    setMessages(nextMessages)
    setSending(true)
    try {
      const history = nextMessages.slice(-12)
      const res = await esslce.ask(questionId, text, history)
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.reply, imageBase64: res.reply_image_base64 },
      ])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSending(false)
    }
  }

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        <MessageCircle className="size-4" aria-hidden /> Ask about this
      </Button>
    )
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
        <MessageCircle className="size-4 text-brand-600" aria-hidden /> Ask about this question
      </p>

      {messages.length === 0 && (
        <p className="text-sm text-zinc-500">Ask anything about this question - why an option is wrong, for an example, or a different way to think about it.</p>
      )}

      <div className="flex flex-col gap-2">
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              "max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed " +
              (m.role === "user" ? "self-end bg-brand-600 text-white" : "self-start bg-zinc-100 text-zinc-800")
            }
          >
            {m.imageBase64 ? (
              <img
                src={`data:image/png;base64,${m.imageBase64}`}
                alt="Worked explanation"
                className="max-w-full rounded-lg"
              />
            ) : (
              m.content
            )}
          </div>
        ))}
        {sending && (
          <div className="self-start flex items-center gap-2 rounded-xl bg-zinc-100 px-3 py-2 text-sm text-zinc-500">
            <Spinner className="size-4" /> Thinking...
          </div>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        className="flex items-end gap-2"
      >
        <textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder="Type your question..."
          className="max-h-24 flex-1 resize-none rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30"
        />
        <Button type="submit" size="md" disabled={sending || !draft.trim()}>
          <Send className="size-4" aria-hidden />
        </Button>
      </form>
    </Card>
  )
}
