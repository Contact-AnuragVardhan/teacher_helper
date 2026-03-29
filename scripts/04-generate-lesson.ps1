param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111",
    [string]$Topic = "Plants",
    [int]$DurationMinutes = 35
)

$body = @{
    whatsapp_number = $WhatsappNumber
    topic = $Topic
    duration_minutes = $DurationMinutes
} | ConvertTo-Json

Invoke-RestMethod -Method Post "$BaseUrl/lesson/generate" -ContentType "application/json" -Body $body
