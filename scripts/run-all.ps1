param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== Health =="
& "$scriptRoot\01-health.ps1" -BaseUrl $BaseUrl

Write-Host "== Upsert Teacher =="
& "$scriptRoot\02-upsert-teacher.ps1" -BaseUrl $BaseUrl

Write-Host "== Get Teacher =="
& "$scriptRoot\03-get-teacher.ps1" -BaseUrl $BaseUrl

Write-Host "== Generate Lesson =="
& "$scriptRoot\04-generate-lesson.ps1" -BaseUrl $BaseUrl

Write-Host "== Save Lesson =="
& "$scriptRoot\05-save-lesson.ps1" -BaseUrl $BaseUrl

Write-Host "== Search Lesson =="
& "$scriptRoot\06-search-lesson.ps1" -BaseUrl $BaseUrl

Write-Host "== Webhook Profile Flow =="
& "$scriptRoot\07-webhook-profile-flow.ps1" -BaseUrl $BaseUrl

Write-Host "== Webhook Lesson Flow =="
& "$scriptRoot\08-webhook-lesson-flow.ps1" -BaseUrl $BaseUrl
