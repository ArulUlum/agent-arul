# Daftarkan bot agar jalan otomatis saat Anda login — TANPA butuh admin.
# Menaruh launcher tersembunyi (pythonw, tanpa jendela console) di folder Startup.
# Jalankan:  powershell -ExecutionPolicy Bypass -File install_startup.ps1
$ErrorActionPreference = 'Stop'

$proj = Split-Path -Parent $MyInvocation.MyCommand.Path

# pythonw dari interpreter yang sama dengan `python` di PATH (tanpa jendela console).
$pyw = & python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"
if (-not (Test-Path $pyw)) { throw "pythonw.exe tidak ditemukan di: $pyw" }

$startup = [Environment]::GetFolderPath('Startup')
$vbsPath = Join-Path $startup 'TelegramLaptopBot.vbs'

# VBS kecil: set folder kerja ke proyek, lalu jalankan bot tersembunyi (window style 0).
$vbs = @"
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$proj"
sh.Run """$pyw"" ""bot.py""", 0, False
"@
Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII

Write-Host "Proyek   : $proj"
Write-Host "pythonw  : $pyw"
Write-Host "Launcher : $vbsPath"
Write-Host ""
Write-Host "OK: bot akan jalan otomatis saat Anda login Windows."
Write-Host "Mulai sekarang juga (tanpa logout): wscript `"$vbsPath`""
Write-Host "Hapus auto-start nanti            : powershell -ExecutionPolicy Bypass -File uninstall_startup.ps1"
