MAIN_MENU = """Reply with:
1 → New Lesson
2 → My Lessons
3 → All Lessons
4 → My Profile"""

SAVE_MENU = """Reply:
1 → Save Lesson
2 → Cancel"""

INVALID_DURATION = "Please enter class duration in minutes, for example 35."
LESSON_NOT_FOUND = "I could not find that lesson. Please try another lesson name."
LESSON_LOOKUP_EXIT_HINT = "Reply with the exact lesson name, or send 0 to return to the main menu."

ALL_LESSONS_EMPTY = "You do not have any saved lessons yet."
ALL_LESSONS_LIST_PREFIX = "Here are all your saved lessons:"
ALL_LESSONS_SELECTION_PROMPT = "Reply with the exact lesson name to view it, or send 0 to return to the main menu."

DUPLICATE_LESSON_NAME = (
    "A lesson with this name already exists. Please enter another lesson name."
)

PROFILE_START = "Let us set up your profile. What is your name?"
PROFILE_NAME_PROMPT = "Please enter your name."
PROFILE_GRADE_PROMPT = "What is your default grade/class?"
PROFILE_SUBJECT_PROMPT = "What subject do you teach?"
PROFILE_LANGUAGE_PROMPT = 'Please enter preferred language. Reply with "English" unless configured otherwise.'
PROFILE_LANGUAGE_INVALID = 'Preferred language is not supported right now. Please enter English.'
PROFILE_SAVED = "Your profile has been saved."

NEW_LESSON_WITHOUT_PROFILE = (
    "Please complete your profile first.\n"
    "What is your name?"
)
NEW_LESSON_TOPIC_PROMPT = "What lesson topic would you like to teach?"
NEW_LESSON_TOPIC_INVALID = "Please enter a lesson topic."
NEW_LESSON_SAVE_PROMPT_PREFIX = "Here is your generated lesson plan:"
NEW_LESSON_NAME_PROMPT = "Please enter a name for this lesson."
NEW_LESSON_NAME_INVALID = "Lesson name cannot be blank. Please enter a lesson name."
LESSON_SAVED = "Your lesson has been saved."
LESSON_CANCELLED = "Lesson creation was cancelled."

RETRIEVE_LESSON_NAME_PROMPT = "Please enter the exact lesson name. Send 0 to return to the main menu."
RETRIEVE_LESSON_NAME_INVALID = "Lesson name cannot be blank. Please enter the exact lesson name, or send 0 to return to the main menu."

INVALID_MAIN_MENU = f"I did not understand that.\n{MAIN_MENU}"
INVALID_SAVE_MENU = f"I did not understand that.\n{SAVE_MENU}"

PROFILE_UPDATED = "Let us update your profile. What is your name?"