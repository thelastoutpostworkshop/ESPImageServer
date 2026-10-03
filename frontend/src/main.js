import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import App from './App.vue'
import { loadThemePreference } from './themePreference.js'
import './style.css'

createApp(App).use(createVuetify({ theme: { defaultTheme: loadThemePreference() } })).mount('#app')
