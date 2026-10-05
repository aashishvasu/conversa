import { ref } from 'vue'
import { createImage, releaseImages } from '../state/store.js'
import { notify } from '../utils/notify.js'
import { tr } from '../i18n/index.js'

// Image limits: long edge capped at 2000px, encoded target under 1MB, final base64 string under 10MB.
// Pipeline: resize via canvas, try PNG (lossless for PNG inputs), then webp, then jpeg as last resort.
export function useImageAttachments() {
  const pendingImages = ref([])
  const imageInput = ref(null)

  async function attachImages(files) {
    for (const file of files) {
      try {
        if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type))
          throw new Error(tr('chat.unsupportedImage', { name: file.name || tr('chat.file') }))
        const bitmap = await createImageBitmap(file)
        const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height))
        const width = Math.round(bitmap.width * scale)
        const height = Math.round(bitmap.height * scale)
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const context = canvas.getContext('2d')
        if (!context) {
          bitmap.close()
          throw new Error(tr('chat.processImageFailed'))
        }
        context.drawImage(bitmap, 0, 0, width, height)
        bitmap.close()
        const encode = (type) => new Promise((resolve) => canvas.toBlob(resolve, type, 0.85))
        let blob = file.type === 'image/png' ? await encode('image/png') : null
        if (!blob || blob.size > 1024 * 1024) blob = await encode('image/webp')
        if (!blob || blob.type !== 'image/webp') blob = await encode('image/jpeg')
        if (!blob) throw new Error(tr('chat.encodeImageFailed', { name: file.name || tr('chat.image') }))
        const bytes = new Uint8Array(await blob.arrayBuffer())
        let binary = ''
        for (const byte of bytes) binary += String.fromCharCode(byte)
        const data = btoa(binary)
        if (data.length > 10 * 1024 * 1024) throw new Error(tr('chat.imageTooLarge', { name: file.name || tr('chat.image') }))
        pendingImages.value.push(await createImage({ id: crypto.randomUUID(), media_type: blob.type, width, height, data, createdAt: Date.now() }))
      } catch (e) {
        notify({ key: 'image:attach', severity: 'warning', text: e.message })
      }
    }
  }

  function onImageInput(e) {
    attachImages(e.target.files)
    e.target.value = ''
  }

  function onPaste(e) {
    if (e.clipboardData.files.length) attachImages(e.clipboardData.files)
  }

  function onDrop(e) {
    e.preventDefault()
    attachImages(e.dataTransfer.files)
  }

  function removePending(image) {
    pendingImages.value = pendingImages.value.filter((x) => x.id !== image.id)
    releaseImages([image.id])
  }

  return { pendingImages, imageInput, attachImages, onImageInput, onPaste, onDrop, removePending }
}
