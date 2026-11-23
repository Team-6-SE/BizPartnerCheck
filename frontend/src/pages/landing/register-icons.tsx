/* Solid, coloured icons of the registers, drawn like the ones in the reference picture. */
import { useId, type SVGProps } from 'react'

/** The flag of the EU in a circle, for VIES. */
export function EuFlagIcon(props: SVGProps<SVGSVGElement>) {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <defs>
        <radialGradient id={id} cx="35%" cy="30%" r="80%">
          <stop offset="0" stopColor="#5a5ff0" />
          <stop offset="1" stopColor="#262aa8" />
        </radialGradient>
      </defs>
      <circle cx="12" cy="12" r="11" fill={`url(#${id})`} />
      {Array.from({ length: 12 }, (_, i) => {
        const angle = (i / 12) * Math.PI * 2
        return <circle key={i} cx={12 + Math.cos(angle) * 6.4} cy={12 + Math.sin(angle) * 6.4} r={0.95} fill="#ffd84d" />
      })}
    </svg>
  )
}

/** A ministry building, for the BMF. */
export function MinistryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="#1d2270" aria-hidden="true" {...props}>
      <path d="M12 1.8 22.2 7v2.3H1.8V7Z" />
      <circle cx="12" cy="6.4" r="1.15" fill="#e9ebff" />
      {[4.6, 8.7, 12.8, 16.9].map((x) => (
        <rect key={x} x={x} y="10.6" width="2.5" height="7.4" rx="0.4" />
      ))}
      <rect x="1.8" y="19.2" width="20.4" height="2.8" rx="0.6" />
    </svg>
  )
}

/** Rising bars, for the GISA register. */
export function BarsIcon(props: SVGProps<SVGSVGElement>) {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#7482ff" />
          <stop offset="1" stopColor="#2b34c4" />
        </linearGradient>
      </defs>
      <g fill={`url(#${id})`}>
        <rect x="3" y="14" width="4.6" height="8" rx="1.1" />
        <rect x="9.7" y="9" width="4.6" height="13" rx="1.1" />
        <rect x="16.4" y="3" width="4.6" height="19" rx="1.1" />
      </g>
      <g fill="#ffffff" opacity="0.45">
        <rect x="3.6" y="14.6" width="1.3" height="6.8" rx="0.6" />
        <rect x="10.3" y="9.6" width="1.3" height="11.8" rx="0.6" />
        <rect x="17" y="3.6" width="1.3" height="17.8" rx="0.6" />
      </g>
    </svg>
  )
}

/** A document, for the VAT number. */
export function DocumentIcon(props: SVGProps<SVGSVGElement>) {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={id} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#6573ff" />
          <stop offset="1" stopColor="#2a33c2" />
        </linearGradient>
      </defs>
      <path d="M6 1.8h8.2L20 7.6v12.6A2 2 0 0 1 18 22.2H6a2 2 0 0 1-2-2V3.8a2 2 0 0 1 2-2Z" fill={`url(#${id})`} />
      <path d="M14.2 1.8v4.3a1.5 1.5 0 0 0 1.5 1.5H20Z" fill="#a9b2ff" />
      <g stroke="#ffffff" strokeWidth="1.5" strokeLinecap="round" opacity="0.9">
        <path d="M7.6 11.6h8.8M7.6 15h8.8M7.6 18.4h5.4" />
      </g>
    </svg>
  )
}

/** A hard hat, for the HFU list (construction). */
export function HardHatIcon(props: SVGProps<SVGSVGElement>) {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#6d7bff" />
          <stop offset="1" stopColor="#2b34c4" />
        </linearGradient>
      </defs>
      <path d="M4 16.2a8 8 0 0 1 16 0Z" fill={`url(#${id})`} />
      <path d="M10.4 4.6h3.2l.9 7.2H9.5Z" fill="#a9b2ff" />
      <rect x="2" y="16" width="20" height="3.6" rx="1.4" fill="#1d2270" />
    </svg>
  )
}

/** A bound register, for the Firmenbuch. */
export function BookIcon(props: SVGProps<SVGSVGElement>) {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={id} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#6573ff" />
          <stop offset="1" stopColor="#2a33c2" />
        </linearGradient>
      </defs>
      <path d="M5 3.2A2.2 2.2 0 0 1 7.2 1.8H19v16.4H7.2A2.2 2.2 0 0 0 5 19.6Z" fill={`url(#${id})`} />
      <path d="M5 19.6a2.2 2.2 0 0 1 2.2-1.4H19v4H7.2A2.2 2.2 0 0 1 5 19.6Z" fill="#c9cfff" />
      <rect x="9" y="6" width="7" height="1.6" rx="0.8" fill="#ffffff" opacity="0.85" />
      <rect x="9" y="9.2" width="5" height="1.6" rx="0.8" fill="#ffffff" opacity="0.6" />
    </svg>
  )
}
