import { useId } from 'react'
import { InfoIcon, SearchCheckIcon } from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

// Typical trade licences; the real list comes from the organization presets later.
const LICENCES = ['Baumeister', 'Elektrotechnik', 'Installateur', 'Dachdecker']

export function NewCheckPage() {
  const id = useId()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="New Check"
        description="Check a business partner against all public sources in one step."
        comingSoon
      />

      <Alert>
        <InfoIcon />
        <AlertTitle>Not Available Yet</AlertTitle>
        <AlertDescription>
          This form shows what a check will ask for. Running checks comes with the VIES check and the
          other sources.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Partner</h2>
          </CardTitle>
          <CardDescription>One identifier is enough; the others are found automatically.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => event.preventDefault()}>
            <FieldGroup>
              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-identifier`}>VAT Number, Company Register Number, GISA Number or Name</FieldLabel>
                <Input
                  id={`${id}-identifier`}
                  placeholder="ATU12345678, 123456a, …"
                  className="font-mono"
                  disabled
                />
              </Field>

              <FieldSet data-disabled>
                <FieldLegend variant="label">Required Licences</FieldLegend>
                <FieldDescription>The partner must hold these business licences (GISA).</FieldDescription>
                <div className="grid gap-3 sm:grid-cols-2">
                  {LICENCES.map((licence) => (
                    <Field key={licence} orientation="horizontal" data-disabled>
                      <Checkbox id={`${id}-${licence}`} disabled />
                      <FieldLabel htmlFor={`${id}-${licence}`} className="font-normal">
                        {licence}
                      </FieldLabel>
                    </Field>
                  ))}
                </div>
              </FieldSet>

              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-reference`}>Reference (Optional)</FieldLabel>
                <Input id={`${id}-reference`} placeholder="Contract number…" disabled />
              </Field>

              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-comment`}>Comment (Optional)</FieldLabel>
                <Textarea id={`${id}-comment`} disabled />
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
        <CardFooter className="justify-end">
          <Button disabled>
            <SearchCheckIcon data-icon="inline-start" />
            Run Check
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
