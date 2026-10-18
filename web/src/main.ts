import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { i18n, loadLocale, resolveLocale } from './i18n'
import { router } from './router'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/dialog.css'

// The catalogue the browser most likely wants is fetched before the first
// paint, so the page does not appear in English and then change. The account
// may still choose another once the session is known.
const guessed = resolveLocale(null, navigator.languages ?? [navigator.language])
const app = createApp(App).use(createPinia()).use(i18n).use(router)
void loadLocale(guessed)
  .catch(() => undefined)
  .finally(() => app.mount('#app'))
