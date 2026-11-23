import { useEffect, useRef, useState, type ComponentType, type SVGProps } from 'react'
import {
  ArrowRightIcon,
  CircleCheckIcon,
  EyeOffIcon,
  FileClockIcon,
  LockKeyholeIcon,
  SmartphoneIcon,
} from 'lucide-react'
import { Link } from 'react-router'

import { signIn } from '@/auth/oidc'

import { GlassCube, Hero } from './hero'
import { BarsIcon, BookIcon, EuFlagIcon, HardHatIcon, MinistryIcon } from './register-icons'

import './landing.css'

type Icon = ComponentType<SVGProps<SVGSVGElement>>

type Source = {
  id: string
  name: string
  short: string
  owner: string
  question: string
  icon: Icon
}

/** The registers BizPartnerCheck asks, in the order of a check. */
const SOURCES: Source[] = [
  {
    id: 'vies',
    name: 'VIES',
    short: 'VIES',
    owner: 'European Commission',
    question: 'Is the VAT number valid, and which name and address are registered for it?',
    icon: EuFlagIcon,
  },
  {
    id: 'bmf',
    name: 'BMF list of fake companies',
    short: 'BMF',
    owner: 'Austrian Ministry of Finance',
    question: 'Is the partner on the official list of shell companies (Scheinunternehmen)?',
    icon: MinistryIcon,
  },
  {
    id: 'hfu',
    name: 'HFU list',
    short: 'HFU',
    owner: 'Austrian Health Insurance Fund (ÖGK)',
    question: 'Is the partner on the HFU list, so that you are not liable for its social insurance contributions?',
    icon: HardHatIcon,
  },
  {
    id: 'firmenbuch',
    name: 'Firmenbuch',
    short: 'Firmenbuch',
    owner: 'Austrian Ministry of Justice',
    question: 'Does the company exist, is it still active, and who manages it?',
    icon: BookIcon,
  },
  {
    id: 'gisa',
    name: 'GISA',
    short: 'GISA',
    owner: 'Austrian Ministry of Economy',
    question: 'Which trade licences does the partner hold, and are they active?',
    icon: BarsIcon,
  },
]

const PREVIEW: { source: string; result: string }[] = [
  { source: 'VIES', result: 'Valid' },
  { source: 'BMF list', result: 'Not listed' },
  { source: 'HFU list', result: 'Listed' },
  { source: 'Firmenbuch', result: 'Registered' },
  { source: 'GISA', result: 'Active licence' },
]

/** True once the element has been on screen (for reveals that run only once). */
function useSeenOnce<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element || seen) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true)
          observer.disconnect()
        }
      },
      { rootMargin: '0px 0px -15% 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [seen])
  return [ref, seen]
}

/** The preview "runs" a check: one register answers after the other. */
function CheckPreview() {
  const [ref, seen] = useSeenOnce<HTMLElement>()
  const [ticked, setTicked] = useState(0)
  // Without motion the answers are simply there.
  const answered = seen && prefersReducedMotion() ? PREVIEW.length : ticked
  useEffect(() => {
    if (!seen || prefersReducedMotion()) return
    const timers = PREVIEW.map((_, index) => window.setTimeout(() => setTicked(index + 1), 500 + index * 420))
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [seen])

  return (
    <figure ref={ref} className="lp-preview" aria-label="Example result of a check">
      <div className="lp-preview-head">
        <span className="lp-preview-name">Muster Bau GmbH</span>
        <span className="lp-preview-ids">ATU12345678 / FN 123456a</span>
      </div>
      <ul className="lp-preview-rows">
        {PREVIEW.map((row, index) => (
          <li key={row.source} className="lp-preview-row">
            <span className="lp-preview-source">{row.source}</span>
            {index < answered ? (
              <span className="lp-result">{row.result}</span>
            ) : (
              <span className="lp-pending">
                <i aria-hidden="true" />
                Checking
              </span>
            )}
          </li>
        ))}
      </ul>
      <figcaption className="lp-preview-foot">Checked today at 09:41. Example data.</figcaption>
    </figure>
  )
}

function clamp(min: number, value: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * Scroll progress through a tall section (0 when its top reaches the top of the window, 1 when
 * its end does), written as --p. The sticky layout is only switched on here, so without
 * JavaScript or with reduced motion the section is a normal, fully visible block.
 */
function useScrollProgress<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useEffect(() => {
    const element = ref.current
    if (!element || prefersReducedMotion()) return
    let frame = 0
    const update = () => {
      frame = 0
      const rect = element.getBoundingClientRect()
      const range = rect.height - window.innerHeight
      const progress = range > 0 ? clamp(0, -rect.top / range, 1) : 1
      element.style.setProperty('--p', progress.toFixed(4))
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    element.dataset.scroll = 'on'
    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      delete element.dataset.scroll
    }
  }, [])
  return ref
}

const STATEMENT = 'Check everything in one click'

const STATEMENT_REGISTERS = [
  { name: 'VIES', icon: EuFlagIcon },
  { name: 'BMF list', icon: MinistryIcon },
  { name: 'HFU list', icon: HardHatIcon },
  { name: 'Firmenbuch', icon: BookIcon },
  { name: 'GISA', icon: BarsIcon },
]

/**
 * The first section after the hero tells the product in one sentence, driven by the scroll:
 * the sentence lights up word by word, the five registers come in, a click on "Check" sends a
 * signal along them and each one answers.
 */
function Statement() {
  const ref = useScrollProgress<HTMLElement>()
  const words = STATEMENT.split(' ')
  return (
    <section
      ref={ref}
      id="about"
      className="lp-statement"
      aria-labelledby="about-title"
      style={{ '--n': words.length } as React.CSSProperties}
    >
      <div className="lp-statement-stage">
        <div className="lp-inner lp-intro">
          <h2 id="about-title" className="lp-display" aria-label={STATEMENT}>
            {words.map((word, index) => (
              <span key={index} aria-hidden="true">
                <span className="lp-word" style={{ '--i': index } as React.CSSProperties}>
                  {word}
                </span>{' '}
              </span>
            ))}
          </h2>
          <p className="lp-lead lp-statement-lead">
            Before you sign a contract or order work, BizPartnerCheck asks the EU VAT database and the Austrian
            authorities about your partner. You get <strong>one clear answer per register</strong>, with the time of
            the check, and you can show it later.
          </p>
        </div>

        <div className="lp-inner">
          <div className="lp-run" aria-hidden="true">
            <span className="lp-run-check">
              <CircleCheckIcon />
              Check
            </span>
            <span className="lp-run-track" />
            <ul className="lp-run-registers">
              {STATEMENT_REGISTERS.map((register, index) => (
                <li key={register.name} className="lp-run-register" style={{ '--i': index } as React.CSSProperties}>
                  <register.icon />
                  {register.name}
                  <i className="lp-run-dot" />
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  )
}

function SourceList() {
  const [ref, seen] = useSeenOnce<HTMLUListElement>()
  return (
    <ul ref={ref} className="lp-sources" data-shown={seen}>
      {SOURCES.map((source, index) => (
        <li key={source.id} className="lp-source" style={{ '--i': index } as React.CSSProperties}>
          <span className="lp-source-icon">
            <source.icon />
          </span>
          <p className="lp-source-name">
            {source.name}
            <span className="lp-source-owner">{source.owner}</span>
          </p>
          <p className="lp-source-question">{source.question}</p>
        </li>
      ))}
    </ul>
  )
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const TRUST: { title: string; text: string; icon: Icon }[] = [
  {
    title: 'Your partners stay yours',
    text: 'Every organisation sees only its own partners and results. Others get no access, not even to the fact that a partner exists.',
    icon: LockKeyholeIcon,
  },
  {
    title: 'Two-step sign-in',
    text: 'Accounts are protected by a password and an authenticator app. Every sign-in is written to your security log.',
    icon: SmartphoneIcon,
  },
  {
    title: 'Results you can show later',
    text: 'Each result keeps the time of the check, the source and what the source answered, so you can prove the check happened.',
    icon: FileClockIcon,
  },
  {
    title: 'Only what the check needs',
    text: 'For managing directors and owners we keep the name and the role. Birth dates and private addresses are not stored.',
    icon: EyeOffIcon,
  },
]

export function LandingPage() {
  const [signInFailed, setSignInFailed] = useState(false)
  const startSignIn = () => {
    setSignInFailed(false)
    signIn('/').catch(() => setSignInFailed(true))
  }

  return (
    <div className="landing">
      <title>BizPartnerCheck: check business partners in one click</title>
      <Hero />
      {signInFailed && (
        <p role="alert" className="fixed top-20 right-6 z-50 rounded-xl bg-white px-4 py-3 text-sm text-red-700 shadow-lg">
          The sign-in service cannot be reached right now. Please try again in a moment.
        </p>
      )}

      <main>
        <Statement />

        <section className="lp-section" style={{ paddingTop: 0 }} aria-labelledby="sources-title">
          <div className="lp-inner">
            <h2 id="sources-title" className="lp-h2">
              What we ask, and where
            </h2>
            <SourceList />
          </div>
        </section>

        <section className="lp-section" aria-labelledby="how-title">
          <div className="lp-inner lp-how">
            <div>
              {/* Not shown: the steps and the example speak for themselves; screen readers keep the heading. */}
              <h2 id="how-title" className="sr-only">
                From sign-up to a checked partner in minutes
              </h2>
              <ol className="lp-steps">
                <li className="lp-step">
                  <span className="lp-step-number">1</span>
                  <div>
                    <h3>Register your company</h3>
                    <p>Confirm your e-mail address, set a password and connect an authenticator app.</p>
                  </div>
                </li>
                <li className="lp-step">
                  <span className="lp-step-number">2</span>
                  <div>
                    <h3>Add your partners</h3>
                    <p>By VAT number, by company register number (FN) or both. The format is checked as you type.</p>
                  </div>
                </li>
                <li className="lp-step">
                  <span className="lp-step-number">3</span>
                  <div>
                    <h3>Check with one click</h3>
                    <p>All registers are asked at once. Each answer shows what it means and what to do next.</p>
                  </div>
                </li>
              </ol>
            </div>

            <CheckPreview />
          </div>
        </section>

        <section className="lp-section" style={{ paddingTop: 0 }} aria-labelledby="trust-title">
          <div className="lp-inner">
            <h2 id="trust-title" className="lp-h2">
              Made to hold up when someone asks
            </h2>
            <div className="lp-trust">
              {TRUST.map((item) => (
                <div key={item.title} className="lp-trust-item">
                  <item.icon aria-hidden="true" />
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-closing" aria-labelledby="closing-title">
          <div className="lp-inner">
            <div className="lp-mini-cube" aria-hidden="true">
              <div className="lp-cube-anchor">
                <GlassCube />
              </div>
            </div>
            <h2 id="closing-title" className="lp-h2">
              Start with your first partner
            </h2>
            <p className="lp-lead">Registration takes two minutes. You need your company name and an e-mail address.</p>
            <div className="lp-closing-actions">
              <Link to="/register" viewTransition className="lp-cta">
                Register your company
                <ArrowRightIcon aria-hidden="true" />
              </Link>
              <button type="button" className="lp-link-button" style={{ height: 58, padding: '0 28px' }} onClick={startSignIn}>
                Sign in
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">BizPartnerCheck is a student project of Team 6 at IMC Krems, 2026.</footer>
    </div>
  )
}
