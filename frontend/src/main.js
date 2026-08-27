import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { initTheme } from './utils/theme.js'
import { initPrefs } from './utils/prefs.js'
import { i18n } from './i18n.js'

initTheme()
initPrefs()
createApp(App).use(i18n).mount('#app')
