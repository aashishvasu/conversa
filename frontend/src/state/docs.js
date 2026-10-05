import { delMany, set } from 'idb-keyval'
import { computed } from 'vue'
import { IMAGE_KEY_PREFIX, IMAGE_TYPES, state, storageFailure } from './persistence.js'
import { dismiss } from '../utils/notify.js'
import { tr } from '../i18n/index.js'

export const docs = computed(() => state.docs)
export const images = computed(() => state.images)

export function validImage(image) {
  return Boolean(image?.id && typeof image.data === 'string' && IMAGE_TYPES.has(image.media_type))
}

export async function createImage(image) {
  if (!validImage(image)) throw new Error(tr('errors.invalidImage'))
  await set(`${IMAGE_KEY_PREFIX}${image.id}`, image).then(() => dismiss('storage'), (e) => { storageFailure(e); throw e })
  state.images.push(image)
  return image
}

export function imagesOf(message) {
  return (message?.imageIds || []).map((id) => state.images.find((image) => image.id === id)).filter(Boolean)
}

export function gcImages(ids) {
  const referenced = new Set(state.conversations.flatMap((c) => c.messages.flatMap((m) => m.imageIds || [])))
  const doomed = (ids || state.images.map((image) => image.id)).filter((id) => !referenced.has(id))
  if (!doomed.length) return
  state.images = state.images.filter((image) => !doomed.includes(image.id))
  delMany(doomed.map((id) => `${IMAGE_KEY_PREFIX}${id}`)).then(() => dismiss('storage'), storageFailure)
}

export function releaseImages(ids) {
  gcImages(ids)
}

export function gcDocs(ids) {
  if (!ids?.length) return
  const referenced = new Set()
  for (const o of [...state.workspaces, ...state.conversations]) for (const id of o.docIds || []) referenced.add(id)
  state.docs = state.docs.filter((d) => !ids.includes(d.id) || referenced.has(d.id))
}

export function createDoc({ name, text, source }) {
  const d = { id: crypto.randomUUID(), name, text, createdAt: Date.now(), updatedAt: Date.now(), source, versions: [] }
  state.docs.push(d)
  return d
}

export function docsOf(owner) {
  return (owner?.docIds || []).map((id) => state.docs.find((d) => d.id === id)).filter(Boolean)
}

export function removeDocRef(owner, id) {
  owner.docIds = (owner.docIds || []).filter((x) => x !== id)
  gcDocs([id])
}

export function deleteDoc(id) {
  state.docs = state.docs.filter((d) => d.id !== id)
  for (const o of [...state.workspaces, ...state.conversations]) {
    if (o.docIds?.includes(id)) o.docIds = o.docIds.filter((x) => x !== id)
  }
}

const DOC_VERSION_CAP = 10

export function updateDocText(doc, text) {
  ;(doc.versions ??= []).push({ text: doc.text, savedAt: Date.now() })
  if (doc.versions.length > DOC_VERSION_CAP) doc.versions.shift()
  doc.text = text
  doc.updatedAt = Date.now()
}

export function undoDocRevision(doc) {
  const v = doc.versions?.pop()
  if (!v) return
  doc.text = v.text
  doc.updatedAt = Date.now()
}

// Pre-doc-store workspaces held docs inline; hoist them into the doc store and leave refs behind.
// Runs on every entry path (initStore, restoreData, importData) so a legacy archive upgrades wherever it appears.
// Keeps the original doc ids: refs elsewhere in the same archive stay valid, and re-importing the same legacy export stays keep-local.
export function hoistInlineDocs(workspaces, docs) {
  const have = new Set(docs.map((d) => d.id))
  for (const w of workspaces) {
    w.docIds ??= []
    for (const d of w.docs || []) {
      if (!d?.id) continue
      if (!have.has(d.id)) {
        docs.push({ id: d.id, name: d.name, text: d.text, createdAt: Date.now(), updatedAt: Date.now(), source: { kind: 'upload' }, versions: [] })
        have.add(d.id)
      }
      w.docIds.push(d.id)
    }
    delete w.docs
  }
}

export function downloadText(name, text, type = 'text/markdown') {
  const a = document.createElement('a')
  const url = URL.createObjectURL(new Blob([text], { type }))
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke on a later task: some browsers only read the blob once the download starts.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
