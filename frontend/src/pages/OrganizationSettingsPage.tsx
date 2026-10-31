import { useId } from 'react'

import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

export function OrganizationSettingsPage() {
  const id = useId()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Details of your organization that every check uses."
        comingSoon
      />
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Organization</h2>
          </CardTitle>
          <CardDescription>Only org admins can change these settings.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => event.preventDefault()}>
            <FieldGroup>
              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-name`}>Name</FieldLabel>
                <Input id={`${id}-name`} defaultValue="Test organization" disabled />
              </Field>
              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-vat`}>Own VAT Number</FieldLabel>
                <Input id={`${id}-vat`} placeholder="ATU12345678…" className="font-mono" disabled />
                <FieldDescription>Sent to VIES with every VAT check, as the requester.</FieldDescription>
              </Field>
              <Field data-disabled>
                <FieldLabel htmlFor={`${id}-licences`}>Licence Presets</FieldLabel>
                <Input id={`${id}-licences`} placeholder="Baumeister, Elektrotechnik…" disabled />
                <FieldDescription>Licences that are pre-selected when you start a new check.</FieldDescription>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
        <CardFooter className="justify-end">
          <Button disabled>Save Changes</Button>
        </CardFooter>
      </Card>
    </div>
  )
}
