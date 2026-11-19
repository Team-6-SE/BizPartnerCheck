import { ArrowRightIcon, HistoryIcon } from 'lucide-react'

import type { RunChange } from '@/api/check-runs'
import { changeText, labelsFor, sourceName } from '@/lib/check-results'

/** Under one source's result: shown only if its status changed in the last run (S5.3). */
export function ChangedSince({ changes, source }: { changes: RunChange[]; source: string }) {
  const change = changes.find((item) => item.source.toUpperCase() === source.toUpperCase())
  if (!change) return null
  return (
    <p className="mt-1 flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
      <HistoryIcon aria-hidden className="size-3" />
      Changed since the last check: {changeText(change)}
    </p>
  )
}

/** Summary after a re-run on the partner page: what changed, or that nothing did. */
export function RunChangesSummary({ changes }: { changes: RunChange[] }) {
  if (changes.length === 0) {
    return <p className="text-sm text-muted-foreground">No changes since the previous check.</p>
  }
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
      <p className="font-medium text-amber-900 dark:text-amber-200">Changed since the previous check</p>
      <ul className="mt-1 flex flex-col gap-1">
        {changes.map((change) => (
          <li key={change.source} className="flex items-center gap-2 text-amber-900 dark:text-amber-200">
            <span className="font-medium">{sourceName(change.source)}:</span>
            {labelsFor(change.source)[change.previous_status]}
            <ArrowRightIcon aria-hidden className="size-3" />
            {labelsFor(change.source)[change.status]}
          </li>
        ))}
      </ul>
    </div>
  )
}
