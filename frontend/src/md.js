import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import { Marked } from 'marked'

// Links open in a new tab, safely.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// Inline icons (raw SVG, since code blocks are rendered as HTML strings, not components).
export const COPY_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>'
export const CHECK_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'

const marked = new Marked({
  breaks: true,
  renderer: {
    // Each fenced block: syntax-highlighted body + a Copy button (handled by delegation in ChatPane).
    // Note: highlightAuto re-runs on every streamed token for unlabelled blocks. Fine for
    // normal output; gate highlighting to stream-complete if huge code blocks lag.
    code({ text, lang }) {
      const valid = lang && hljs.getLanguage(lang)
      const body = valid
        ? hljs.highlight(text, { language: lang }).value
        : hljs.highlightAuto(text).value
      return `<div class="code-block"><button class="code-copy" type="button" aria-label="Copy code">${COPY_SVG}</button><pre><code class="hljs">${body}</code></pre></div>`
    },
  },
})

// Render markdown to sanitized HTML. Sanitizing is the security boundary — never skip it.
export function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ''))
}
