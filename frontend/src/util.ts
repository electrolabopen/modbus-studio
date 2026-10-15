const pad = (n: number, width = 2) => String(n).padStart(width, '0')

/** Local time as YYYYMMDD-HHMM, for file names. */
export function fileTimestamp(d = new Date()): string {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`
}

/** Local time of a Unix timestamp (seconds) as HH:MM:SS.mmm. */
export function clockTime(timestamp: number): string {
  const d = new Date(timestamp * 1000)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

/** Offer ``text`` to the user as a file download. */
export function downloadText(name: string, text: string, type: string): void {
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([text], { type }))
  link.download = name
  link.click()
  URL.revokeObjectURL(link.href)
}
