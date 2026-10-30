# Cek apakah bot sedang nyala. Jalankan:
#   powershell -ExecutionPolicy Bypass -File status_bot.ps1
$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'bot\.py' }
$port = Get-NetTCPConnection -LocalPort 49231 -State Listen -ErrorAction SilentlyContinue

if ($proc) {
    $proc | ForEach-Object { Write-Host ("BOT NYALA  : PID {0} ({1}), mulai {2}" -f $_.ProcessId, $_.Name, $_.CreationDate) }
    if ($port) { Write-Host "Kunci 49231: LISTENING (sehat)" } else { Write-Host "Kunci 49231: tidak listening (aneh - cek bot.log)" }
    if (($proc | Measure-Object).Count -gt 1) { Write-Host "PERINGATAN : lebih dari satu instance jalan!" }
} else {
    Write-Host "BOT MATI   : tidak ada proses bot."
    Write-Host "Nyalakan   : powershell -ExecutionPolicy Bypass -File restart_bot.ps1"
}
