param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111",
    [string]$LessonName = "Plants Basics",
    [string]$Topic = "Plants",
    [int]$DurationMinutes = 35,
    [string]$LessonText = "Lesson Title: Plants Basics`nObjective: Students understand plant parts.`nActivities: Discussion and drawing."
)

$body = @{
    whatsapp_number = $WhatsappNumber
    lesson_name = $LessonName
    topic = $Topic
    duration_minutes = $DurationMinutes
    lesson_text = $LessonText
} | ConvertTo-Json

Invoke-RestMethod -Method Post "$BaseUrl/lesson/save" -ContentType "application/json" -Body $body
