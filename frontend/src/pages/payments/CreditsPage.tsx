import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Coins, Crown } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { errorMessage, payments, type CreditsResponse } from "../../lib/api"

export function CreditsPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<CreditsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    payments
      .credits()
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!data) return <FullPageSpinner />

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col items-center gap-3 p-6 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-accent-400/20">
          {data.has_active_subscription ? (
            <Crown className="size-7 text-accent-600" aria-hidden />
          ) : (
            <Coins className="size-7 text-accent-600" aria-hidden />
          )}
        </div>
        {data.has_active_subscription ? (
          <>
            <p className="text-lg font-semibold text-zinc-900">Active subscription</p>
            <p className="text-sm text-zinc-500">Unlimited exam-solve credits while it's active.</p>
          </>
        ) : (
          <>
            <p className="text-3xl font-semibold text-zinc-900">{data.balance}</p>
            <p className="text-sm text-zinc-500">credits remaining</p>
          </>
        )}
      </Card>

      {!data.has_active_subscription && (
        <Button size="lg" fullWidth onClick={() => navigate("/credits/buy")}>
          Buy credits
        </Button>
      )}

      <p className="text-center text-xs text-zinc-400">
        Explain mode and practice questions are free. Credits are used for the exam-photo solver.
      </p>
    </div>
  )
}
