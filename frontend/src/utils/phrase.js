// Normalize a pasted transfer phrase into its canonical five-word form.
// Returns '' when the input is not five lowercase words, so callers treat it as invalid.
export function normalizePhrase(input) {
  const words = String(input ?? '').trim().toLowerCase().match(/[a-z]+/g) || []
  if (words.length !== 5) return ''
  return words.join('-')
}
