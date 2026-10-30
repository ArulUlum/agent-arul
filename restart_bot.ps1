# Restart bot: hentikan instance yang jalan, lalu mulai lagi (tersembunyi, kode terbaru).
# Jalankan:  powershell -ExecutionPolicy Bypass -File restart_bot.ps1
$ErrorActionPreference = 'SilentlyContinue'

# 1) Hentikan instance bot yang sedang berjalan.
$stopped = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'bot\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ("Dihentikan PID {0}" -f $_.ProcessId); $stopped++ }
if ($stopped -eq 0) { Write-Host "Tidak ada instance lama yang jalan." }
Start-Sleep -Seconds 1

# 2) Mulai lagi lewat launcher tersembunyi (pythonw, tanpa console).
$vbs = Join-Path ([Environment]::GetFolderPath('Startup')) 'TelegramLaptopBot.vbs'
if (Test-Path $vbs) {
    & wscript $vbs
    Write-Host "Bot dijalankan lagi (latar belakang)."
} else {
    Write-Host "Launcher belum ada. Jalankan dulu: powershell -ExecutionPolicy Bypass -File install_startup.ps1"
}
