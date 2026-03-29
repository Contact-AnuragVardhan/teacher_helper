param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ApiWhatsappNumber = "+15550001111",
    [string]$WebhookWhatsappNumber = "+15550002222",
    [string]$TeacherName = "Anurag",
    [string]$DefaultGrade = "5",
    [string]$DefaultSubject = "Science",
    [string]$PreferredLanguage = "English",
    [string]$Topic = "Plants",
    [int]$DurationMinutes = 35,
    [string]$LessonName = ("Plants Basics {0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")),
    [switch]$IngestSampleData
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
$dbPath = Join-Path $projectRoot "teacher_helper.db"
$sampleDataPath = Join-Path $projectRoot "sample_data"

function Assert-LocalSchemaReady {
    if (-not (Test-Path $dbPath)) {
        return
    }

    try {
        $pythonCommand = @'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ncert_content'")
row = cur.fetchone()
conn.close()
sys.exit(0 if row else 2)
'@

        $pythonCommand | python - $dbPath
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 2) {
            throw "Missing table 'ncert_content'. Run 'alembic upgrade head' before running this smoke test."
        }
        if ($exitCode -ne 0) {
            throw "Schema validation failed."
        }
    }
    catch [System.Management.Automation.RuntimeException] {
        throw
    }
    catch {
        Write-Warning "Could not validate local SQLite schema automatically: $($_.Exception.Message)"
        Write-Warning "If lesson generation returns HTTP 500, run 'alembic upgrade head' first."
    }
}

Assert-LocalSchemaReady

if ($IngestSampleData) {
    Write-Host "== Ingest NCERT Sample Data =="
    & "$scriptRoot\09-ingest-ncert.ps1" -Directory $sampleDataPath -TruncateFirst |
        ConvertTo-Json -Depth 10
}

Write-Host "== Health =="
& "$scriptRoot\01-health.ps1" -BaseUrl $BaseUrl | ConvertTo-Json -Depth 10

Write-Host "== Upsert Teacher =="
& "$scriptRoot\02-upsert-teacher.ps1" `
    -BaseUrl $BaseUrl `
    -WhatsappNumber $ApiWhatsappNumber `
    -TeacherName $TeacherName `
    -DefaultGrade $DefaultGrade `
    -DefaultSubject $DefaultSubject `
    -PreferredLanguage $PreferredLanguage |
    ConvertTo-Json -Depth 10

Write-Host "== Get Teacher =="
& "$scriptRoot\03-get-teacher.ps1" -BaseUrl $BaseUrl -WhatsappNumber $ApiWhatsappNumber |
    ConvertTo-Json -Depth 10

Write-Host "== Generate Lesson =="
$generatedLesson = & "$scriptRoot\04-generate-lesson.ps1" `
    -BaseUrl $BaseUrl `
    -WhatsappNumber $ApiWhatsappNumber `
    -Topic $Topic `
    -DurationMinutes $DurationMinutes
$generatedLesson | ConvertTo-Json -Depth 10

Write-Host "== Save Lesson =="
& "$scriptRoot\05-save-lesson.ps1" `
    -BaseUrl $BaseUrl `
    -WhatsappNumber $ApiWhatsappNumber `
    -LessonName $LessonName `
    -Topic $Topic `
    -DurationMinutes $DurationMinutes `
    -LessonText $generatedLesson.lesson_text |
    ConvertTo-Json -Depth 10

Write-Host "== Search Lesson =="
& "$scriptRoot\06-search-lesson.ps1" `
    -BaseUrl $BaseUrl `
    -WhatsappNumber $ApiWhatsappNumber `
    -LessonName $LessonName |
    ConvertTo-Json -Depth 10

Write-Host "== Webhook Profile Flow =="
& "$scriptRoot\07-webhook-profile-flow.ps1" `
    -BaseUrl $BaseUrl `
    -From $WebhookWhatsappNumber `
    -TeacherName $TeacherName `
    -DefaultGrade $DefaultGrade `
    -DefaultSubject $DefaultSubject `
    -PreferredLanguage $PreferredLanguage |
    ConvertTo-Json -Depth 10

Write-Host "== Webhook Lesson Flow =="
& "$scriptRoot\08-webhook-lesson-flow.ps1" `
    -BaseUrl $BaseUrl `
    -From $WebhookWhatsappNumber `
    -Topic $Topic `
    -Duration $DurationMinutes `
    -LessonName $LessonName |
    ConvertTo-Json -Depth 10

