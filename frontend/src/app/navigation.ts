import {
  Building2Icon,
  HistoryIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  type LucideIcon,
  ScrollTextIcon,
  SearchCheckIcon,
  Settings2Icon,
  ShieldIcon,
  UsersIcon,
} from 'lucide-react'

import { ORG_ADMIN_ROLE } from '@/auth/roles'

export type NavItem = {
  title: string
  url: string
  icon: LucideIcon
  /** Only exact match marks the item active (for "/"). */
  end?: boolean
  /** Shown only to users with this Keycloak role (the backend checks it again). */
  role?: string
}

export type NavGroup = {
  title: string
  items: NavItem[]
}

/** All screens of the web app (SRS 3.1.1). "Partners" and "Security Log" work so far. */
export const navigation: NavGroup[] = [
  {
    title: 'Checks',
    items: [
      { title: 'Dashboard', url: '/', icon: LayoutDashboardIcon, end: true },
      { title: 'New Check', url: '/checks/new', icon: SearchCheckIcon },
      { title: 'History', url: '/checks', icon: HistoryIcon, end: true },
    ],
  },
  {
    title: 'Partners',
    items: [{ title: 'Partners', url: '/partners', icon: Building2Icon }],
  },
  {
    title: 'Organization',
    items: [
      { title: 'API Tokens', url: '/settings/api-tokens', icon: KeyRoundIcon },
      { title: 'Users', url: '/settings/users', icon: UsersIcon },
      { title: 'Settings', url: '/settings/organization', icon: Settings2Icon },
      { title: 'Security Log', url: '/settings/security-log', icon: ScrollTextIcon, role: ORG_ADMIN_ROLE },
    ],
  },
  {
    title: 'Platform',
    items: [{ title: 'Organizations', url: '/admin/organizations', icon: ShieldIcon }],
  },
]

/** The menu for a user with these roles (groups without visible items are left out). */
export function visibleNavigation(roles: ReadonlySet<string>): NavGroup[] {
  return navigation
    .map((group) => ({ ...group, items: group.items.filter((item) => !item.role || roles.has(item.role)) }))
    .filter((group) => group.items.length > 0)
}

export function isActive(item: NavItem, pathname: string): boolean {
  if (item.end) return pathname === item.url
  return pathname === item.url || pathname.startsWith(`${item.url}/`)
}

/** Group and item for the current URL, used for the breadcrumb. */
export function findNavItem(pathname: string): { group: NavGroup; item: NavItem } | null {
  // "/checks/123" (check result) belongs to History.
  const path = /^\/checks\/(?!new$)[^/]+$/.test(pathname) ? '/checks' : pathname
  for (const group of navigation) {
    for (const item of group.items) {
      if (isActive(item, path)) return { group, item }
    }
  }
  return null
}
