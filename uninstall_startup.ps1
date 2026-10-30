# Hapus auto-start bot (membatalkan install_startup.ps1). Tanpa admin.
# Jalankan:  powershell -ExecutionPolicy Bypass -File uninstall_startup.ps1
$ErrorActionPreference = 'Stop'

$startup = [Environment]::GetFolderPath('Startup')
$vbsPath = Join-Path $startup 'TelegramLaptopBot.vbs'

if (Test-Path $vbsPath) {
    Remove-Item $vbsPath -Force
    Write-Host "OK: launcher auto-start dihapus ($vbsPath)."
} else {
    Write-Host "Tidak ada launcher auto-start. Tidak ada yang dihapus."
}

# Hentikan proses bot yang sedang berjalan (pythonw menjalankan bot.py), bila ada.
$killed = 0
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -match 'bot\.py') {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}
if ($killed -gt 0) { Write-Host "Menghentikan $killed proses bot yang sedang jalan." }
Write-Host "Selesai. Bot tidak lagi jalan otomatis."
