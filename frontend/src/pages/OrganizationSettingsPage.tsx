import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { CircleCheckIcon, SaveIcon } from 'lucide-react'

import { ApiError } from '@/api/client'
import { getOrganization, updateOrganizationVatNumber, type Organization } from '@/api/organization'
import { ORG_ADMIN_ROLE, useRoles } from '@/auth/roles'
import { AppearanceSettings } from '@/components/appearance-settings'
import { PageHeader } from '@/components/page-header'
import { VideoGuidesSettings } from '@/components/video-guides'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; organization: Organization }
  | { status: 'error'; message: string }

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

export function OrganizationSettingsPage() {
  const roles = useRoles()
  const isOrgAdmin = roles.has(ORG_ADMIN_ROLE)
  const id = useId()

  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)
  const [vatNumber, setVatNumber] = useState('')
  const [vatError, setVatError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const vatInputRef = useRef<HTMLInputElement>(null)
  // Blocks a second submit (e.g. a fast double Enter) before React re-renders.
  const savingRef = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    setLoadState({ status: 'loading' })
    getOrganization(controller.signal)
      .then((organization) => {
        if (controller.signal.aborted) return
        setVatNumber(organization.vat_number ?? '')
        setLoadState({ status: 'ready', organization })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadState({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [reloadKey])

  const organization = loadState.status === 'ready' ? loadState.organization : null
  const unchanged = organization !== null && vatNumber.trim() === (organization.vat_number ?? '')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (savingRef.current || !organization || !isOrgAdmin) return
    savingRef.current = true
    setSaving(true)
    setSaved(false)
    setVatError('')
    try {
      const updated = await updateOrganizationVatNumber(vatNumber)
      setVatNumber(updated.vat_number ?? '')
      setLoadState({ status: 'ready', organization: updated })
      setSaved(true)
      setAnnouncement(
        updated.vat_number ? `Own VAT number ${updated.vat_number} saved.` : 'Own VAT number removed.',
      )
    } catch (error) {
      setVatError(errorMessage(error))
      vatInputRef.current?.focus()
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" description="How the app looks for you, and the details of your organization." />

      <AppearanceSettings />
      <VideoGuidesSettings />

      {loadState.status === 'error' && (
        <Alert variant="destructive">
          <AlertTitle>Could Not Load the Settings</AlertTitle>
          <AlertDescription>{loadState.message}</AlertDescription>
          <AlertAction>
            <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
              Try Again
            </Button>
          </AlertAction>
        </Alert>
      )}

      <Card aria-busy={loadState.status === 'loading'}>
        <CardHeader>
          <CardTitle>
            <h2>Organization</h2>
          </CardTitle>
          <CardDescription>
            {isOrgAdmin
              ? 'Only organization admins can change these settings.'
              : 'Only organization admins can change these settings. Ask an admin of your organization.'}
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent>
            {loadState.status === 'loading' ? (
              <SettingsSkeleton />
            ) : (
              <FieldGroup>
                <Field data-disabled>
                  <FieldLabel htmlFor={`${id}-name`}>Name</FieldLabel>
                  <Input id={`${id}-name`} value={organization?.name ?? ''} readOnly disabled />
                </Field>
                <Field data-invalid={vatError ? true : undefined} data-disabled={!isOrgAdmin || undefined}>
                  <FieldLabel htmlFor={`${id}-vat`}>Own VAT Number</FieldLabel>
                  <Input
                    ref={vatInputRef}
                    id={`${id}-vat`}
                    name="vat_number"
                    value={vatNumber}
                    onChange={(event) => {
                      setVatNumber(event.target.value)
                      setSaved(false)
                      if (vatError) setVatError('')
                    }}
                    placeholder="ATU12345678…"
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    className="font-mono tracking-wide"
                    disabled={!isOrgAdmin || !organization}
                    aria-invalid={vatError ? true : undefined}
                    aria-describedby={vatError ? `${id}-vat-hint ${id}-vat-error` : `${id}-vat-hint`}
                  />
                  <FieldDescription id={`${id}-vat-hint`}>
                    Sent to VIES with every VAT check, as the requester. VIES then returns a consultation
                    number as proof of the check. Leave empty to check without one.
                  </FieldDescription>
                  <FieldError id={`${id}-vat-error`}>{vatError}</FieldError>
                </Field>
                <Field data-disabled>
                  <FieldLabel htmlFor={`${id}-licences`}>Licence Presets</FieldLabel>
                  <Input id={`${id}-licences`} placeholder="Baumeister, Elektrotechnik…" disabled />
                  <FieldDescription>
                    Licences that are pre-selected when you start a new check (coming soon).
                  </FieldDescription>
                </Field>
              </FieldGroup>
            )}
          </CardContent>
          {isOrgAdmin && (
            <CardFooter className="justify-end gap-3">
              {saved && (
                <span className="flex items-center gap-1 text-sm text-muted-foreground">
                  <CircleCheckIcon aria-hidden className="size-4 text-emerald-600 dark:text-emerald-400" />
                  Saved
                </span>
              )}
              <Button type="submit" disabled={saving || !organization || unchanged}>
                {saving ? <Spinner data-icon="inline-start" /> : <SaveIcon data-icon="inline-start" />}
                {saving ? 'Saving…' : 'Save Changes'}
              </Button>
            </CardFooter>
          )}
        </form>
      </Card>

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  )
}

function SettingsSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading the settings…">
      {[0, 1, 2].map((row) => (
        <div key={row} className="flex flex-col gap-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-9 w-full max-w-md" />
        </div>
      ))}
    </div>
  )
}
