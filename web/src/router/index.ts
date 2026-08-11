import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/', redirect: { name: 'library' } },
  { path: '/sign-in', name: 'sign-in', component: () => import('@/views/SignInView.vue') },
  { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue') },
  {
    path: '/second-factor',
    name: 'second-factor',
    component: () => import('@/views/SecondFactorView.vue'),
  },
  {
    path: '/verify',
    name: 'verify-email',
    component: () => import('@/views/VerifyEmailView.vue'),
  },
  {
    // Where the desktop client's loginURL sends the browser.
    path: '/link',
    name: 'link-client',
    component: () => import('@/views/LinkClientView.vue'),
    meta: { requiresAuth: true },
  },
  {
    // The section is in the path rather than in component state, so that a
    // link can point at one -- "your keys are in settings" is a sentence that
    // wants a URL -- and so the browser's back button walks the sections the
    // way it walks everything else. Optional: `{ name: 'settings' }` from the
    // header still resolves, and the view falls back to the first section.
    path: '/settings/:section?',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    // The instance rather than a library: what it is running, what it costs,
    // and the policies that belong to whoever runs it. Sectioned in the path
    // for the same reasons settings is. Guarded twice — `requiresAdmin` here
    // so an ordinary account is not shown a screen of refusals, and the server
    // itself, which is where it actually matters.
    path: '/admin/:section?',
    name: 'admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
  },
  {
    // Where an emailed invitation lands. Deliberately not guarded: somebody
    // with no account here has to be able to read what they were asked to
    // join before deciding to make one.
    path: '/invitations',
    name: 'invitation',
    component: () => import('@/views/InvitationView.vue'),
  },
  {
    path: '/notifications',
    name: 'notifications',
    component: () => import('@/views/NotificationsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/groups',
    name: 'groups',
    component: () => import('@/views/GroupsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
    meta: { requiresAuth: true },
  },
  {
    // Somebody's published work. Deliberately unguarded: publishing something
    // here means anyone may read it, which is what the desktop client's wizard
    // promises and what `/users/<id>/publications/items` already does — see
    // `api/routes/webprofile.py` for the owner's own say in that.
    //
    // Under `/u/` rather than at `/<username>`, which is where zotero.org puts
    // it. A bare path would collide with this router's own names, so an
    // account called `settings` or `library` would have no page at all, and
    // every route added later would quietly claim a username. The prefix costs
    // two characters and cannot go wrong.
    //
    // `props: true` so the view takes the name as a parameter rather than
    // reading the route: it is the one thing the page is about.
    path: '/u/:username',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    props: true,
    // Not `requiresAuth`, but not a sign-in screen either: it is a page of
    // content and wants the application's own frame around it.
    meta: { shell: true },
  },
]

export const router = createRouter({
  // The application is served under /app/, so the history base has to match or
  // every in-app link resolves against the server root and hits the v3 API.
  history: createWebHistory('/app/'),
  routes,
})

router.beforeEach(async (to: RouteLocationNormalized) => {
  const auth = useAuthStore()

  // The cookie is checked once per load, before the first guarded route
  // decides anything -- otherwise a reload on /library bounces to sign-in for
  // as long as that request is in flight.
  if (!auth.ready) {
    await auth.restore()
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    if (auth.needsFactor) {
      return { name: 'second-factor' }
    }
    await auth.loadConfig()
    // A fresh instance has nobody to sign in as, so send the first visitor to
    // the form that can actually get them in.
    const destination = auth.registrationOpen ? 'register' : 'sign-in'
    return { name: destination, query: { next: to.fullPath } }
  }

  /* Signed in, but not for this. The library rather than the sign-in form:
     signing in again would not help, and the account already has a screen of
     its own to be on. */
  if (to.meta.requiresAdmin && auth.isAuthenticated && !auth.user?.administrator) {
    return { name: 'library' }
  }

  if ((to.name === 'sign-in' || to.name === 'register') && auth.isAuthenticated) {
    // Keeping `next` matters for the invitation link: somebody already signed
    // in who follows one would otherwise be dropped at the library with the
    // thing they came to answer nowhere in sight.
    return (to.query.next as string) || { name: 'library' }
  }

  return true
})
