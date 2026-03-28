param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WhatsappNumber = "+15550001111",
    [string]$TeacherName = "Anurag",
    [string]$DefaultGrade = "5",
    [string]$DefaultSubject = "Science",
    [string]$PreferredLanguage = "English"
)

$body = @{
    whatsapp_number = $WhatsappNumber
    teacher_name = $TeacherName
    default_grade = $DefaultGrade
    default_subject = $DefaultSubject
    preferred_language = $PreferredLanguage
} | ConvertTo-Json

Invoke-RestMethod -Method Post "$BaseUrl/teacher" -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 10
