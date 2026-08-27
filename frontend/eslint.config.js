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
]
