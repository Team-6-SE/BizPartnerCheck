import { ChevronsUpDownIcon, KeyRoundIcon, LanguagesIcon, LogOutIcon } from 'lucide-react'
import { useAuth } from 'react-oidc-context'
import { Link, useLocation } from 'react-router'

import { ACCOUNT_URL, announceSignOut, signedOutPath } from '@/auth/oidc'

import { findNavItem, visibleNavigation } from '@/app/navigation'
import { useRoles } from '@/auth/roles'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'

function initials(name: string): string {
  const parts = name.split(/[\s@.]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

export function AppSidebar() {
  const auth = useAuth()
  const profile = auth.user?.profile
  const email = profile?.email ?? ''
  const name = profile?.name || [profile?.given_name, profile?.family_name].filter(Boolean).join(' ') || email
  const { pathname } = useLocation()
  // Same rule as the breadcrumb, so e.g. a check result keeps "History" active.
  const activeUrl = findNavItem(pathname)?.item.url
  const roles = useRoles()
  const navigation = visibleNavigation(roles)

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link to="/" />} tooltip="BizPartnerCheck">
              <img src="/favicon.svg" alt="" width={32} height={32} className="size-8 shrink-0" />
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="truncate font-heading font-semibold">BizPartnerCheck</span>
                <span className="truncate text-xs text-muted-foreground">Test organization</span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {navigation.map((group) => (
          <SidebarGroup key={group.title}>
            <SidebarGroupLabel>{group.title}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const active = item.url === activeUrl
                  return (
                    <SidebarMenuItem key={item.url}>
                      <SidebarMenuButton
                        render={<Link to={item.url} aria-current={active ? 'page' : undefined} />}
                        isActive={active}
                        tooltip={item.title}
                      >
                        <item.icon />
                        <span>{item.title}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <SidebarMenuButton
                    size="lg"
                    className="data-open:bg-sidebar-accent data-open:text-sidebar-accent-foreground"
                  />
                }
              >
                <Avatar className="size-8 rounded-lg">
                  <AvatarFallback className="rounded-lg">{initials(name)}</AvatarFallback>
                </Avatar>
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="truncate font-medium">{name}</span>
                  <span className="truncate text-xs text-muted-foreground">{email}</span>
                </span>
                <ChevronsUpDownIcon className="ml-auto" />
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="min-w-56">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="truncate">{email}</DropdownMenuLabel>
                  <DropdownMenuItem
                    render={<a href={ACCOUNT_URL} target="_blank" rel="noopener noreferrer" />}
                  >
                    <KeyRoundIcon />
                    Account and Password
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => {
                      announceSignOut('signed_out')
                      auth.signoutRedirect().catch(() => {
                        // Keycloak not reachable: at least leave the app in this browser.
                        window.location.replace(signedOutPath('signed_out'))
                      })
                    }}
                  >
                    <LogOutIcon />
                    Sign Out
                  </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem disabled>
                    <LanguagesIcon />
                    Deutsch / English
                    <DropdownMenuShortcut>Soon</DropdownMenuShortcut>
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
