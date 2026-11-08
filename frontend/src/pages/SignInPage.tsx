import { useState } from 'react'
import { ArrowRightIcon, LogInIcon } from 'lucide-react'
import { useAuth } from 'react-oidc-context'
import { Link, useSearchParams } from 'react-router'

import { IDLE_TIMEOUT_MINUTES, signIn } from '@/auth/oidc'
import { FullPageMessage } from '@/components/full-page-message'
import { Button } from '@/components/ui/button'

/** Public page: after signing out, after inactivity, or when opened directly. */
export function SignInPage() {
  const auth = useAuth()
  const [params] = useSearchParams()
  const [unreachable, setUnreachable] = useState(false)

  if (auth.isAuthenticated) {
    return (
      <FullPageMessage title="You Are Signed In" description={auth.user?.profile.email}>
        <Button className="w-full" nativeButton={false} render={<Link to="/" />}>
          Go to the App
          <ArrowRightIcon data-icon="inline-end" />
        </Button>
      </FullPageMessage>
    )
  }

  const description =
    params.get('reason') === 'idle'
      ? `You were signed out after ${IDLE_TIMEOUT_MINUTES} minutes without activity.`
      : params.has('signed_out')
        ? 'You are signed out.'
        : 'Sign in with the e-mail address and password of your BizPartnerCheck account.'

  return (
    <FullPageMessage title="Sign In to BizPartnerCheck" description={description}>
      <Button
        className="w-full"
        onClick={() => {
          setUnreachable(false)
          signIn('/').catch(() => setUnreachable(true))
        }}
        disabled={Boolean(auth.activeNavigator)}
      >
        <LogInIcon data-icon="inline-start" />
        Sign In
      </Button>
      {unreachable && (
        <p role="alert" className="text-center text-sm text-destructive">
          The sign-in service cannot be reached right now. Please try again in a moment.
        </p>
      )}
    </FullPageMessage>
  )
}
