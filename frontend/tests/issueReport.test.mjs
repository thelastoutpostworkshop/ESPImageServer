import test from 'node:test'
import assert from 'node:assert/strict'
import { buildIssueReport, ISSUE_URL, sanitizeIssueText } from '../src/issueReport.js'

test('the issue link has a fixed destination without a report in its URL', () => {
  assert.equal(ISSUE_URL, 'https://github.com/thelastoutpostworkshop/ESPImageServer/issues/new')
  assert.equal(new URL(ISSUE_URL).search, '')
})

test('missing technical details produce readable unknowns and helpful form placeholders', () => {
  const report = buildIssueReport()
  for (const heading of ['What happened', 'Steps to reproduce', 'Expected behavior', 'Technical details']) {
    assert.ok(report.includes(`## ${heading}\n\n`))
  }
  assert.ok(report.includes('_Describe what went wrong._'))
  assert.ok(report.includes('1. Describe the actions that led to the problem.'))
  assert.ok(report.includes('_Describe what you expected to happen._'))
  assert.ok(report.includes('- Server OS: Unknown'))
  assert.ok(report.includes('- Display: None selected'))
  assert.ok(!report.includes('undefined'))
  assert.ok(!report.includes('Recent logs'))
})

test('technical details whitelist server environment and exclude personal and unrelated state', () => {
  const report = buildIssueReport({
    details: {
      app_version: '2.3.4',
      system: { os: 'Ubuntu', release: '24.04', version: 'Server build', architecture: 'x86_64', python: '3.12.1', hostname: 'private-host', username: 'private-user' },
      generation: { device: 'cuda', cuda_available: true, cuda_version: '12.4', gpu_name: 'NVIDIA RTX', gpu_memory_bytes: 8589934592, jobs: 'private-job' },
      packages: { torch: '2.5.1', diffusers: '0.35.0', transformers: '4.50.0', accelerate: '1.0.0', fastapi: '0.115.0', imageio_ffmpeg: '0.6.0', extra: 'private-package' },
      userAgent: 'private-browser-os', health: 'private-health', jobs: 'private-jobs',
    },
    display: { board_target: 'JC4827W543', firmware_version: '1.1.45', width: 480, height: 272, online: false, connected: false,
      name: 'private-display-name', id: 'private-id', mac: 'private-mac', ip: 'private-ip', last_activity: 'private-activity' },
    imageModel: 'DreamShaper 8', videoModel: 'Wan 2.1', imageRotation: 90, videoRotation: 270,
  })
  for (const value of ['Ubuntu', '24.04', 'Server build', 'x86_64', '3.12.1', 'cuda', '12.4', 'NVIDIA RTX', '8589934592', '2.5.1', '0.35.0', '0.6.0', 'JC4827W543', '1.1.45', 'DreamShaper 8', 'Wan 2.1']) {
    assert.ok(report.includes(value), `Missing allowed detail: ${value}`)
  }
  assert.ok(report.includes('- Server OS: Ubuntu'))
  assert.ok(report.includes('- CUDA available: Yes'))
  assert.ok(report.includes('- Display status: Offline'))
  assert.ok(report.includes('- Display width: 480'))
  assert.ok(report.includes('- Display height: 272'))
  assert.ok(report.includes('- Image rotation: 90°'))
  assert.ok(report.includes('- Video rotation: 270°'))
  assert.ok(!report.includes('private-'))
})

test('environment fields reject object, array, boolean, and incorrectly typed numbers', () => {
  const report = buildIssueReport({
    details: {
      app_version: { secret: 'object-secret' },
      system: { os: ['array-secret'], release: false, python: 312 },
      generation: { cuda_available: 'true', gpu_memory_bytes: '8589934592' },
      packages: { torch: { nested: 'package-secret' } },
    },
    display: { board_target: ['board-secret'], firmware_version: 1145, width: '480', height: -1, online: 'yes' },
    imageModel: {}, videoModel: [],
  })
  for (const label of ['App version', 'Server OS', 'OS release', 'Python', 'CUDA available', 'GPU memory (bytes)', 'torch', 'Display width', 'Display height', 'Display status', 'Image model', 'Video model']) {
    assert.ok(report.includes(`- ${label}: Unknown`), `Incorrectly accepted field: ${label}`)
  }
  assert.ok(!report.includes('secret'))
  assert.ok(!report.includes('[object Object]'))
})

test('only exact numeric rotations are recorded, including zero', () => {
  for (const value of [0, 90, 180, 270]) {
    const report = buildIssueReport({ imageRotation: value, videoRotation: value })
    assert.ok(report.includes(`- Image rotation: ${value}°`))
    assert.ok(report.includes(`- Video rotation: ${value}°`))
  }
  for (const value of [null, undefined, '', '0', '90', false, true, -90, 360, NaN, {}]) {
    const report = buildIssueReport({ imageRotation: value, videoRotation: value })
    assert.ok(report.includes('- Image rotation: Not recorded'))
    assert.ok(report.includes('- Video rotation: Not recorded'))
  }
})

test('an offline display is distinct from no display and legacy connection status is supported', () => {
  const offline = buildIssueReport({ display: { board_target: 'JC4827W543', online: false } })
  assert.ok(offline.includes('- Display status: Offline'))
  assert.ok(!offline.includes('None selected'))
  assert.ok(buildIssueReport({ display: { connected: true } }).includes('- Display status: Online'))
  assert.ok(buildIssueReport({ display: null }).includes('- Display: None selected'))
})

test('logs are excluded by default and require explicit boolean opt-in', () => {
  for (const includeLogs of [undefined, false, 'true', 1]) {
    const report = buildIssueReport({ details: { logs: ['log-only-content'] }, includeLogs })
    assert.ok(!report.includes('log-only-content'))
    assert.ok(!report.includes('Recent logs'))
  }
  assert.ok(buildIssueReport({ includeLogs: true }).includes('_No recent log lines available._'))
})

test('credentials, quoted secrets, personal paths, and network addresses are redacted', () => {
  const text = [
    'wifi_password="secret with spaces" ssid=private-network',
    'api_key: "api secret words" hf_token=hf_veryprivate123',
    'OPENAI_API_KEY="prefixed secret words" WIFI_PASS=private-wifi-pass',
    'Authorization: Bearer bearer-secret-value',
    'Standalone hf_tokenvalue123 sk-proj-privatekey github_pat_privatekey',
    'File "C:\\Users\\Jane Doe\\Private Images\\photo.jpg" failed',
    'File /home/jane/private/file.log failed',
    'File /Users/jane/Documents/file.log failed',
    'File "\\\\private-nas\\Shared Folder\\photo.jpg" failed',
    'Connect 192.168.1.25:8000 or 2001:db8::1 or ::1 or board.local',
    'MAC aa:bb:cc:dd:ee:ff URL http://private-host:8000/private?token=secret-query',
  ].map(value => sanitizeIssueText(value)).join('\n')
  for (const secret of ['secret with spaces', 'private-network', 'api secret words', 'prefixed secret words', 'private-wifi-pass', 'veryprivate123', 'bearer-secret-value', 'hf_tokenvalue123', 'sk-proj-privatekey', 'github_pat_privatekey', 'Jane Doe', '/home/jane', '/Users/jane', 'private-nas', '192.168.1.25', '2001:db8::1', '::1', 'board.local', 'aa:bb:cc:dd:ee:ff', 'private-host', 'secret-query']) {
    assert.ok(!text.includes(secret), `Leaked: ${secret}`)
  }
  assert.ok(text.includes('failed'))
  assert.ok(text.includes('[redacted]'))
  assert.equal(sanitizeIssueText('2026-10-17 13:44:55 INFO Failed after 00:10:30'), '2026-10-17 13:44:55 INFO Failed after 00:10:30')
})

test('credential assignments discard ambiguous unquoted, escaped, and multiline values after the safe prefix', () => {
  for (const input of [
    'Safe explanation. password=secret with spaces',
    'Safe explanation. password: "secret \\"quote\\" continuation"',
    'Safe explanation. {"password":"secret \\"quote\\" continuation"}',
    'Safe explanation. Wi-Fi SSID:\nprivate network\nprivate continuation',
    'Safe explanation. api_key=\nprivate first line\nprivate continuation',
    'Safe explanation. Bearer secret with spaces\nprivate continuation',
  ]) {
    const text = sanitizeIssueText(input)
    assert.ok(text.startsWith('Safe explanation.'), input)
    assert.ok(text.endsWith('[redacted]'), input)
    assert.ok(!text.includes('secret'), input)
    assert.ok(!text.includes('quote'), input)
    assert.ok(!text.includes('continuation'), input)
    assert.ok(!text.includes('private'), input)
  }
  const report = buildIssueReport({
    happened: 'The prompt fails after selecting a model. password=secret with spaces',
    steps: 'Connect Wi-Fi. Wi-Fi SSID:\nprivate network\nprivate continuation',
    expected: 'JSON config: {"password":"secret \\"quote\\" continuation"}',
  })
  assert.ok(report.includes('The prompt fails after selecting a model.'))
  assert.ok(report.includes('Connect Wi-Fi.'))
  assert.ok(report.includes('JSON config:'))
  for (const value of ['secret', 'quote', 'continuation', 'private network']) assert.ok(!report.includes(value), value)
})

test('unquoted personal paths and file URIs redact complete paths containing spaces', () => {
  for (const path of [
    'C:\\Users\\Jane Doe\\My Private Folder\\file.jpg',
    '/home/jane/My Private Folder/file.log',
    '/Users/Jane Doe/My Private Folder/file.log',
    '/mnt/c/Users/Jane Doe/My Private Folder/file.log',
    '\\\\private-nas\\My Private Folder\\file.jpg',
    'file:///C:/Users/Jane%20Doe/My%20Private%20Folder/file.jpg',
    'file:///home/jane/My Private Folder/file.log',
  ]) {
    const text = sanitizeIssueText(`Safe explanation. ${path}\nNext safe line.`)
    assert.equal(text, 'Safe explanation. [path redacted]\nNext safe line.', path)
    for (const value of ['Jane', 'jane', 'Private', 'Folder', 'file.jpg', 'file.log', 'private-nas', 'file:///']) {
      assert.ok(!text.includes(value), `${path}: ${value}`)
    }
  }
})

test('user problem descriptions preserve ordinary discussion of prompts and redact secrets', () => {
  const report = buildIssueReport({
    happened: 'The prompt fails after selecting a model. password="my private password"',
    steps: '1. Enter a prompt.\n2. Click Generate.',
    expected: 'A generated image should appear.',
  })
  assert.ok(report.includes('The prompt fails after selecting a model.'))
  assert.ok(report.includes('1. Enter a prompt.\n2. Click Generate.'))
  assert.ok(report.includes('A generated image should appear.'))
  assert.ok(!report.includes('my private password'))
})

test('optional logs redact prompt payloads, ignore nonstrings, and cannot close the Markdown fence', () => {
  const report = buildIssueReport({ includeLogs: true, details: { logs: [
    'INFO Prompt: private generation text', 'negative_prompt="private negative text"',
    'prompt="private first line\nprivate continuation"',
    'Normal failure message', '```\n## Injected heading\n~~~', { secret: 'object-secret' },
  ] } })
  assert.ok(report.includes('[prompt omitted]'))
  assert.ok(report.includes('Normal failure message'))
  for (const secret of ['private generation text', 'private negative text', 'private continuation', 'object-secret']) assert.ok(!report.includes(secret))
  assert.equal(report.split('\n').filter(line => /^```/.test(line)).length, 2)
  assert.ok(!report.includes('\n~~~'))
})

test('logs and user descriptions are bounded while retaining recent log lines', () => {
  const report = buildIssueReport({
    happened: 'h'.repeat(10000), steps: 's'.repeat(10000), expected: 'e'.repeat(10000),
    includeLogs: true, details: { logs: ['old-content', ...Array.from({ length: 110 }, (_, i) => `recent-${i}`)] },
  })
  assert.ok(!report.includes('old-content'))
  assert.ok(!report.includes('recent-0\n'))
  assert.ok(report.includes('recent-109'))
  assert.ok(report.includes('[truncated]'))
  const longLogs = buildIssueReport({ includeLogs: true, details: { logs: ['x'.repeat(20000)] } }).split('```text\n')[1].split('\n```')[0]
  assert.ok(longLogs.length <= 12000)
  assert.ok(longLogs.endsWith('[truncated]'))
  assert.ok(sanitizeIssueText('x'.repeat(1000), 100).length <= 100)
})
