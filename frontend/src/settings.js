import { globalSettings } from './store.js'

// The settings surface: which keys exist per owner, and how an owner resolves against the global defaults.

export const SETTING_KEYS = [
  'model',
  'temperature',
  'num_messages_to_send',
  'send_system_prompt',
  'max_tokens',
  'effort',
  'utility_model',
  'use_memory',
  'summarize_n',
  'use_recall',
  'use_cache',
]

// Research settings belong to a run, not to a conversation, so they get their own list.
// Both lists resolve the same way: a per-owner override, falling back to the global default.
// Three model tiers, because the stages have different quality bars: extraction reads one page at a time, orchestration makes short judgement calls, and the report is the only long-form writing.
export const RESEARCH_KEYS = [
  'research_search_model',
  'research_note_model',
  'research_report_model',
  'research_depth',
]

// The one definition of the thinking-effort lever, rendered by the composer toolbar and both settings panels.
// Values go to the API as output_config.effort, and the backend maps them to token budgets for pre-4.6 models.
// Adding a level here (Anthropic also has 'xhigh' and 'max') surfaces it in all three places.
// Values stored under the legacy thinking_budget key are ignored.
export const EFFORT_LEVELS = [
  { label: 'Off', value: '' },
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
]

// A per-owner override falls back to the global default per key.
// `??` so an explicit false/0 override is respected; only null/undefined inherits.
// `owner` is a conversation with SETTING_KEYS, or a run with RESEARCH_KEYS.
export function effectiveSettings(owner, keys = SETTING_KEYS) {
  const g = globalSettings.value || {}
  const out = {}
  for (const k of keys) out[k] = owner?.settings?.[k] ?? g[k]
  return out
}
