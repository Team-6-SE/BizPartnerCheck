import { request } from '@/api/client'

export type UserRole = 'org-admin' | 'checker' | 'reviewer'

export type Member = {
  id: string
  email: string
  name: string
  role: UserRole | null
  enabled: boolean
  email_verified: boolean
}

export const listMembers = () => request<Member[]>('/users')
export const inviteMember = (email: string, name: string, role: UserRole) =>
  request<Member>('/users/invitations', {
    method: 'POST',
    body: JSON.stringify({ email, name, role }),
  })
export const updateMemberRole = (id: string, role: UserRole) =>
  request<Member>(`/users/${encodeURIComponent(id)}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
export const updateMemberStatus = (id: string, enabled: boolean) =>
  request<Member>(`/users/${encodeURIComponent(id)}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  })
export const deleteMember = (id: string) =>
  request<{ message: string }>(`/users/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const resendInvitation = (id: string) =>
  request<{ message: string }>(`/users/${encodeURIComponent(id)}/resend-invitation`, { method: 'POST' })
