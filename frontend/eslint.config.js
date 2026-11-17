import vueI18n from '@intlify/eslint-plugin-vue-i18n'
import vueParser from 'vue-eslint-parser'

export default [
  ...vueI18n.configs['flat/base'],
  {
    files: ['src/**/*.vue'],
    languageOptions: { parser: vueParser },
    rules: { '@intlify/vue-i18n/no-raw-text': ['error', { ignoreText: ['conversa', '…', '(', ')', '✕', '·', 'q', '↺'] }] },
    settings: { 'vue-i18n': { localeDir: './src/locales/*.json', messageSyntaxVersion: '^11.0.0' } },
  },
  {
    //  ChatPane persists a run; research/coordinator.js starts it. tools/check.py gates this rule through pnpm lint:i18n.
    files: ['src/views/ChatPane.vue'],
    rules: { 'no-restricted-imports': ['error', { patterns: [{ group: ['**/api/client*'], importNames: ['startResearch'], message: 'start research through research/coordinator.js' }] }] },
  },
  {
    // Enforced by tools/check.py through pnpm lint:i18n, which lints .js too despite its --ext .vue.
    files: ['src/**/*.{js,vue}'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['dexie', 'dexie-react-hooks'], message: 'import dexie only through state/db.js' },
          { regex: '(^|/)state/db', message: 'import state/db.js only from within state/' },
        ],
      }],
    },
  },
  {
    files: ['src/selfchecks/**/*.js'],
    rules: { 'no-restricted-imports': ['error', { patterns: [{ group: ['dexie', 'dexie-react-hooks'], message: 'import dexie only through state/db.js' }] }] },
  },
  {
    files: ['src/state/db.js'],
    rules: { 'no-restricted-imports': 'off' },
  },
]
