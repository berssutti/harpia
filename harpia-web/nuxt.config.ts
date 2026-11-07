import { defineNuxtConfig } from 'nuxt/config'

export default defineNuxtConfig({
  compatibilityDate: '2024-04-03',
  css: ['~/assets/css/main.css'],
  devtools: { enabled: false },
  runtimeConfig: {
    // Server-only values. Overridden at runtime by NUXT_BACKEND_URL,
    // NUXT_API_KEY, NUXT_UI_USER and NUXT_UI_PASSWORD.
    backendUrl: 'http://harpia-backend:8000',
    apiKey: '',
    uiUser: '',
    uiPassword: '',
    public: {
      // Same-origin Nitro proxy; the browser never talks to the API directly.
      apiBase: '/api'
    }
  }
})
