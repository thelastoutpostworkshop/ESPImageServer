export function compareVersions(a, b) {
  const parse = value => /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(value || '')
  const left = parse(a), right = parse(b)
  if (!left || !right) return null
  for (let i = 1; i <= 3; i++) {
    const x = BigInt(left[i]), y = BigInt(right[i])
    if (x !== y) return x > y ? 1 : -1
  }
  if (left[4] === right[4]) return 0
  if (!left[4]) return 1
  if (!right[4]) return -1
  const x = left[4].split('.'), y = right[4].split('.')
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if (x[i] === undefined) return -1
    if (y[i] === undefined) return 1
    if (x[i] === y[i]) continue
    const nx = /^\d+$/.test(x[i]), ny = /^\d+$/.test(y[i])
    if (nx && ny) return BigInt(x[i]) > BigInt(y[i]) ? 1 : -1
    if (nx !== ny) return nx ? -1 : 1
    return x[i] > y[i] ? 1 : -1
  }
  return 0
}

export function firmwareStatus(identity, library) {
  if (!identity || !library?.checkedAt || library.error) return { kind: 'unknown', latest: null }
  const packages = (library.packages || []).filter(p => p.board === identity.board_target &&
    compareVersions(p.version, p.version) === 0 && !p.version.split('+')[0].includes('-'))
    .sort((a, b) => compareVersions(b.version, a.version))
  const latest = packages[0]
  if (!latest) return { kind: 'missing', latest: null }
  const comparison = compareVersions(latest.version, identity.firmware_version)
  return { kind: comparison === null ? 'unknown' : comparison > 0 ? 'update' : comparison === 0 ? 'current' : 'newer', latest }
}
