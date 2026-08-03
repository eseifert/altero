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
    path: '/library',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
    meta: { requiresAuth: true },
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

  if ((to.name === 'sign-in' || to.name === 'register') && auth.isAuthenticated) {
    return { name: 'library' }
  }

  return true
})
