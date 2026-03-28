param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$From = "+15550002222",
    [string]$TeacherName = "Anurag",
    [string]$DefaultGrade = "5",
    [string]$DefaultSubject = "Science",
    [string]$PreferredLanguage = "English"
)

$messages = @(
    "3",
    $TeacherName,
    $DefaultGrade,
    $DefaultSubject,
    $PreferredLanguage
)

foreach ($message in $messages) {
    $body = @{
        from = $From
        body = $message
    } | ConvertTo-Json

    Invoke-RestMethod -Method Post "$BaseUrl/webhook/whatsapp" -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 10
}
