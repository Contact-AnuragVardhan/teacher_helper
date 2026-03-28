param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

Invoke-RestMethod -Method Get "$BaseUrl/health" | ConvertTo-Json -Depth 10
