import test from 'node:test'
import assert from 'node:assert/strict'
import { renderReleaseNotes } from '../src/releaseNotes.js'

test('release notes format headings, lists, emphasis and web links', () => {
  const html = renderReleaseNotes('## Changes\n\n- **Faster** playback\n- [Details](https://github.com/example/release)')
  assert.match(html, /<h2>Changes<\/h2>/)
  assert.match(html, /<li><strong>Faster<\/strong> playback<\/li>/)
  assert.match(html, /target="_blank" rel="noopener noreferrer"/)
})

test('remote notes cannot inject HTML, script links or image requests', () => {
  const html = renderReleaseNotes('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n[x](file:///secret)\n\n![tracking](https://example.com/pixel)')
  assert.doesNotMatch(html, /<script|<img|href="(?:javascript:|file:)/)
  assert.equal(renderReleaseNotes(null), '')
})
