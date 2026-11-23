import { MonitorIcon, MoonIcon, SunIcon, type LucideIcon } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { setTheme, useTheme, type Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const OPTIONS: { value: Theme; label: string; hint: string; icon: LucideIcon }[] = [
  { value: 'light', label: 'Light', hint: 'Default', icon: SunIcon },
  { value: 'dark', label: 'Dark', hint: 'Easier at night', icon: MoonIcon },
  { value: 'system', label: 'System', hint: 'Like your device', icon: MonitorIcon },
]

/** Light, dark or like the device. Saved in this browser only. */
export function AppearanceSettings() {
  const theme = useTheme()
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Appearance</h2>
        </CardTitle>
        <CardDescription>How BizPartnerCheck looks in this browser.</CardDescription>
      </CardHeader>
      <CardContent>
        <fieldset>
          <legend className="sr-only">Theme</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {OPTIONS.map((option) => {
              const selected = theme === option.value
              return (
                <label
                  key={option.value}
                  className={cn(
                    'relative flex cursor-pointer items-center gap-3 rounded-xl border bg-card p-4 transition-[border-color,background-color,transform] duration-150 ease-out active:scale-[0.98]',
                    'has-focus-visible:ring-3 has-focus-visible:ring-ring/40',
                    selected ? 'border-primary bg-primary/5' : 'hover:bg-muted/60',
                  )}
                >
                  <input
                    type="radio"
                    name="theme"
                    value={option.value}
                    checked={selected}
                    onChange={() => setTheme(option.value)}
                    className="sr-only"
                  />
                  <span
                    className={cn(
                      'grid size-10 shrink-0 place-items-center rounded-lg',
                      selected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                    )}
                  >
                    <option.icon aria-hidden className="size-5" />
                  </span>
                  <span className="flex flex-col">
                    <span className="font-medium">{option.label}</span>
                    <span className="text-sm text-muted-foreground">{option.hint}</span>
                  </span>
                </label>
              )
            })}
          </div>
        </fieldset>
      </CardContent>
    </Card>
  )
}
