import { nextTick, onMounted, ref, watch } from 'vue'

export function useAutoScroll(convo) {
  const atBottom = ref(true)
  const scroller = ref(null)

  function scrollDown() {
    nextTick(() => {
      if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
    })
  }

  function onScroll() {
    const el = scroller.value
    if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  // Auto-follow the stream only when the user is already at the bottom.
  watch(() => convo.value?.messages.at(-1)?.content, () => atBottom.value && scrollDown(), { flush: 'post' })

  // On reload, convo already has its value when this mounts, so the convo watcher in the
  // caller won't fire for the initial selection. Scroll once here.
  onMounted(scrollDown)

  return { atBottom, scroller, scrollDown, onScroll }
}
