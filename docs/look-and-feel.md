# Look and feel

## Theme

- **Light is the default** everywhere (app, sign-in pages of Keycloak, landing page). Before, the app followed the
  system setting, so many people got dark without choosing it.
- **Settings → Appearance:** Light, Dark or System (follows the device and changes with it).
- The choice is stored per browser (`localStorage`, key `bizpartnercheck.theme`), not on the server: it is a
  preference of the device, and it must apply before sign-in. `initTheme()` in `main.tsx` sets it before the first
  render, so the page never flashes in the wrong theme. Code: `src/lib/theme.ts`,
  `src/components/appearance-settings.tsx`.
- Colours: indigo primary on cool greys (tokens in `src/index.css`), the same in the Keycloak theme
  (`infra/keycloak/themes/bizpartnercheck/login/resources/css/bizpartnercheck.css`, `darkMode=false`).

## Moving between pages

The app is a single-page app: moving between pages never reloaded the page (only sign-in and sign-out leave the
app for Keycloak and come back, which cannot be avoided). What made it feel like a reload was the content
switching at once, sometimes after a short loading gap.

- **Inside the app, a quick switch:** only the page content (`#main`) fades over and moves up 6 px (about
  0.2 s); sidebar and header stay where they are. Pages are switched many times a day, so the animation is
  short and quiet.
- **Between the public pages, a curtain:** from the landing page to the registration and between sign-in,
  registration and landing page, a curtain in the accent colour rises from the bottom with an arched top
  edge, covers the screen, the page changes behind it, and the curtain moves on upwards and uncovers the new
  page from below (0.8 s; the middle of the arch leads, the sides trail).
- How: links use React Router's `viewTransition`, which uses the browser's View Transitions API; navigations
  without it (redirects, filters in the URL) switch at once. `viewTransition` only works with a data router,
  so the app uses `createBrowserRouter` + `RouterProvider` (`App.tsx`); with the former `<BrowserRouter>` the
  option was silently ignored. The rest is CSS (`index.css`): `:root:has(#main)` tells the app (quick switch)
  from the public pages (curtain). For the curtain, the old page is hidden below the arch with a mask, the new
  page shown below it with a `clip-path`, and the curtain is the background between them.
- With "reduce motion" the new page only fades in (140 ms). Browsers without the API switch at once.
- **No loading gap:** the pages are separate chunks; once the app is idle they are all loaded in the background
  (`usePreloadPages` in `AppLayout.tsx`), so a click shows the page at once.

## Layout

- Content is up to 1280 px wide (`max-w-7xl`), so tables and cards use wide screens.
- The sidebar is 17 rem wide, with 18 px icons and 15 px text. Menu items have 4 px between them and hover is
  lighter than the active page, so a hovered item next to the active one never reads as one block.
- The partner table fits a 1440 px screen with the sidebar: result columns are at least 144 px wide and dates wrap
  onto a second line instead of pushing the **Check** button out of sight.
