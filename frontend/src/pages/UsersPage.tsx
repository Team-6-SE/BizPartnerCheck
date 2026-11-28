import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useRoles } from '@/auth/roles'
import { MailPlusIcon, RefreshCwIcon } from 'lucide-react'

import {
  deleteMember, inviteMember, listMembers, resendInvitation,
  updateMemberRole, updateMemberStatus, type Member, type UserRole,
} from '@/api/users'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

const roles: UserRole[] = ['org-admin', 'checker', 'reviewer']
const roleNames: Record<UserRole, string> = {
  'org-admin': 'Org Admin', checker: 'Checker', reviewer: 'Reviewer',
}
function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export function UsersPage() {
  const roleSet = useRoles()
  const isOrgAdmin = roleSet.has('org-admin')

  const [members, setMembers] = useState<Member[]>([])
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<UserRole>('checker')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setError('')
      setMembers(await listMembers())
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOrgAdmin) void load()
    else setLoading(false)
  }, [isOrgAdmin, load])

  async function act(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await action()
      setMessage(success)
      await load()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void act(async () => {
      await inviteMember(email, name, role)
      setEmail('')
      setName('')
    }, 'Invitation sent. The link expires after seven days.')
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Invite colleagues, manage their roles and control access to your organisation."
        actions={isOrgAdmin ? <Button disabled={busy} onClick={() => void load()}>
          <RefreshCwIcon data-icon="inline-start" /> Refresh
        </Button> : undefined}
      />
      {!isOrgAdmin ? <Card><CardContent className="py-6">
        Only organisation admins can manage users.
      </CardContent></Card> : <>
        <Card>
          <CardHeader><CardTitle>Invite user</CardTitle>
            <CardDescription>Send a seven-day email invitation through Keycloak.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitInvite} className="grid gap-3 md:grid-cols-4">
              <label className="grid gap-1 text-sm">Name
                <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} placeholder="Full name" />
              </label>
              <label className="grid gap-1 text-sm">Email
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={320} placeholder="colleague@company.at" />
              </label>
              <label className="grid gap-1 text-sm">Role
                <NativeSelect value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
                  {roles.map((value) => <NativeSelectOption key={value} value={value}>{roleNames[value]}</NativeSelectOption>)}
                </NativeSelect>
              </label>
              <div className="flex items-end"><Button disabled={busy} type="submit">
                <MailPlusIcon data-icon="inline-start" /> Invite user
              </Button></div>
            </form>
          </CardContent>
        </Card>
        {error && <div role="alert" className="rounded border border-red-300 p-3 text-sm text-red-700">{error}</div>}
        {message && <div role="status" className="rounded border p-3 text-sm">{message}</div>}
        <Card>
          <CardHeader><CardTitle>Members</CardTitle>
            <CardDescription>Users are limited to your organisation. The last active admin cannot be removed or demoted.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {loading ? <p>Loading members…</p> : members.length === 0 ? <p>No members found.</p> :
              members.map((member) => <MemberRow
                key={member.id}
                member={member}
                busy={busy}
                onAction={act}
              />)}
          </CardContent>
        </Card>
      </>}
    </div>
  )
}

function MemberRow({ member, busy, onAction }: {
  member: Member
  busy: boolean
  onAction: (action: () => Promise<unknown>, success: string) => Promise<void>
}) {
  const [selectedRole, setSelectedRole] = useState<UserRole>(member.role ?? 'checker')
  useEffect(() => setSelectedRole(member.role ?? 'checker'), [member.role])

  return <div className="grid gap-3 rounded-lg border p-4 lg:grid-cols-[minmax(160px,1fr)_160px_auto] lg:items-center">
    <div className="min-w-0">
      <div className="font-medium">{member.name || member.email}</div>
      <div className="truncate text-sm text-muted-foreground">{member.email}</div>
      <div className="text-xs text-muted-foreground">
        {member.enabled ? 'Active' : 'Deactivated'} · {member.email_verified ? 'Email verified' : 'Invitation pending'}
      </div>
    </div>
    <label className="grid gap-1 text-sm">Role
      <NativeSelect disabled={busy} value={selectedRole} onChange={(e) => setSelectedRole(e.target.value as UserRole)}>
        {roles.map((value) => <NativeSelectOption key={value} value={value}>{roleNames[value]}</NativeSelectOption>)}
      </NativeSelect>
    </label>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={busy || selectedRole === member.role}
        onClick={() => void onAction(() => updateMemberRole(member.id, selectedRole), 'Role updated.')}>Save role</Button>
      {!member.email_verified && <Button size="sm" variant="outline" disabled={busy}
        onClick={() => void onAction(() => resendInvitation(member.id), 'Invitation resent.')}>Resend</Button>}
      <Button size="sm" variant="outline" disabled={busy}
        onClick={() => void onAction(() => updateMemberStatus(member.id, !member.enabled), 'Account status updated.')}>
        {member.enabled ? 'Deactivate' : 'Activate'}
      </Button>
      <Button size="sm" variant="outline" disabled={busy}
        onClick={() => { if (window.confirm(`Remove ${member.email}? This cannot be undone.`)) void onAction(() => deleteMember(member.id), 'User removed.') }}>
        Remove
      </Button>
    </div>
  </div>
}
