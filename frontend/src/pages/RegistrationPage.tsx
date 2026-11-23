import { useState } from 'react'
import { ApiError } from '@/api/client'

import { signIn } from '@/auth/oidc'
import { FullPageMessage } from '@/components/full-page-message'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { LANGUAGES, preferredLanguage, setPreferredLanguage, type Language } from '@/lib/language'

type FormValues = {
  companyName: string
  adminName: string
  email: string
  vatNumber: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

/** Request field names of the API and the form fields they belong to. */
const SERVER_FIELDS: Record<string, keyof FormValues> = {
  company_name: 'companyName',
  admin_name: 'adminName',
  email: 'email',
  vat_number: 'vatNumber',
}

const translations = {
  en: {
    title: 'Create Your Account',
    description: 'Register your company and start checking business partners.',
    company: 'Company name',
    admin: 'Administrator name',
    email: 'Email address',
    vat: 'VAT number (optional)',
    submit: 'Create Account',
    submitting: 'Creating account…',
    haveAccount: 'Already have an account?',
    signIn: 'Sign in',
    signInUnreachable: 'The sign-in service cannot be reached right now. Please try again in a moment.',
    successTitle: 'Check Your E-Mail',
    successHint: 'Open the link in the e-mail to confirm your address and set your password. Then you can sign in.',
    duplicateVat: 'An organisation with this VAT number is already registered.',
    required: 'This field is required.',
    invalidEmail: 'Please enter a valid email address.',
    language: 'Language',
    unavailable: 'The registration service is not connected yet.',
    success: 'Registration received! Please check your email for the verification link.',
    duplicateEmail: 'This email address is already registered.',
    registrationError: 'Registration failed. Please try again.',
  },
  de: {
    title: 'Konto erstellen',
    description: 'Registrieren Sie Ihr Unternehmen und beginnen Sie mit der Überprüfung von Geschäftspartnern.',
    company: 'Firmenname',
    admin: 'Name des Administrators',
    email: 'E-Mail-Adresse',
    vat: 'Umsatzsteuer-ID (optional)',
    submit: 'Konto erstellen',
    submitting: 'Konto wird erstellt…',
    haveAccount: 'Sie haben bereits ein Konto?',
    signIn: 'Anmelden',
    signInUnreachable: 'Der Anmeldedienst ist gerade nicht erreichbar. Bitte versuchen Sie es gleich noch einmal.',
    successTitle: 'Bitte prüfen Sie Ihre E-Mails',
    successHint: 'Öffnen Sie den Link in der E-Mail, um Ihre Adresse zu bestätigen und Ihr Passwort festzulegen. Danach können Sie sich anmelden.',
    duplicateVat: 'Eine Organisation mit dieser UID-Nummer ist bereits registriert.',
    required: 'Dieses Feld ist erforderlich.',
    invalidEmail: 'Bitte geben Sie eine gültige E-Mail-Adresse ein.',
    language: 'Sprache',
    unavailable: 'Der Registrierungsdienst ist noch nicht verbunden.',
    success: 'Registrierung erhalten! Bitte prüfen Sie Ihre E-Mails auf den Bestätigungslink.',
    duplicateEmail: 'Diese E-Mail-Adresse ist bereits registriert.',
    registrationError: 'Die Registrierung ist fehlgeschlagen. Bitte versuchen Sie es erneut.',
  },
}

export function RegistrationPage() {
  const [language, setLanguage] = useState<Language>(preferredLanguage)
  const [signInFailed, setSignInFailed] = useState(false)
  const [values, setValues] = useState<FormValues>({
    companyName: '',
    adminName: '',
    email: '',
    vatNumber: '',
  })
  function updateField(field: keyof FormValues, value: string) {
    setValues((current) => ({
      ...current,
      [field]: value,
    }))
    setErrors((current) => (current[field] ? { ...current, [field]: undefined } : current))
  }
  const [errors, setErrors] = useState<FormErrors>({})
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [registered, setRegistered] = useState(false)

  const t = translations[language]

  function chooseLanguage(next: Language) {
    setLanguage(next)
    // Keycloak's sign-in page opens in the same language later.
    setPreferredLanguage(next)
  }

  // Straight to Keycloak's sign-in page (no page of our own in between).
  function startSignIn() {
    setSignInFailed(false)
    signIn('/').catch(() => setSignInFailed(true))
  }

  const signInLink = (
    <div className="flex flex-col gap-2">
      <p className="text-center text-sm text-muted-foreground">
        {t.haveAccount}{' '}
        <button
          type="button"
          onClick={startSignIn}
          className="text-foreground underline underline-offset-4 hover:text-primary"
        >
          {t.signIn}
        </button>
      </p>
      {signInFailed && (
        <p role="alert" className="text-center text-sm text-destructive">
          {t.signInUnreachable}
        </p>
      )}
    </div>
  )

  function validate(): boolean {
    const newErrors: FormErrors = {}

    if (!values.companyName.trim()) {
      newErrors.companyName = t.required
    }

    if (!values.adminName.trim()) {
      newErrors.adminName = t.required
    }

    if (!values.email.trim()) {
      newErrors.email = t.required
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) {
      newErrors.email = t.invalidEmail
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }
async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
  event.preventDefault()
  setMessage('')

  if (!validate() || submitting) return

  const formData = new FormData(event.currentTarget)
  setSubmitting(true)

  try {
    const response = await fetch('/api/v1/registration', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        company_name: values.companyName,
        admin_name: values.adminName,
        email: values.email,
        vat_number: values.vatNumber.trim() || null,
        website: String(formData.get('website') ?? ''),
      }),
      signal: AbortSignal.timeout(15000),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => null)
      const detail = body?.detail

      // Errors about one field are shown at that field.
      const field = SERVER_FIELDS[detail?.field ?? '']
      if (field) {
        const text =
          detail?.code === 'email_already_registered'
            ? t.duplicateEmail
            : detail?.code === 'duplicate_organization_vat'
              ? t.duplicateVat
              : detail?.message || t.registrationError
        setErrors({ [field]: text })
        document.getElementById(field)?.focus()
        return
      }

      throw new ApiError(detail?.message || t.registrationError, response.status, detail?.code)
    }

    setRegistered(true)
    setMessage(t.success)
  } catch (error) {
    setMessage(
      error instanceof ApiError ? error.message : t.registrationError,
    )
  } finally {
    setSubmitting(false)
  }
}

  if (registered) {
    return (
      <FullPageMessage title={t.successTitle} description={values.email}>
        <p role="status" className="text-center text-sm text-muted-foreground">
          {t.successHint}
        </p>
        <Button className="w-full" onClick={startSignIn}>
          {t.signIn}
        </Button>
        {signInFailed && (
          <p role="alert" className="text-center text-sm text-destructive">
            {t.signInUnreachable}
          </p>
        )}
      </FullPageMessage>
    )
  }

  return (
    <FullPageMessage
      title={t.title}
      description={t.description}
      action={
        // Looks and sits like the language choice on Keycloak's sign-in page.
        <NativeSelect
          className="auth-language shrink-0"
          aria-label={t.language}
          value={language}
          onChange={(event) => chooseLanguage(event.target.value as Language)}
        >
          {LANGUAGES.map((option) => (
            <NativeSelectOption key={option.value} value={option.value}>
              {option.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      }
    >
      <div className="w-full space-y-4">
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div
                className="absolute -left-[10000px] h-px w-px overflow-hidden"
                aria-hidden="true"
            >
                <label htmlFor="website">Website</label>
                <input
                    id="website"
                    name="website"
                    type="text"
                    tabIndex={-1}
                    autoComplete="off"
                />
            </div>
          <div className="space-y-2">
            <Label htmlFor="companyName">{t.company}</Label>
            <Input
              id="companyName"
              value={values.companyName}
              onChange={(event) => updateField('companyName', event.target.value)}
              aria-invalid={Boolean(errors.companyName)}
              aria-describedby={errors.companyName ? 'companyName-error' : undefined}
            />
            {errors.companyName && (
              <p id="companyName-error" role="alert" className="text-sm text-destructive">
                {errors.companyName}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="adminName">{t.admin}</Label>
            <Input
              id="adminName"
              value={values.adminName}
              onChange={(event) => updateField('adminName', event.target.value)}
              aria-invalid={Boolean(errors.adminName)}
              aria-describedby={errors.adminName ? 'adminName-error' : undefined}
            />
            {errors.adminName && (
              <p id="adminName-error" role="alert" className="text-sm text-destructive">
                {errors.adminName}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="email">{t.email}</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={values.email}
              onChange={(event) => updateField('email', event.target.value)}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'email-error' : undefined}
            />
            {errors.email && (
              <p id="email-error" role="alert" className="text-sm text-destructive">
                {errors.email}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="vatNumber">{t.vat}</Label>
            <Input
              id="vatNumber"
              value={values.vatNumber}
              onChange={(event) => updateField('vatNumber', event.target.value)}
              autoCapitalize="characters"
              spellCheck={false}
              aria-invalid={Boolean(errors.vatNumber)}
              aria-describedby={errors.vatNumber ? 'vatNumber-error' : undefined}
            />
            {errors.vatNumber && (
              <p id="vatNumber-error" role="alert" className="text-sm text-destructive">
                {errors.vatNumber}
              </p>
            )}
          </div>
            <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? t.submitting : t.submit}
            </Button>

          {message && (
            <p role="status" className="text-center text-sm text-muted-foreground">
              {message}
            </p>
          )}
        </form>

        {signInLink}
      </div>
    </FullPageMessage>
  )
}
