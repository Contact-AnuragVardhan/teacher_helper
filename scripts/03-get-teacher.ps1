param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111"
)

$encodedWhatsapp = [System.Uri]::EscapeDataString($WhatsappNumber)

Invoke-RestMethod -Method Get "$BaseUrl/teacher/$encodedWhatsapp"
