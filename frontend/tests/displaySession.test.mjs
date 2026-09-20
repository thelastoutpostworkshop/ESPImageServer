import test from 'node:test'
import assert from 'node:assert/strict'
import { displayConnectionLabel, sessionDisplayId } from '../src/displaySession.js'

const remembered = { id: 'remembered', online: false, seen_this_session: false }
const offline = { id: 'offline', online: false, seen_this_session: true }
const online = { id: 'online', online: true, seen_this_session: true }

test('connection labels distinguish remembered displays from session disconnects', () => {
  assert.equal(displayConnectionLabel(remembered), 'Not seen this session')
  assert.equal(displayConnectionLabel(offline), 'Offline')
  assert.equal(displayConnectionLabel(online), 'Online')
})

test('startup waits rather than selecting a remembered display', () => {
  assert.equal(sessionDisplayId([remembered], remembered.id, true), '')
  assert.equal(sessionDisplayId([remembered], '', true), '')
})

test('an online display takes priority over remembered or offline selections', () => {
  for (const id of ['', remembered.id, offline.id, online.id]) {
    assert.equal(sessionDisplayId([remembered, offline, online], id), online.id)
  }
})

test('offline session selections and explicit saved-profile management remain available', () => {
  assert.equal(sessionDisplayId([offline], offline.id, true), offline.id)
  assert.equal(sessionDisplayId([remembered], remembered.id), remembered.id)
  assert.equal(sessionDisplayId([], remembered.id), '')
})
