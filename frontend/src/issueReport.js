export const ISSUE_URL = 'https://github.com/thelastoutpostworkshop/ESPImageServer/issues/new'

function bounded(text, limit) {
  const suffix = '\n[truncated]'
  return text.length <= limit ? text : text.slice(0, Math.max(0, limit - suffix.length)) + suffix.slice(0, limit)
}

// Defense in depth for copied reports. The server also sanitizes optional logs.
export function sanitizeIssueText(value, maxLength = 12000) {
  if (typeof value !== 'string') return ''
  const limit = Number.isInteger(maxLength) && maxLength > 0 ? Math.min(maxLength, 12000) : 12000
  let text = value.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
  // A credential value may contain spaces, escaped quotes, or newlines. Keep
  // only the safe prefix rather than guessing where that value ends.
  text = text
    .replace(/\bBearer\s+[\s\S]*/i, 'Bearer [redacted]')
    .replace(/\b(?:hf_[a-z0-9]+|sk-[a-z0-9_-]+|github_pat_[a-z0-9_]+|gh[pousr]_[a-z0-9]+)\b/gi, '[redacted]')
    .replace(/\b((?:[\w-]+[_-])?(?:(?:wi[-_ ]?fi[-_ ]?)?(?:password|passwd|pass|pwd|ssid)|api[-_ ]?key|access[-_ ]?token|auth(?:orization)?|secret|token|huggingface[-_ ]?token|hf[-_ ]?token))\b["']?\s*[:=][\s\S]*/i, '$1=[redacted]')
    .replace(/https?:\/\/[^\s"'<>]+/gi, '[network address redacted]')
    .replace(/(["'])(?:[a-z]:[\\/]|\\\\|\/(?:home|Users)\/|\/mnt\/[a-z]\/Users\/)[^\n]*?\1/gi, '[path redacted]')
    .replace(/\bfile:\/\/[^\n"'<>|]*/gi, '[path redacted]')
    .replace(/(?:\b[a-z]:[\\/]|\\\\|\/(?:home|Users)\/|\/mnt\/[a-z]\/Users\/)[^\n"'<>|]*/gi, '[path redacted]')
    .replace(/(?<!\w)(?:[a-f0-9]{2}[:-]){5}[a-f0-9]{2}(?!\w)/gi, '[network address redacted]')
    .replace(/(?<![\w:])(?:(?:[a-f0-9]{1,4}:){7}[a-f0-9]{1,4}|(?:[a-f0-9]{1,4}:)*[a-f0-9]{0,4}::(?:[a-f0-9]{1,4}:)*[a-f0-9:.]*)(?:%[\w.-]+)?(?![\w:])/gi, '[network address redacted]')
    .replace(/\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b/g, '[network address redacted]')
    .replace(/\b(?:[a-z0-9-]+\.)+(?:local|lan|internal)\b(?::\d+)?/gi, '[network address redacted]')
    .replace(/`{3,}|~{3,}/g, fence => [...fence].join('\u200b'))
  return bounded(text, limit)
}

function scalar(value) {
  if (typeof value !== 'string' || !value.trim()) return 'Unknown'
  return sanitizeIssueText(value, 200).replace(/\s+/g, ' ').trim()
}

const yesNo = value => typeof value === 'boolean' ? (value ? 'Yes' : 'No') : 'Unknown'
const positiveInteger = value => Number.isSafeInteger(value) && value > 0 ? String(value) : 'Unknown'
const rotation = value => [0, 90, 180, 270].includes(value) ? `${value}°` : 'Not recorded'

export function buildIssueReport({
  details = {}, happened = '', steps = '', expected = '', imageModel = '', videoModel = '',
  display = null, imageRotation = null, videoRotation = null, includeLogs = false,
} = {}) {
  const system = details?.system
  const generation = details?.generation
  const packages = details?.packages
  const description = (value, placeholder, limit) => sanitizeIssueText(value, limit).trim() || placeholder
  const technical = [
    ['App version', scalar(details?.app_version)],
    ['Server OS', scalar(system?.os)],
    ['OS release', scalar(system?.release)],
    ['OS version', scalar(system?.version)],
    ['Architecture', scalar(system?.architecture)],
    ['Python', scalar(system?.python)],
    ['Generation device', scalar(generation?.device)],
    ['CUDA available', yesNo(generation?.cuda_available)],
    ['CUDA version', scalar(generation?.cuda_version)],
    ['GPU', scalar(generation?.gpu_name)],
    ['GPU memory (bytes)', positiveInteger(generation?.gpu_memory_bytes)],
    ['Image model', scalar(imageModel)],
    ['Video model', scalar(videoModel)],
    ['Image rotation', rotation(imageRotation)],
    ['Video rotation', rotation(videoRotation)],
  ]
  if (display && typeof display === 'object' && !Array.isArray(display)) {
    const available = typeof display.online === 'boolean' ? display.online : display.connected
    technical.push(
      ['Display board target', scalar(display.board_target)],
      ['Display firmware version', scalar(display.firmware_version)],
      ['Display width', positiveInteger(display.width)],
      ['Display height', positiveInteger(display.height)],
      ['Display status', typeof available === 'boolean' ? (available ? 'Online' : 'Offline') : 'Unknown'],
    )
  } else {
    technical.push(['Display', 'None selected'])
  }
  for (const name of ['torch', 'diffusers', 'transformers', 'accelerate', 'fastapi', 'imageio_ffmpeg']) {
    technical.push([name, scalar(packages?.[name])])
  }
  const sections = [
    `## What happened\n\n${description(happened, '_Describe what went wrong._', 4000)}`,
    `## Steps to reproduce\n\n${description(steps, '1. Describe the actions that led to the problem.', 4000)}`,
    `## Expected behavior\n\n${description(expected, '_Describe what you expected to happen._', 2000)}`,
    `## Technical details\n\n${technical.map(([label, value]) => `- ${label}: ${value}`).join('\n')}`,
  ]
  if (includeLogs === true) {
    const lines = Array.isArray(details?.logs) ? details.logs.filter(line => typeof line === 'string').slice(-100) : []
    const logs = sanitizeIssueText(lines.map(line => /\b(?:(?:negative|positive)[_ -]?)?prompt["']?\s*[:=]/i.test(line) ? '[prompt omitted]' : line).join('\n'))
    sections.push(`## Recent logs\n\n${logs.trim() ? `\`\`\`text\n${logs}\n\`\`\`` : '_No recent log lines available._'}`)
  }
  return sections.join('\n\n') + '\n'
}
