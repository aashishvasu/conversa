import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { initTheme } from './theme.js'
import { initPrefs } from './prefs.js'

initTheme()
initPrefs()
createApp(App).mount('#app')
