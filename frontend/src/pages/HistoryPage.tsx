import { useId } from 'react'
import { HistoryIcon } from 'lucide-react'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

export function HistoryPage() {
  const id = useId()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="History"
        description="All check runs of your organization, newest first. Stored runs cannot be changed."
        comingSoon
      />

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Check Runs</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field data-disabled>
              <FieldLabel htmlFor={`${id}-partner`}>Partner</FieldLabel>
              <Input id={`${id}-partner`} placeholder="Name or VAT number…" disabled />
            </Field>
            <Field data-disabled>
              <FieldLabel htmlFor={`${id}-from`}>From</FieldLabel>
              <Input id={`${id}-from`} type="date" disabled />
            </Field>
            <Field data-disabled>
              <FieldLabel htmlFor={`${id}-reference`}>Reference</FieldLabel>
              <Input id={`${id}-reference`} placeholder="Contract number…" disabled />
            </Field>
          </div>
          <ComingSoon
            icon={HistoryIcon}
            title="No Check Runs Yet"
            description="Every check will be stored here with its evidence and can be downloaded as a PDF report."
          />
        </CardContent>
      </Card>
    </div>
  )
}
