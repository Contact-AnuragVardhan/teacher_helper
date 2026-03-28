param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$From = "+15550002222",
    [string]$Topic = "Plants",
    [string]$Duration = "35",
    [string]$LessonName = "Plants Basics"
)

$messages = @(
    "1",
    $Topic,
    $Duration,
    "1",
    $LessonName
)

foreach ($message in $messages) {
    $body = @{
        from = $From
        body = $message
    } | ConvertTo-Json

    Invoke-RestMethod -Method Post "$BaseUrl/webhook/whatsapp" -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 10
}
