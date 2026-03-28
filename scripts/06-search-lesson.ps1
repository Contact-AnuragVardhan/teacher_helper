param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111",
    [string]$LessonName = "Plants Basics"
)

$encodedWhatsapp = [System.Uri]::EscapeDataString($WhatsappNumber)
$encodedLessonName = [System.Uri]::EscapeDataString($LessonName)

Invoke-RestMethod -Method Get "$BaseUrl/lesson/search?whatsapp_number=$encodedWhatsapp&lesson_name=$encodedLessonName" | ConvertTo-Json -Depth 10
