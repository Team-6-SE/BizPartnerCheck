import { request } from './client'

/** The signed-in user's organisation (backend: app/organization/router.py). */
export type Organization = {
  id: string
  name: string
  /** Own VAT number, sent to VIES as the requester; null until an admin sets it. */
  vat_number: string | null
}

export function getOrganization(signal?: AbortSignal): Promise<Organization> {
  return request<Organization>('/organization', { signal })
}

/** Org admins only. An empty value removes the number. */
export function updateOrganizationVatNumber(vatNumber: string): Promise<Organization> {
  return request<Organization>('/organization', {
    method: 'PUT',
    body: JSON.stringify({ vat_number: vatNumber.trim() || null }),
  })
}
