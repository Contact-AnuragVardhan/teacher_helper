@echo off
setlocal
set "PS1=%TEMP%\test_library_api_%RANDOM%.ps1"
powershell -NoProfile -Command "$n=(Select-String -Path '%~f0' -Pattern '^__POWERSHELL__$').LineNumber; (Get-Content '%~f0' | Select-Object -Skip $n) | Set-Content '%PS1%'"
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "EXITCODE=%ERRORLEVEL%"
del "%PS1%" >nul 2>&1
pause
exit /b %EXITCODE%
__POWERSHELL__
$ErrorActionPreference = 'Stop'
$baseUrl = 'https://teacher-helper-u1pr.onrender.com'

function Show-Block([string]$title) {
    Write-Host ''
    Write-Host ('=' * 90)
    Write-Host $title
    Write-Host ('=' * 90)
}

function Invoke-Step {
    param(
        [string]$Title,
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null
    )

    Show-Block $Title
    Write-Host "$Method $Uri"

    try {
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 20
            Write-Host ''
            Write-Host 'Request Body:'
            Write-Host $json
            $response = Invoke-RestMethod -Method $Method -Uri $Uri -ContentType 'application/json' -Body $json
        }
        else {
            $response = Invoke-RestMethod -Method $Method -Uri $Uri
        }

        Write-Host ''
        Write-Host 'Response:'
        Write-Host ($response | ConvertTo-Json -Depth 20)
        return $response
    }
    catch {
        $statusCode = $null
        $bodyText = $null

        try {
            $statusCode = [int]$_.Exception.Response.StatusCode
        } catch {}

        try {
            $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
            $bodyText = $reader.ReadToEnd()
        } catch {
            $bodyText = $_.ToString()
        }

        Write-Host ''
        Write-Host "FAILED. Status: $statusCode"
        if ($bodyText) {
            Write-Host $bodyText
        }
        throw
    }
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Get-ItemCount($response) {
    if ($null -eq $response.items) {
        return 0
    }
    return @($response.items).Count
}

function Get-LessonNames($response) {
    if ($null -eq $response.items) {
        return @()
    }
    return @($response.items | ForEach-Object { $_.lesson_name })
}

function Get-TeacherIds($response) {
    if ($null -eq $response.items) {
        return @()
    }
    return @($response.items | ForEach-Object { $_.teacher_id })
}

$health = Invoke-Step -Title 'Health Check' -Method 'GET' -Uri "$baseUrl/health"

$randPhone = Get-Random -Minimum 1000000 -Maximum 9999999

$teacherOneRequest = @{
    whatsapp_number = "+1555$randPhone"
    teacher_name = "Anurag One"
    default_grade = "6"
    default_subject = "Science"
    preferred_language = "English"
}

$teacherTwoRequest = @{
    whatsapp_number = "+1666$randPhone"
    teacher_name = "Anurag Two"
    default_grade = "6"
    default_subject = "Science"
    preferred_language = "English"
}

$teacherOne = Invoke-Step -Title 'Create Teacher One' -Method 'POST' -Uri "$baseUrl/teacher" -Body $teacherOneRequest
$teacherTwo = Invoke-Step -Title 'Create Teacher Two' -Method 'POST' -Uri "$baseUrl/teacher" -Body $teacherTwoRequest

Assert-True ($null -ne $teacherOne.id) 'Teacher one id not found in /teacher response.'
Assert-True ($null -ne $teacherTwo.id) 'Teacher two id not found in /teacher response.'

$teacherOneId = 'teacher-{0:d3}' -f [int]$teacherOne.id
$teacherTwoId = 'teacher-{0:d3}' -f [int]$teacherTwo.id

$lessonOneName = "Components_of_Food_Intro_$randPhone"
$lessonTwoName = "Plant_Life_Intro_$randPhone"
$lessonThreeName = "Fractions_Intro_$randPhone"
$updatedLessonOneName = "Components_of_Food_Updated_$randPhone"

Write-Host ''
Write-Host "Using teacher_id values: $teacherOneId and $teacherTwoId"

$saveRequestOne = @{
    teacher_id = $teacherOneId
    lesson_name = $lessonOneName
    grade = "6"
    subject = "Science"
    topic = "Components of Food"
    duration_minutes = 40
    source_type = "ncert_syllabus"
    source_reference = @{
        grade = "6"
        subject = "Science"
        topic_name = "Components of Food"
    }
    lesson_json = @{
        lesson_title = "Grade 6 Science - Components of Food"
        objective = "Students understand major nutrients and balanced diet."
        opening = "Ask students what they ate today."
        main_teaching = "Explain nutrients, balanced diet, and deficiency diseases."
        activity = "Students sort foods into nutrient groups."
        qa = @(
            "What is a balanced diet?"
            "Why do we need nutrients?"
            "Name one deficiency disease."
        )
        closing = "Summarize healthy food choices."
    }
}

$saveRequestTwo = @{
    teacher_id = $teacherOneId
    lesson_name = $lessonTwoName
    grade = "6"
    subject = "Science"
    topic = "Plant Life"
    duration_minutes = 35
    source_type = "generated"
    source_reference = @{
        grade = "6"
        subject = "Science"
        topic_name = "Plant Life"
    }
    lesson_json = @{
        lesson_title = "Grade 6 Science - Plant Life"
        objective = "Students understand plant parts."
        opening = "Ask students to name a plant."
        main_teaching = "Explain roots, stem, leaf, and flower."
        activity = "Label plant parts."
        qa = @(
            "What do roots do?"
            "What does a leaf do?"
        )
        closing = "Summarize plant parts."
    }
}

$saveRequestThree = @{
    teacher_id = $teacherTwoId
    lesson_name = $lessonThreeName
    grade = "6"
    subject = "Mathematics"
    topic = "Fractions"
    duration_minutes = 30
    source_type = "generated"
    source_reference = @{
        grade = "6"
        subject = "Mathematics"
        topic_name = "Fractions"
    }
    lesson_json = @{
        lesson_title = "Grade 6 Mathematics - Fractions"
        objective = "Students understand basic fractions."
        opening = "Ask students where they see fractions."
        main_teaching = "Explain numerator and denominator."
        activity = "Shade fraction parts."
        qa = @(
            "What is a fraction?"
            "What is a numerator?"
        )
        closing = "Summarize fractions."
    }
}

$saveResponseOne = Invoke-Step -Title 'POST /api/library/lessons - lesson one' -Method 'POST' -Uri "$baseUrl/api/library/lessons" -Body $saveRequestOne
$saveResponseTwo = Invoke-Step -Title 'POST /api/library/lessons - lesson two' -Method 'POST' -Uri "$baseUrl/api/library/lessons" -Body $saveRequestTwo
$saveResponseThree = Invoke-Step -Title 'POST /api/library/lessons - lesson three' -Method 'POST' -Uri "$baseUrl/api/library/lessons" -Body $saveRequestThree

Assert-True ($null -ne $saveResponseOne.lesson_id) 'lesson_id not found in first POST response.'
Assert-True ($null -ne $saveResponseTwo.lesson_id) 'lesson_id not found in second POST response.'
Assert-True ($null -ne $saveResponseThree.lesson_id) 'lesson_id not found in third POST response.'

$lessonIdOne = [string]$saveResponseOne.lesson_id

$getResponse = Invoke-Step -Title 'GET /api/library/lessons/{lesson_id}' -Method 'GET' -Uri "$baseUrl/api/library/lessons/$lessonIdOne"

$searchAllResponse = Invoke-Step -Title 'GET /api/library/search with no params' -Method 'GET' -Uri "$baseUrl/api/library/search"
$searchTeacherOnlyResponse = Invoke-Step -Title 'GET /api/library/search by teacher_id only' -Method 'GET' -Uri "$baseUrl/api/library/search?teacher_id=$teacherOneId"
$searchTopicOnlyResponse = Invoke-Step -Title 'GET /api/library/search by topic only' -Method 'GET' -Uri "$baseUrl/api/library/search?topic=Components%20of%20Food"
$searchGradeSubjectResponse = Invoke-Step -Title 'GET /api/library/search by grade and subject' -Method 'GET' -Uri "$baseUrl/api/library/search?grade=6&subject=Science"
$searchTeacherTopicResponse = Invoke-Step -Title 'GET /api/library/search by teacher_id and topic' -Method 'GET' -Uri "$baseUrl/api/library/search?teacher_id=$teacherOneId&topic=Plant%20Life"
$searchMultiFilterResponse = Invoke-Step -Title 'GET /api/library/search by multiple filters' -Method 'GET' -Uri "$baseUrl/api/library/search?teacher_id=$teacherOneId&lesson_name=$lessonOneName&grade=6&subject=Science&topic=Components%20of%20Food"

$updateRequest = @{
    lesson_name = $updatedLessonOneName
    source_type = "ncert_syllabus"
    source_reference = @{
        grade = "6"
        subject = "Science"
        topic_name = "Components of Food"
    }
    lesson_json = @{
        lesson_title = "Grade 6 Science - Components of Food Updated"
        objective = "Students identify nutrients and healthy meals."
        opening = "Ask what healthy foods students ate this week."
        main_teaching = "Explain nutrients, balance, and food choices."
        activity = "Group foods by nutrients."
        qa = @(
            "What is protein?"
            "What is a balanced diet?"
        )
        closing = "Students share one healthy food habit."
    }
}

$updateResponse = Invoke-Step -Title 'PUT /api/library/lessons/{lesson_id}' -Method 'PUT' -Uri "$baseUrl/api/library/lessons/$lessonIdOne" -Body $updateRequest
$confirmResponse = Invoke-Step -Title 'GET /api/library/lessons/{lesson_id} after update' -Method 'GET' -Uri "$baseUrl/api/library/lessons/$lessonIdOne"

Assert-True ($saveResponseOne.success -eq $true) 'First POST /api/library/lessons did not return success=true.'
Assert-True ($saveResponseTwo.success -eq $true) 'Second POST /api/library/lessons did not return success=true.'
Assert-True ($saveResponseThree.success -eq $true) 'Third POST /api/library/lessons did not return success=true.'
Assert-True ($getResponse.lesson_id -eq $lessonIdOne) 'GET /api/library/lessons/{lesson_id} returned unexpected lesson_id.'

$allLessonNames = @(Get-LessonNames $searchAllResponse)
Assert-True ((Get-ItemCount $searchAllResponse) -ge 3) 'GET /api/library/search with no params returned fewer than 3 lessons.'
Assert-True ($allLessonNames -contains $lessonOneName) 'No-param search did not include lesson one.'
Assert-True ($allLessonNames -contains $lessonTwoName) 'No-param search did not include lesson two.'
Assert-True ($allLessonNames -contains $lessonThreeName) 'No-param search did not include lesson three.'

$teacherOnlyLessonNames = @(Get-LessonNames $searchTeacherOnlyResponse)
$teacherOnlyTeacherIds = @(Get-TeacherIds $searchTeacherOnlyResponse)
$uniqueTeacherOnlyTeacherIds = @($teacherOnlyTeacherIds | Select-Object -Unique)
Assert-True ((Get-ItemCount $searchTeacherOnlyResponse) -eq 2) 'teacher_id-only search did not return exactly 2 lessons.'
Assert-True ($teacherOnlyLessonNames -contains $lessonOneName) 'teacher_id-only search missing lesson one.'
Assert-True ($teacherOnlyLessonNames -contains $lessonTwoName) 'teacher_id-only search missing lesson two.'
Assert-True (-not ($teacherOnlyLessonNames -contains $lessonThreeName)) 'teacher_id-only search incorrectly included teacher two lesson.'
Assert-True ($uniqueTeacherOnlyTeacherIds.Count -eq 1) 'teacher_id-only search returned multiple teacher ids.'
Assert-True ($uniqueTeacherOnlyTeacherIds[0] -eq $teacherOneId) 'teacher_id-only search returned wrong teacher id.'

$topicOnlyLessonNames = @(Get-LessonNames $searchTopicOnlyResponse)
Assert-True ((Get-ItemCount $searchTopicOnlyResponse) -ge 1) 'topic-only search returned no lessons.'
Assert-True ($topicOnlyLessonNames -contains $lessonOneName) 'topic-only search missing expected lesson.'
Assert-True (@($searchTopicOnlyResponse.items | Where-Object { $_.topic -ne 'Components of Food' }).Count -eq 0) 'topic-only search returned a non-matching topic.'

$gradeSubjectLessonNames = @(Get-LessonNames $searchGradeSubjectResponse)
Assert-True ((Get-ItemCount $searchGradeSubjectResponse) -ge 2) 'grade+subject search returned too few lessons.'
Assert-True ($gradeSubjectLessonNames -contains $lessonOneName) 'grade+subject search missing lesson one.'
Assert-True ($gradeSubjectLessonNames -contains $lessonTwoName) 'grade+subject search missing lesson two.'
Assert-True (-not ($gradeSubjectLessonNames -contains $lessonThreeName)) 'grade+subject search incorrectly included mathematics lesson.'
Assert-True (@($searchGradeSubjectResponse.items | Where-Object { $_.grade -ne '6' -or $_.subject -ne 'Science' }).Count -eq 0) 'grade+subject search returned a non-matching item.'

$teacherTopicLessonNames = @(Get-LessonNames $searchTeacherTopicResponse)
Assert-True ((Get-ItemCount $searchTeacherTopicResponse) -eq 1) 'teacher_id+topic search did not return exactly 1 lesson.'
Assert-True ($teacherTopicLessonNames -contains $lessonTwoName) 'teacher_id+topic search returned the wrong lesson.'

$multiFilterLessonNames = @(Get-LessonNames $searchMultiFilterResponse)
Assert-True ((Get-ItemCount $searchMultiFilterResponse) -eq 1) 'multi-filter search did not return exactly 1 lesson.'
Assert-True ($multiFilterLessonNames -contains $lessonOneName) 'multi-filter search returned the wrong lesson.'

Assert-True ($updateResponse.success -eq $true) 'PUT /api/library/lessons/{lesson_id} did not return success=true.'
Assert-True ($confirmResponse.lesson_name -eq $updatedLessonOneName) 'Updated lesson_name was not persisted.'
Assert-True ($confirmResponse.lesson_json.lesson_title -eq 'Grade 6 Science - Components of Food Updated') 'Updated lesson_json.lesson_title was not persisted.'

Show-Block 'ALL LIBRARY ENDPOINT TESTS PASSED'
Write-Host "Teacher One Id: $teacherOneId"
Write-Host "Teacher Two Id: $teacherTwoId"
Write-Host "Lesson One Id:  $lessonIdOne"
Write-Host ''
Write-Host 'Tested endpoints and search variants:'
Write-Host "POST $baseUrl/api/library/lessons"
Write-Host "GET  $baseUrl/api/library/lessons/$lessonIdOne"
Write-Host "GET  $baseUrl/api/library/search"
Write-Host "GET  $baseUrl/api/library/search?teacher_id=$teacherOneId"
Write-Host "GET  $baseUrl/api/library/search?topic=Components%%20of%%20Food"
Write-Host "GET  $baseUrl/api/library/search?grade=6&subject=Science"
Write-Host "GET  $baseUrl/api/library/search?teacher_id=$teacherOneId&topic=Plant%%20Life"
Write-Host "GET  $baseUrl/api/library/search?teacher_id=$teacherOneId&lesson_name=$lessonOneName&grade=6&subject=Science&topic=Components%%20of%%20Food"
Write-Host "PUT  $baseUrl/api/library/lessons/$lessonIdOne"