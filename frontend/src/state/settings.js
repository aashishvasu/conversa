import { globalSettings } from './store.js'

// The settings surface: which keys exist per owner, and how an owner resolves against the global defaults.

// Research preferences are global defaults with per-conversation overrides.
// A run snapshots their effective values when it starts.
export const RESEARCH_KEYS = [
  'research_search_model',
  'research_note_model',
  'research_report_model',
  'research_depth',
]

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
  ...RESEARCH_KEYS,
  'tools_enabled',
  'tool_web_search',
  'tool_fetch_url',
  'tool_datetime',
  'tool_calculator',
  'tool_random',
  'tool_max_rounds',
  'tool_max_calls',
]

export const RESEARCH_MODEL_FIELDS = [
  { key: 'research_search_model', labelKey: 'research.searchModel' },
  { key: 'research_note_model', labelKey: 'research.notesModel' },
  { key: 'research_report_model', labelKey: 'research.reportModel' },
]

export const TOOL_FIELDS = [
  { key: 'tool_web_search', tool: 'search_web' },
  { key: 'tool_fetch_url', tool: 'fetch_url' },
  { key: 'tool_datetime', tool: 'datetime' },
  { key: 'tool_calculator', tool: 'calculator' },
  { key: 'tool_random', tool: 'random' },
]

// The one definition of the thinking-effort lever, rendered by the composer toolbar and both settings panels.
// Values go to the API as output_config.effort, and the backend maps them to token budgets for pre-4.6 models.
// Adding a level here (Anthropic also has 'xhigh' and 'max') surfaces it in all three places.
// Values stored under the legacy thinking_budget key are ignored.
export const EFFORT_LEVELS = ['', 'low', 'medium', 'high']

// A per-owner override falls back to the global default per key.
// `??` so an explicit false/0 override is respected; only null/undefined inherits.
// `owner` is normally a conversation; a run carries its own completed snapshot.
export function effectiveSettings(owner, keys = SETTING_KEYS) {
  const g = globalSettings.value || {}
  const out = {}
  for (const k of keys) out[k] = owner?.settings?.[k] ?? g[k]
  return out
}

export function enabledTools(settings) {
  if (!settings?.tools_enabled) return []
  return TOOL_FIELDS.filter((field) => settings[field.key]).map((field) => field.tool)
}
