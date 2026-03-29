param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$From = "+15550002222",
    [switch]$CreateProfileFirst,
    [string]$TeacherName = "Anurag",
    [string]$DefaultGrade = "5",
    [string]$DefaultSubject = "Science",
    [string]$PreferredLanguage = "English",
    [string]$Topic = "Plants",
    [string]$Duration = "35",
    [string]$LessonName = "Plants Basics"
)

function Send-WebhookMessage {
    param(
        [string]$Message
    )

    $body = @{
        from = $From
        body = $Message
    } | ConvertTo-Json

    Invoke-RestMethod -Method Post "$BaseUrl/webhook/whatsapp" -ContentType "application/json" -Body $body
}

if ($CreateProfileFirst) {
    $profileMessages = @(
        "3",
        $TeacherName,
        $DefaultGrade,
        $DefaultSubject,
        $PreferredLanguage
    )

    foreach ($message in $profileMessages) {
        [pscustomobject]@{
            sent = $message
            response = Send-WebhookMessage -Message $message
        }
    }
}

$lessonMessages = @(
    "1",
    $Topic,
    $Duration,
    "1",
    $LessonName
)

foreach ($message in $lessonMessages) {
    [pscustomobject]@{
        sent = $message
        response = Send-WebhookMessage -Message $message
    }
}
