import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Camera, CheckCircle2, Clock, ImageIcon, X } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, Field, TextInput } from "../../components/ui/Primitives"
import { errorMessage, payments } from "../../lib/api"
import { usePublicConfig } from "../../lib/publicConfig"


export function BuyPage() {
  const navigate = useNavigate()
  const config = usePublicConfig()
  const [transactionId, setTransactionId] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ status: "completed" | "pending"; message: string } | null>(null)
  // Two inputs: the camera one carries capture="environment", which opens the camera directly; the
  // other has no capture, so the phone offers its gallery and files (where a receipt screenshot is).
  const cameraInput = useRef<HTMLInputElement>(null)
  const galleryInput = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  function pick(e: React.ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null)
    e.target.value = "" // picking the same photo again still fires onChange
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!file) return
    setError(null)
    setLoading(true)
    try {
      const res = await payments.submitReceipt(transactionId, file)
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
        <Button onClick={() => navigate("/subscription")}>Done</Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <button
        onClick={() => navigate("/subscription")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Subscription
      </button>

      <Card className="flex flex-col gap-2 p-4 text-sm">
        {config ? (
          <>
            <p className="font-medium text-zinc-900">
              Send {config.subscription_price_etb} ETB to one of these, then submit your receipt below - that's
              a full year of unlimited access, one payment.
            </p>
            <p className="text-zinc-600">Telebirr: {config.payment_telebirr_number}</p>
            <p className="text-zinc-600">CBE: {config.payment_cbe_account}</p>
          </>
        ) : (
          <p className="text-zinc-500">Loading payment details...</p>
        )}
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

        <Field label="Receipt photo or screenshot" htmlFor="receiptGallery">
          {preview ? (
            <div className="relative overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50">
              <img src={preview} alt="Selected receipt" className="max-h-72 w-full object-contain" />
              <button
                type="button"
                onClick={() => setFile(null)}
                aria-label="Remove photo"
                className="absolute top-2 right-2 flex size-8 items-center justify-center rounded-full bg-black/60 text-white"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => galleryInput.current?.click()}
                className="flex h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 text-sm text-zinc-600 hover:border-brand-400 hover:text-brand-700"
              >
                <ImageIcon className="size-6" aria-hidden />
                Choose from gallery
              </button>
              <button
                type="button"
                onClick={() => cameraInput.current?.click()}
                className="flex h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 text-sm text-zinc-600 hover:border-brand-400 hover:text-brand-700"
              >
                <Camera className="size-6" aria-hidden />
                Take a photo
              </button>
            </div>
          )}
          <input ref={galleryInput} id="receiptGallery" type="file" accept="image/*" className="hidden" onChange={pick} />
          <input ref={cameraInput} type="file" accept="image/*" capture="environment" className="hidden" onChange={pick} />
        </Field>

        <Button type="submit" size="lg" fullWidth loading={loading} disabled={!file || !transactionId}>
          Submit
        </Button>
      </form>
    </div>
  )
}
