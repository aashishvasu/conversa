import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { initTheme } from './utils/theme.js'
import { initPrefs } from './utils/prefs.js'

initTheme()
initPrefs()
createApp(App).mount('#app')
