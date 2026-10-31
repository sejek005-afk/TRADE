# حذف فقط تسک «NeuroTraderPro» و توقف فقط فرایندهای همین موتور.
$TaskName = "NeuroTraderPro"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "تسک $TaskName حذف شد."
}
& "$PSScriptRoot\stop.ps1"
