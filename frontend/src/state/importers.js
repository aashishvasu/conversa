const DATE = /^(\d{1,2})\/(\d{1,2})\/(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})(?:\s+(AM|PM))?$/i

function epoch(value, order) {
  const match = typeof value === 'string' && value.match(DATE)
  if (!match) return null
  const [, first, second, year, hours, minutes, seconds, period] = match
  const day = Number(order === 'dmy' ? first : second)
  const month = Number(order === 'dmy' ? second : first)
  let hour = Number(hours)
  if (period) {
    if (hour < 1 || hour > 12) return null
    hour = hour % 12 + (period.toUpperCase() === 'PM' ? 12 : 0)
  } else if (hour > 23) return null
  const date = new Date(Number(year), month - 1, day, hour, Number(minutes), Number(seconds))
  return date.getFullYear() === Number(year) && date.getMonth() === month - 1 && date.getDate() === day ? date.getTime() : null
}

// WHY: NextChat stores locale dates without the locale. Prefer the order whose timestamps do not follow the session update.
function dateOrder(sessions) {
  const score = (order) => sessions.reduce((total, session) => total + (Array.isArray(session?.messages) ? session.messages.reduce((count, message) => {
    const value = epoch(message?.date, order)
    return count + Number(Number.isFinite(value) && value <= session.lastUpdate + 86_400_000)
  }, 0) : 0), 0)
  return score('mdy') > score('dmy') ? 'mdy' : 'dmy'
}

function message(source, fallback, order, pinned = false) {
  if (!source || !['user', 'assistant'].includes(source.role) || typeof source.content !== 'string') return null
  if (source.isError || source.streaming) return null
  return {
    id: typeof source.id === 'string' && source.id ? source.id : crypto.randomUUID(),
    role: source.role,
    content: source.content,
    createdAt: epoch(source.date, order) ?? fallback,
    ...(pinned ? { pinned: true } : {}),
  }
}

function settings(config, modelIds) {
  const out = {}
  if (typeof config?.model === 'string' && modelIds.includes(config.model)) out.model = config.model
  if (typeof config?.temperature === 'number') out.temperature = config.temperature
  if (typeof config?.max_tokens === 'number') out.max_tokens = config.max_tokens
  if (typeof config?.historyMessageCount === 'number') out.num_messages_to_send = config.historyMessageCount
  if (typeof config?.sendMemory === 'boolean') out.use_memory = config.sendMemory
  return out
}

function conversation(session, order, modelIds, report) {
  if (!session?.id || !Array.isArray(session.messages)) {
    report.sessionsSkipped++
    return null
  }
  if (!session.messages.length) {
    report.sessionsSkipped++
    return null
  }
  const fallback = Number.isFinite(session.lastUpdate) ? session.lastUpdate : Date.now()
  const context = Array.isArray(session.mask?.context) ? session.mask.context : []
  const system = context.filter((entry) => entry?.role === 'system' && typeof entry.content === 'string').map((entry) => entry.content).filter(Boolean).join('\n\n')
  const pinned = context.filter((entry) => entry?.role !== 'system').map((entry) => message(entry, fallback, order, true)).filter(Boolean)
  const turns = session.messages.map((entry) => message(entry, fallback, order)).filter(Boolean)
  report.messagesSkipped += session.messages.length - turns.length
  report.toolsDropped += session.messages.reduce((count, entry) => count + (Array.isArray(entry?.tools) ? entry.tools.length : 0), 0)
  if (!turns.length) {
    report.sessionsSkipped++
    return null
  }
  return {
    id: session.id,
    title: typeof session.topic === 'string' && session.topic.trim() ? session.topic : 'Imported conversation',
    isTemplate: false,
    scanAssistant: false,
    workspaceId: null,
    docIds: [],
    mode: 'chat',
    settings: settings(session.mask?.modelConfig, modelIds),
    cards: [],
    cardOverrides: {},
    memory: typeof session.memoryPrompt === 'string' ? session.memoryPrompt : '',
    memoryCount: Math.max(0, pinned.length + (Number.isInteger(session.lastSummarizeIndex) ? session.lastSummarizeIndex : 0)),
    usage: null,
    messages: [{ id: crypto.randomUUID(), role: 'system', content: system, createdAt: fallback }, ...pinned, ...turns],
    createdAt: Number.isFinite(session.mask?.createdAt) ? session.mask.createdAt : fallback,
    updatedAt: fallback,
  }
}

function template(mask, key, order, modelIds) {
  if (!mask || typeof mask !== 'object') return null
  const fallback = Number.isFinite(mask.createdAt) ? mask.createdAt : Date.now()
  const context = Array.isArray(mask.context) ? mask.context : []
  const system = context.filter((entry) => entry?.role === 'system' && typeof entry.content === 'string').map((entry) => entry.content).filter(Boolean).join('\n\n')
  const pinned = context.filter((entry) => entry?.role !== 'system').map((entry) => message(entry, fallback, order, true)).filter(Boolean)
  return {
    id: `nextchat-mask:${key}`,
    title: typeof mask.name === 'string' && mask.name.trim() ? mask.name : 'Imported template',
    isTemplate: true,
    scanAssistant: false,
    workspaceId: null,
    docIds: [],
    mode: 'chat',
    settings: settings(mask.modelConfig, modelIds),
    cards: [],
    cardOverrides: {},
    memory: '',
    memoryCount: pinned.length,
    usage: null,
    messages: [{ id: crypto.randomUUID(), role: 'system', content: system, createdAt: fallback }, ...pinned],
    createdAt: fallback,
    updatedAt: fallback,
  }
}

function nextChat(data, modelIds) {
  const sessions = data['chat-next-web-store'].sessions
  const report = { conversations: 0, templates: 0, sessionsSkipped: 0, messagesSkipped: 0, toolsDropped: 0 }
  const order = dateOrder(sessions)
  const conversations = sessions.map((session) => conversation(session, order, modelIds, report)).filter(Boolean)
  report.conversations = conversations.length
  const masks = data['mask-store']?.masks
  const entries = Array.isArray(masks) ? masks.entries() : Object.entries(masks || {})
  for (const [key, mask] of entries) {
    const item = template(mask, key, order, modelIds)
    if (item) {
      conversations.push(item)
      report.templates++
    }
  }
  return { data: { conversations }, report }
}

export function convertImport(data, modelIds = []) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || !Array.isArray(data['chat-next-web-store']?.sessions)) return null
  return nextChat(data, modelIds)
}
