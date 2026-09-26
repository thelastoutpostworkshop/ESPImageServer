import test from 'node:test'
import assert from 'node:assert/strict'
import { compareVersions, firmwareStatus } from '../src/firmwareStatus.js'
test('firmware versions compare numerically, including prereleases and build metadata', () => {
  for (const [a, b, expected] of [['1.1.10','1.1.9',1], ['1.1.4','1.1.4+build',0], ['1.1.4-rc.10','1.1.4-rc.2',1],
    ['1.1.4-rc','1.1.4',-1], ['2.0.0','10.0.0',-1], ['invalid','1.1.4',null]]) assert.equal(compareVersions(a,b), expected)
})

test('GitHub preview flag is always excluded even when the version looks stable', () => {
  const identity = { board_target: 'CHEAP_YELLOW_DISPLAY', firmware_version: '1.1.4' }
  const releases = { checkedAt: 'today', packages: [{ board: identity.board_target, version: '1.1.5', prerelease: true }] }
  assert.equal(firmwareStatus(identity, releases).kind, 'missing')
  assert.equal(firmwareStatus(identity, { ...releases, includePrereleases: true }).kind, 'missing')
})
test('update status uses only validated stable packages for the identified board', () => {
  const identity = { board_target:'JC4827W543', firmware_version:'1.1.3' }
  const library = {checkedAt:'today',packages:[{board:'OTHER',version:'9.0.0'}, {board:'JC4827W543',version:'2.0.0-beta'}, {board:'JC4827W543',version:'1.1.4'}]}
  assert.equal(firmwareStatus(identity, library).latest.version,'1.1.4')
  assert.equal(firmwareStatus(identity, library).kind,'update')
  assert.equal(firmwareStatus({...identity,firmware_version:'1.1.4'}, library).kind,'current')
  assert.equal(firmwareStatus({...identity,firmware_version:'1.1.5'}, library).kind,'newer')
  assert.equal(firmwareStatus(identity, {...library,error:'Offline drive'}).kind,'unknown')
  assert.equal(firmwareStatus(identity, {...library,checkedAt:null}).kind,'unknown')
  assert.equal(firmwareStatus(identity, {...library,packages:[]}).kind,'missing')
})
