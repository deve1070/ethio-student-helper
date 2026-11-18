import { useNavigate } from "react-router-dom"
import { Crown } from "lucide-react"
import { Button } from "../ui/Button"
import { Card } from "../ui/Card"
import { usePublicConfig } from "../../lib/publicConfig"

/** Shown instead of a plain ErrorBanner whenever a gated AI feature's call fails with the
 * paywall's 402 (see lib/apiAuth.ts's isPaywallError) - every call site passes that 402's own
 * detail.message through, so the exact "N of 8 used" wording always matches the backend. */
export function SubscribeCta({ message }: { message: string }) {
  const navigate = useNavigate()
  const price = usePublicConfig()?.subscription_price_etb
  return (
    <Card className="flex flex-col items-center gap-3 p-5 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-accent-400/20">
        <Crown className="size-6 text-accent-600" aria-hidden />
      </div>
      <p className="text-[15px] leading-relaxed text-zinc-700">{message}</p>
      <Button size="lg" fullWidth onClick={() => navigate("/subscribe")}>
        {price ? `Subscribe for ${price} ETB/year` : "Subscribe"}
      </Button>
    </Card>
  )
}
