import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Crown, Sparkles } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, FullPageSpinner, ProgressBar } from "../../components/ui/Primitives"
import { errorMessage, payments, type EntitlementResponse } from "../../lib/api"

export function CreditsPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<EntitlementResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    payments
      .entitlement()
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
            <Sparkles className="size-7 text-accent-600" aria-hidden />
          )}
        </div>
        {data.has_active_subscription ? (
          <>
            <p className="text-lg font-semibold text-zinc-900">Active subscription</p>
            <p className="text-sm text-zinc-500">
              Unlimited access to every AI feature
              {data.subscription_expires_at
                ? ` until ${new Date(data.subscription_expires_at).toLocaleDateString()}`
                : ""}
              .
            </p>
          </>
        ) : (
          <>
            <p className="text-3xl font-semibold text-zinc-900">
              {data.free_actions_used} / {data.free_actions_quota}
            </p>
            <p className="text-sm text-zinc-500">free previews used</p>
            <ProgressBar
              value={(data.free_actions_used / data.free_actions_quota) * 100}
              className="mt-1 w-full"
            />
          </>
        )}
      </Card>

      {!data.has_active_subscription && (
        <Button size="lg" fullWidth onClick={() => navigate("/subscribe")}>
          Subscribe for 300 ETB/year
        </Button>
      )}

      <p className="text-center text-xs text-zinc-400">
        {data.has_active_subscription
          ? "Thanks for subscribing - it covers notes, explain, elaborations, ask-about-question, and exam solving for a full year."
          : `Every student gets ${data.free_actions_quota} free previews across notes, explain, elaborations, and ask-about-question. Subscribe once for a full year of unlimited access.`}
      </p>
    </div>
  )
}
