import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Camera, CheckCircle2, Clock } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, Field, TextInput } from "../../components/ui/Primitives"
import { errorMessage, payments } from "../../lib/api"

const BUNDLES = [
  { id: "bundle_5", credits: 5, etb: 25 },
  { id: "bundle_20", credits: 20, etb: 90 },
]

// Matches telegram_bot/handlers/payment_handler.py's receiving accounts - public by design.
const TELEBIRR_NUMBER = "0909575318"
const CBE_ACCOUNT_NUMBER = "1000198942948"

export function BuyPage() {
  const navigate = useNavigate()
  const [bundle, setBundle] = useState<(typeof BUNDLES)[number] | null>(null)
  const [transactionId, setTransactionId] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ status: "completed" | "pending"; message: string } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!bundle || !file) return
    setError(null)
    setLoading(true)
    try {
      const res = await payments.submitReceipt(bundle.id, transactionId, file)
      setResult({ status: res.status, message: res.message })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (result) {
    return (
      <div className="flex flex-col items-center gap-4 py-10 text-center">
        <div
          className={
            "flex size-14 items-center justify-center rounded-full " +
            (result.status === "completed" ? "bg-emerald-100" : "bg-amber-100")
          }
        >
          {result.status === "completed" ? (
            <CheckCircle2 className="size-7 text-emerald-700" aria-hidden />
          ) : (
            <Clock className="size-7 text-amber-700" aria-hidden />
          )}
        </div>
        <p className="max-w-xs text-[15px] text-zinc-700">{result.message}</p>
        <Button onClick={() => navigate("/credits")}>Done</Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <button
        onClick={() => navigate("/credits")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Credits
      </button>

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-700">Choose a bundle</p>
        <div className="grid grid-cols-2 gap-2.5">
          {BUNDLES.map((b) => (
            <button
              key={b.id}
              onClick={() => setBundle(b)}
              className={
                "rounded-xl border p-4 text-left transition-colors " +
                (bundle?.id === b.id
                  ? "border-brand-600 bg-brand-50"
                  : "border-zinc-200 bg-white hover:border-brand-300")
              }
            >
              <p className="text-lg font-semibold text-zinc-900">{b.credits} credits</p>
              <p className="text-sm text-zinc-500">{b.etb} ETB</p>
            </button>
          ))}
        </div>
      </div>

      {bundle && (
        <>
          <Card className="flex flex-col gap-2 p-4 text-sm">
            <p className="font-medium text-zinc-900">
              Send {bundle.etb} ETB to one of these, then submit your receipt below
            </p>
            <p className="text-zinc-600">Telebirr: {TELEBIRR_NUMBER}</p>
            <p className="text-zinc-600">CBE: {CBE_ACCOUNT_NUMBER}</p>
          </Card>

          <form onSubmit={submit} className="flex flex-col gap-4">
            {error && <ErrorBanner message={error} />}
            <Field label="Transaction ID from your receipt" htmlFor="txId">
              <TextInput
                id="txId"
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                required
              />
            </Field>

            <Field label="Receipt photo" htmlFor="receipt">
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="flex h-32 w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 text-sm text-zinc-500 hover:border-brand-400 hover:text-brand-700"
              >
                <Camera className="size-6" aria-hidden />
                {file ? file.name : "Tap to choose a photo"}
              </button>
              <input
                ref={fileInput}
                id="receipt"
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                required
              />
            </Field>

            <Button type="submit" size="lg" fullWidth loading={loading} disabled={!file || !transactionId}>
              Submit
            </Button>
          </form>
        </>
      )}
    </div>
  )
}
