import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { computed, effectScope, nextTick, ref, watch } from 'vue'

const component = await readFile(new URL('../src/components/IssueReport.vue', import.meta.url), 'utf8')
const script = component.slice(component.indexOf('<script setup>') + '<script setup>'.length, component.indexOf('</script>'))
  .replace(/^import .*$/gm, '')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// Exercise the production controller with Vue's actual reactive scheduling.
// Network, clipboard, and browser lifecycle hooks stay controlled by each test.
function setup(t, options = {}) {
  const mounted = [], unmounted = [], requests = [], copies = [], timers = new Map()
  let nextTimer = 0, destroyed = false
  const props = {
    appVersion: '1.2.3', imageModel: 'DreamShaper 8', videoModel: 'wan-2.1-t2v-1.3b',
    display: { board_target: 'JC4827W543', width: 480, height: 272 },
    imageRotation: 0, videoRotation: 90,
    copyText: text => { copies.push(text); return options.copyText?.(text) ?? Promise.resolve() },
    ...options.props,
  }
  const context = vm.createContext({
    computed, ref, watch, AbortController,
    defineProps: () => props,
    onMounted: callback => mounted.push(callback),
    onUnmounted: callback => unmounted.push(callback),
    fetch: (url, init) => {
      const response = deferred()
      requests.push({ url, init, ...response })
      return response.promise
    },
    window: {
      setTimeout: (callback, delay) => { timers.set(++nextTimer, { callback, delay }); return nextTimer },
      clearTimeout: id => timers.delete(id),
    },
    // Report formatting and redaction have their own helper tests. This exposes
    // exactly which current form data the controller sends to that formatter.
    buildIssueReport: data => JSON.stringify(data),
    ISSUE_URL: 'https://github.com/thelastoutpostworkshop/ESPImageServer/issues/new',
  })
  const scope = effectScope()
  scope.run(() => vm.runInContext(`${script}\n
    globalThis.form = { happened, steps, expected, includeLogs, details, loading,
      loadError, copying, copyStatus, copyError, report, loadDetails, copyReport };
  `, context))
  const unmount = () => {
    if (destroyed) return
    destroyed = true
    for (const callback of unmounted) callback()
    scope.stop()
  }
  t.after(unmount)
  assert.equal(mounted.length, 1)
  const initialLoad = mounted[0]()
  return { form: context.form, requests, copies, timers, initialLoad, unmount }
}

const reportData = run => JSON.parse(run.form.report.value)
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body })
async function settle(request, body, status = 200) {
  request.resolve(response(body, status))
  await request.promise
  // Complete the cross-context fetch/json promise chain before reading refs.
  await new Promise(resolve => setImmediate(resolve))
  await nextTick()
}

test('mount collects details without logs and supplies the current models, display, and rotations', async t => {
  const run = setup(t)
  assert.equal(run.form.includeLogs.value, false)
  assert.equal(run.requests.length, 1)
  assert.equal(run.requests[0].url, '/diagnostics/report?include_logs=false')
  assert.equal(run.requests[0].init.cache, 'no-store')
  assert.equal(run.form.loading.value, true)
  await settle(run.requests[0], { app_version: '1.2.4', system: { os: 'Windows' }, logs: [] })
  await run.initialLoad
  const report = reportData(run)
  assert.equal(report.details.app_version, '1.2.4')
  assert.equal(report.imageModel, 'DreamShaper 8')
  assert.equal(report.videoModel, 'wan-2.1-t2v-1.3b')
  assert.equal(report.display.board_target, 'JC4827W543')
  assert.equal(report.imageRotation, 0)
  assert.equal(report.videoRotation, 90)
  assert.equal(report.includeLogs, false)
  assert.equal(run.form.loading.value, false)
  assert.equal(run.timers.size, 0)
})

test('opting into logs explicitly requests them and opting out clears the previous excerpt before refresh completes', async t => {
  const run = setup(t)
  await settle(run.requests[0], { app_version: '1.2.3', logs: [] })
  run.form.includeLogs.value = true
  await nextTick()
  assert.equal(run.requests[1].url, '/diagnostics/report?include_logs=true')
  await settle(run.requests[1], { app_version: '1.2.3', logs: ['Example diagnostic line'] })
  assert.deepEqual(reportData(run).details.logs, ['Example diagnostic line'])

  run.form.includeLogs.value = false
  await nextTick()
  assert.equal(run.requests[2].url, '/diagnostics/report?include_logs=false')
  assert.equal(run.form.loading.value, true)
  assert.deepEqual(reportData(run).details.logs, [])
  assert.equal(reportData(run).includeLogs, false)
  await settle(run.requests[2], { app_version: '1.2.3', logs: [] })
})

test('a late opted-in response cannot restore logs after consent is withdrawn', async t => {
  const run = setup(t)
  await settle(run.requests[0], { app_version: '1.2.3', logs: [] })
  run.form.includeLogs.value = true
  await nextTick()
  const optedIn = run.requests[1]
  run.form.includeLogs.value = false
  await nextTick()
  assert.equal(optedIn.init.signal.aborted, true)
  await settle(run.requests[2], { app_version: 'newer', logs: [] })
  // A server or fetch mock can finish despite abort; the request sequence must
  // still reject its stale result rather than relying on cancellation alone.
  await settle(optedIn, { app_version: 'stale', logs: ['Late private excerpt'] })
  assert.equal(reportData(run).details.app_version, 'newer')
  assert.deepEqual(reportData(run).details.logs, [])
  assert.equal(run.form.loading.value, false)
  assert.equal(run.form.loadError.value, '')
})

test('a failed details request preserves the written form and an available report can still be copied', async t => {
  const run = setup(t)
  run.form.happened.value = 'The preview stopped updating'
  run.form.steps.value = '1. Open the gallery\n2. Select a saved creation'
  run.form.expected.value = 'The preview should open'
  run.requests[0].reject(new Error('Network unavailable'))
  await run.initialLoad
  assert.equal(run.form.loading.value, false)
  assert.match(run.form.loadError.value, /could not be collected/)
  assert.match(run.form.loadError.value, /copy the report/)
  const report = reportData(run)
  assert.equal(report.happened, 'The preview stopped updating')
  assert.equal(report.steps, '1. Open the gallery\n2. Select a saved creation')
  assert.equal(report.expected, 'The preview should open')
  assert.equal(report.details.app_version, '1.2.3')
  await run.form.copyReport()
  assert.equal(run.copies.length, 1)
  assert.equal(JSON.parse(run.copies[0]).happened, report.happened)
  assert.match(run.form.copyStatus.value, /Issue report copied/)
})

for (const [description, body, status] of [
  ['HTTP failure', { message: 'Unavailable' }, 503],
  ['malformed details', ['not a report'], 200],
]) test(`${description} leaves a retryable details error and permits a later successful refresh`, async t => {
  const run = setup(t)
  await settle(run.requests[0], body, status)
  await run.initialLoad
  assert.match(run.form.loadError.value, /Refresh details/)
  assert.equal(run.form.loading.value, false)
  const retry = run.form.loadDetails()
  assert.equal(run.form.loadError.value, '')
  await settle(run.requests[1], { app_version: 'recovered', logs: [] })
  await retry
  assert.equal(reportData(run).details.app_version, 'recovered')
  assert.equal(run.form.loadError.value, '')
})

test('unmount aborts collection and a late response cannot update retained form state', async t => {
  const run = setup(t)
  const request = run.requests[0]
  run.unmount()
  assert.equal(request.init.signal.aborted, true)
  await settle(request, { app_version: 'late', logs: ['Late diagnostic line'] })
  await run.initialLoad
  assert.equal(run.form.details.value, null)
  assert.equal(run.form.loadError.value, '')
  assert.equal(run.timers.size, 0)
  run.form.includeLogs.value = true
  await nextTick()
  assert.equal(run.requests.length, 1, 'unmounted watchers must not start another request')
})

test('a superseded request failure cannot replace the newer successful result or loading state', async t => {
  const run = setup(t)
  const latest = run.form.loadDetails()
  assert.equal(run.requests[0].init.signal.aborted, true)
  await settle(run.requests[1], { app_version: 'latest', logs: [] })
  await latest
  run.requests[0].reject(new Error('Old request failed'))
  await run.initialLoad
  assert.equal(reportData(run).details.app_version, 'latest')
  assert.equal(run.form.loadError.value, '')
  assert.equal(run.form.loading.value, false)
})

test('copy is blocked while details load, shares no duplicate operation, and reports success only after clipboard completion', async t => {
  const clipboard = deferred()
  const run = setup(t, { copyText: () => clipboard.promise })
  await run.form.copyReport()
  assert.equal(run.copies.length, 0)
  await settle(run.requests[0], { app_version: '1.2.3', logs: [] })
  const pending = run.form.copyReport()
  assert.equal(run.form.copying.value, true)
  assert.equal(run.form.copyStatus.value, '')
  await run.form.copyReport()
  assert.equal(run.copies.length, 1)
  clipboard.resolve()
  await pending
  assert.equal(run.form.copying.value, false)
  assert.match(run.form.copyStatus.value, /Issue report copied/)
  assert.equal(run.form.copyError.value, '')
})

test('clipboard rejection preserves the report and offers manual copying without a false success', async t => {
  const run = setup(t, { copyText: async () => { throw new Error('Clipboard permission denied') } })
  await settle(run.requests[0], { app_version: '1.2.3', logs: [] })
  run.form.happened.value = 'Useful issue details'
  await nextTick()
  const before = run.form.report.value
  await run.form.copyReport()
  assert.equal(run.form.copying.value, false)
  assert.equal(run.form.copyStatus.value, '')
  assert.match(run.form.copyError.value, /Preview report.*manually/)
  assert.equal(run.form.report.value, before)
})

test('editing during clipboard completion identifies the copied snapshot and a subsequent edit clears obsolete feedback', async t => {
  const clipboard = deferred()
  const run = setup(t, { copyText: () => clipboard.promise })
  await settle(run.requests[0], { app_version: '1.2.3', logs: [] })
  run.form.happened.value = 'Original description'
  await nextTick()
  const pending = run.form.copyReport()
  run.form.happened.value = 'Updated description'
  await nextTick()
  clipboard.resolve()
  await pending
  assert.equal(JSON.parse(run.copies[0]).happened, 'Original description')
  assert.match(run.form.copyStatus.value, /earlier report was copied/)
  run.form.expected.value = 'New expected behavior'
  await nextTick()
  assert.equal(run.form.copyStatus.value, '')
  assert.equal(run.form.copyError.value, '')
})
