/**
 * Small clipboard helper shared by code blocks and message actions in ChatBox.
 */

/** Copy text to the clipboard. Falls back to execCommand for non-HTTPS
 *  internal deployments where navigator.clipboard is unavailable. */
export async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {}
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
