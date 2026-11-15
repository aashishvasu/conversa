import { nextTick, onMounted, ref, watch } from 'vue'
import { turnState } from '../chat/coordinator.js'

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
  // A live turn's text lives in coordinator view state and only reaches the stored message at checkpoints, so the follower reads whichever of the two is current.
  watch(
    () => {
      const last = convo.value?.messages.at(-1)
      return last ? turnState(last.id)?.content ?? last.content : null
    },
    () => atBottom.value && scrollDown(),
    { flush: 'post' },
  )

  // On reload, convo already has its value when this mounts, so the convo watcher in the caller won't fire for the initial selection. Scroll once here.
  onMounted(scrollDown)

  return { atBottom, scroller, scrollDown, onScroll }
}
