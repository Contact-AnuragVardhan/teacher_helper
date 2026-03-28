param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111"
)

Invoke-RestMethod -Method Get "$BaseUrl/teacher/$WhatsappNumber" | ConvertTo-Json -Depth 10
