import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

// Native dependency packaging is a later milestone. Management-only developer
// startup must not invoke PowerShell on Linux or macOS.
if (process.platform === 'win32') {
  // CI runs npm from PowerShell 7. Windows PowerShell 5.1 must discover its
  // own modules rather than inheriting PowerShell 7's incompatible module path.
  // Environment variable names are case-insensitive on Windows.
  const env = Object.fromEntries(Object.entries(process.env)
    .filter(([name]) => name.toLowerCase() !== 'psmodulepath'))
  const result = spawnSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    fileURLToPath(new URL('./prepare-esptool.ps1', import.meta.url))], { stdio: 'inherit', windowsHide: true, env })
  if (result.error) console.error(result.error.message)
  process.exitCode = result.status ?? 1
} else {
  console.log('Automatic esptool preparation is currently Windows-only. Desktop management can start; native USB tooling is not bundled yet.')
}
