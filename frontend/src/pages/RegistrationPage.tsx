import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError } from '@/api/client'

import { FullPageMessage } from '@/components/full-page-message'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Language = 'en' | 'de'

type FormValues = {
  companyName: string
  adminName: string
  email: string
  vatNumber: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const translations = {
  en: {
    title: 'Create Your Account',
    description: 'Register your company and start checking business partners.',
    company: 'Company name',
    admin: 'Administrator name',
    email: 'Email address',
    vat: 'VAT number (optional)',
    submit: 'Create Account',
    signIn: 'Already have an account? Sign in',
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
    signIn: 'Sie haben bereits ein Konto? Anmelden',
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
  const [language, setLanguage] = useState<Language>('en')
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
}
  const [errors, setErrors] = useState<FormErrors>({})
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const t = translations[language]

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

      if (detail?.code === 'email_already_registered') {
        throw new ApiError(t.duplicateEmail, response.status, detail.code)
      }

      throw new ApiError(
        detail?.message || t.registrationError,
        response.status,
        detail?.code,
      )
    }

    setMessage(t.success)
  } catch (error) {
    setMessage(
      error instanceof ApiError ? error.message : t.registrationError,
    )
  } finally {
    setSubmitting(false)
  }
}

  return (
    <FullPageMessage title={t.title} description={t.description}>
      <div className="w-full space-y-4">
        <div className="flex items-center justify-end gap-2 text-sm">
          <span>{t.language}:</span>
          <button
            type="button"
            onClick={() => setLanguage('en')}
            aria-pressed={language === 'en'}
            className={language === 'en' ? 'font-bold underline' : 'hover:underline'}
          >
            English
          </button>
          <span aria-hidden="true">|</span>
          <button
            type="button"
            onClick={() => setLanguage('de')}
            aria-pressed={language === 'de'}
            className={language === 'de' ? 'font-bold underline' : 'hover:underline'}
          >
            Deutsch
          </button>
        </div>

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
            />
          </div>
            <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? 'Submitting...' : t.submit}
            </Button>

          {message && (
            <p role="status" className="text-center text-sm text-muted-foreground">
              {message}
            </p>
          )}
        </form>

        <p className="text-center text-sm">
          <Link to="/sign-in" className="underline underline-offset-4 hover:text-primary">
            {t.signIn}
          </Link>
        </p>
      </div>
    </FullPageMessage>
  )
}