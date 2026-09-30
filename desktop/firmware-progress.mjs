// esptool reports each binary separately. Weight their percentages by file size
// so the application upload does not look like four separate installations.
export function firmwareProgress(segments, update) {
  const total = segments.reduce((sum, segment) => sum + segment.size_bytes, 0)
  let buffered = '', verified = 0, completed = 0, percent = 0
  function line(text) {
    const segment = segments[verified]
    if (!segment) return
    const writing = text.match(/Writing at\s+0x[\da-f]+.*?(\d+(?:\.\d+)?)\s*%/i)
    if (writing) {
      percent = Math.max(percent, 100 * (completed + segment.size_bytes * Math.min(100, Number(writing[1])) / 100) / total)
      update({ percent, verified, total: segments.length, phase: 'writing' })
    } else if (/Hash of data verified/i.test(text)) {
      completed += segment.size_bytes
      verified++
      percent = Math.max(percent, 100 * completed / total)
      update({ percent, verified, total: segments.length, phase: 'verified' })
    } else if (/Wrote\s+\d|Wrote\s+[\d,]+\s+bytes/i.test(text)) {
      update({ percent, verified, total: segments.length, phase: 'verifying' })
    }
  }
  return {
    push(text) {
      buffered += text
      const lines = buffered.split(/[\r\n]/)
      buffered = lines.pop()
      lines.forEach(line)
    },
    finish() { line(buffered); buffered = '' }
  }
}
