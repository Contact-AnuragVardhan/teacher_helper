from dataclasses import dataclass, replace
from datetime import datetime
import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import DEFAULT_LANGUAGE, language_key, normalize_language
from app.core.logging import get_logger, log_event
from app.repositories.embedding_content_repository import EmbeddingContentRepository, EmbeddingLessonMatch, EmbeddingSubsection
from app.repositories.lesson_repository import AccessibleLessonSummary, LessonRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.teacher_repository import TeacherRepository
from app.services.lesson_generator import LessonGeneratorService
from app.services.lesson_payload_builder import LessonPayloadBuilder
from app.services.pdf_content_lesson_service import PdfContentLessonService
from app.services.preferred_language_api_service import PreferredLanguageApiService
from app.services.subject_resolver import SubjectResolver
from app.state_machine.states import ConversationState
from app.utils.lesson_title_localization import localize_lesson_display_title
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.text import clean_text, normalize_choice, normalize_grade, parse_duration_minutes

logger = get_logger(__name__)


@dataclass
class ConversationReply:
    reply: str
    current_state: str
    outbound: dict | None = None


TEXT: dict[str, dict[str, str]] = {
    "hindi": {
        "tap_option": "कृपया नीचे एक विकल्प चुनें।",
        "welcome": "नमस्ते! Teacher Helper में आपका स्वागत है। मैं पाठ योजना बनाने, सेव करने और देखने में मदद कर सकता हूँ।",
        "main_menu_unknown": "मैं नया पाठ बनाने, सेव किए गए पाठ देखने या प्रोफ़ाइल अपडेट करने में मदद कर सकता हूँ। कृपया नीचे दिए गए विकल्पों में से एक चुनें।",
        "main_header": "Teacher Helper",
        "main_body": "एक विकल्प चुनें",
        "main_footer": "नीचे एक विकल्प टैप करें",
        "btn_new_lesson": "नया पाठ",
        "btn_all_lessons": "सभी पाठ",
        "btn_profile": "प्रोफ़ाइल",
        "btn_main_menu": "मुख्य मेनू",
        "all_lessons_body_page": "खोलने के लिए पाठ चुनें। पेज {page}/{total_pages}",
        "all_lessons_next": "अगला पेज",
        "all_lessons_previous": "पिछला पेज",
        "new_lesson_without_profile": "कृपया पहले अपनी प्रोफ़ाइल पूरी करें।\nआपका नाम क्या है?",
        "new_lesson_topic_prompt": "आप किस विषय पर पाठ पढ़ाना चाहते हैं? उदाहरण: \"झाँसी की रानी\"",
        "new_lesson_topic_invalid": "कृपया पाठ का विषय लिखें, उदाहरण: \"झाँसी की रानी\"।",
        "new_lesson_grade_prompt": "इस पाठ के लिए ग्रेड/कक्षा लिखें। उदाहरण: 1, 2, 3",
        "new_lesson_subject_prompt": "इस पाठ का विषय/सब्जेक्ट लिखें। उदाहरण: गणित",
        "duration_prompt": "कक्षा की अवधि मिनटों में लिखें। उदाहरण: 35",
        "invalid_duration": "कृपया कक्षा की अवधि मिनटों में लिखें, उदाहरण 35।",
        "generated_lesson_prefix": "यह आपकी तैयार की गई पाठ योजना है:",
        "save_body": "क्या आप इस पाठ को सेव करना चाहते हैं?",
        "save_footer": "एक विकल्प चुनें",
        "btn_save": "पाठ सेव करें",
        "btn_cancel": "रद्द करें",
        "save_invalid": "कृपया एक विकल्प चुनें:\n1 → पाठ सेव करें\n2 → रद्द करें",
        "lesson_cancelled": "पाठ सेव नहीं किया गया।",
        "lesson_name_suggestion_body": "सुझाया गया पाठ नाम:\n{lesson_name}\n\nक्या आप इसी नाम से सेव करना चाहते हैं?",
        "lesson_name_suggestion_footer": "हाँ या नहीं चुनें",
        "lesson_name_suggestion_invalid": "कृपया हाँ चुनें अगर इसी नाम से सेव करना है, या नहीं चुनें अगर अपना नाम लिखना है।",
        "btn_yes": "हाँ",
        "btn_no": "नहीं",
        "lesson_name_prompt": "कृपया इस पाठ का नाम लिखें। उदाहरण: \"झाँसी की रानी\"",
        "lesson_name_invalid": "पाठ का नाम खाली नहीं हो सकता। कृपया पाठ का नाम लिखें, उदाहरण: \"झाँसी की रानी\"।",
        "duplicate_lesson_name": "इस नाम से एक पाठ पहले से मौजूद है। कृपया कोई दूसरा नाम लिखें, उदाहरण \"झाँसी की रानी\"।",
        "lesson_saved": "आपका पाठ सेव हो गया है।",
        "profile_start": "आइए आपकी प्रोफ़ाइल सेट करते हैं। आपका नाम क्या है?",
        "profile_name_prompt": "कृपया अपना नाम लिखें।",
        "profile_school_prompt": "कृपया नीचे दी गई सूची से अपना स्कूल चुनें।",
        "profile_school_invalid": "कृपया सूची से सही स्कूल चुनें।",
        "profile_school_empty": "embeddings_documents में स्कूल सूची नहीं मिली। कृपया अपने स्कूल का नाम लिखें।",
        "profile_school_edit": "वर्तमान स्कूल: {school}\nनया स्कूल चुनें, या रखने के लिए 'same' भेजें।",
        "school_list_header": "स्कूल चुनें",
        "school_list_body": "अपना स्कूल चुनें।",
        "school_list_button": "Schools",
        "school_list_section": "Schools",
        "school_list_footer": "नीचे एक स्कूल टैप करें।",
        "new_lesson_no_school": "पाठ योजना बनाने से पहले कृपया प्रोफ़ाइल अपडेट करके स्कूल चुनें।",
        "lesson_no_match": "इसके लिए कोई lesson/section नहीं मिला: {topic}\n\nकृपया किताब का exact lesson, section या chapter title लिखें।",
        "lesson_summary_intro": "मुझे यह lesson/section मिला:\n{title}\nBook Pages: {pages}\n\nSimple summary:\n{summary}\n\nअब detailed lesson plan के लिए day/subsection चुनें।",
        "lesson_day_header": "Day चुनें",
        "lesson_day_body": "एक day/subsection चुनें।",
        "lesson_day_button": "Lesson Days",
        "lesson_day_section": "Days",
        "lesson_day_footer": "नीचे एक day टैप करें।",
        "lesson_day_invalid": "कृपया सूची से सही day/subsection चुनें।",
        "profile_grade_prompt": "आपकी डिफ़ॉल्ट ग्रेड/कक्षा क्या है? उदाहरण: 1, 2, 3",
        "profile_subject_prompt": "आप कौन सा विषय पढ़ाते हैं? उदाहरण: गणित",
        "profile_language_prompt": "कृपया पसंदीदा भाषा लिखें। विकल्प: {options}",
        "profile_language_invalid": "यह भाषा अभी समर्थित नहीं है। कृपया नीचे दिए गए विकल्पों में से एक लिखें।",
        "profile_saved": "आपकी प्रोफ़ाइल सेव हो गई है।",
        "profile_updated": "आइए आपकी प्रोफ़ाइल अपडेट करते हैं।",
        "current_profile": "वर्तमान प्रोफ़ाइल:\nनाम: {name}\nस्कूल: {school}\nग्रेड: {grade}\nविषय: {subject}\nभाषा: {language}",
        "profile_name_edit": "अपना नाम लिखें, या वर्तमान नाम रखने के लिए 'same', 'सेम' या 'समान' भेजें।",
        "profile_grade_edit": "वर्तमान ग्रेड/कक्षा: {grade}\nनई ग्रेड/कक्षा लिखें, या रखने के लिए 'same', 'सेम' या 'समान' भेजें। उदाहरण: 1, 2, 3",
        "profile_subject_edit": "वर्तमान विषय: {subject}\nनया विषय लिखें, या रखने के लिए 'same', 'सेम' या 'समान' भेजें। उदाहरण: गणित",
        "profile_language_edit": "वर्तमान भाषा: {language}\nनई भाषा लिखें, या रखने के लिए 'same', 'सेम' या 'समान' भेजें। विकल्प: {options}",
        "all_lessons_empty": "आपके पास अभी कोई सेव या साझा किया गया पाठ नहीं है।",
        "all_lessons_reply": "सभी पाठ:\nकृपया नीचे दी गई सूची से एक पाठ चुनें।",
        "all_lessons_header": "सेव किए गए पाठ",
        "all_lessons_body": "खोलने के लिए एक पाठ चुनें।",
        "all_lessons_button": "पाठ देखें",
        "all_lessons_section": "आपके पाठ",
        "all_lessons_footer": "नीचे एक पाठ टैप करें।",
        "all_lessons_fallback": "सभी पाठ:\n{titles}\n\nपाठ खोलने के लिए उसका नंबर भेजें।\nमुख्य मेनू पर लौटने के लिए 0 भेजें।",
        "back_main": "मुख्य मेनू पर वापस।",
        "create_profile_first": "कृपया पहले अपनी प्रोफ़ाइल बनाएँ।",
        "invalid_lesson_number": "अमान्य पाठ नंबर। कृपया सूची से सही पाठ नंबर लिखें।\nमुख्य मेनू पर लौटने के लिए 0 भेजें।",
        "choose_from_list": "कृपया WhatsApp सूची से एक पाठ चुनें, या मुख्य मेनू पर लौटने के लिए 0 भेजें।",
        "enter_lesson_number": "कृपया सूची से पाठ नंबर लिखें।\nमुख्य मेनू पर लौटने के लिए 0 भेजें।",
        "lesson_not_found_try": "मुझे वह पाठ नहीं मिला। कृपया फिर से कोशिश करें।\nमुख्य मेनू पर लौटने के लिए 0 भेजें।",
        "shared_lesson_from": "साझा पाठ भेजने वाले शिक्षक: {teacher_name}",
        "lesson_action_prompt": "कृपया नीचे एक विकल्प चुनें।",
        "lesson_actions_header": "पाठ विकल्प",
        "shared_lesson_body": "यह एक साझा पाठ है।",
        "lesson_actions_body": "इस पाठ के लिए आप क्या करना चाहते हैं?",
        "btn_back": "वापस",
        "btn_share": "साझा करें",
        "btn_delete": "डिलीट",
        "share_prompt": "पाठ साझा करें: {lesson_name}\nकृपया शिक्षक का WhatsApp नंबर देश कोड सहित लिखें। उदाहरण: +15550001111",
        "delete_confirm": "क्या आप सच में '{lesson_name}' को डिलीट करना चाहते हैं?",
        "delete_header": "पाठ डिलीट करें",
        "btn_confirm_delete": "हाँ, डिलीट",
        "that_lesson_missing": "वह पाठ अब उपलब्ध नहीं है।",
        "shared_view_only": "यह साझा पाठ केवल देखने के लिए है।",
        "choose_action": "कृपया नीचे दिए गए पाठ विकल्पों में से एक चुनें।",
        "owner_only_share": "केवल पाठ का मालिक इसे साझा कर सकता है।",
        "recipient_not_found": "मुझे उस WhatsApp नंबर की शिक्षक प्रोफ़ाइल नहीं मिली। कृपया पंजीकृत शिक्षक नंबर लिखें, या वापस जाने के लिए back भेजें।",
        "share_self": "आप अपने आप से पाठ साझा नहीं कर सकते। कृपया किसी दूसरे शिक्षक का WhatsApp नंबर लिखें, या वापस जाने के लिए back भेजें।",
        "share_failed": "मैं वह पाठ साझा नहीं कर पाया। कृपया फिर से कोशिश करें।",
        "share_success": "'{lesson_name}' {teacher_name} के साथ साझा कर दिया गया है।",
        "delete_success": "'{lesson_name}' डिलीट कर दिया गया है।",
    },
    "english": {
        "tap_option": "Please tap one option below.",
        "welcome": "Hello! Welcome to Teacher Helper. I can help you create, save, and view lesson plans.",
        "main_menu_unknown": "I can help with creating a new lesson, viewing all saved lessons, or updating your profile. Please choose one of the options below.",
        "main_header": "Teacher Helper",
        "main_body": "Choose an option",
        "main_footer": "Tap one option below",
        "btn_new_lesson": "New Lesson",
        "btn_all_lessons": "All Lessons",
        "btn_profile": "My Profile",
        "btn_main_menu": "Back to Main Menu",
        "all_lessons_body_page": "Choose a lesson to open. Page {page}/{total_pages}.",
        "all_lessons_next": "Next Page",
        "all_lessons_previous": "Previous Page",
        "new_lesson_without_profile": "Please complete your profile first.\nWhat is your name?",
        "new_lesson_topic_prompt": "What lesson topic would you like to teach? Example: \"Jhansi Ki Rani\"",
        "new_lesson_topic_invalid": "Please enter a lesson topic, for example \"Jhansi Ki Rani\".",
        "new_lesson_grade_prompt": "Please enter the grade/class for this lesson. Example: 1, 2, 3",
        "new_lesson_subject_prompt": "Please enter the subject for this lesson. Example: English",
        "duration_prompt": "Please enter class duration in minutes. Example: 35",
        "invalid_duration": "Please enter class duration in minutes, for example 35.",
        "generated_lesson_prefix": "Here is your generated lesson plan:",
        "save_body": "Do you want to save this lesson?",
        "save_footer": "Choose one option",
        "btn_save": "Save Lesson",
        "btn_cancel": "Cancel",
        "save_invalid": "Please choose one option:\n1 → Save Lesson\n2 → Cancel",
        "lesson_cancelled": "Lesson was not saved.",
        "lesson_name_suggestion_body": "Suggested lesson name:\n{lesson_name}\n\nDo you want to save this lesson with this name?",
        "lesson_name_suggestion_footer": "Choose Yes or No",
        "lesson_name_suggestion_invalid": "Please choose Yes to use the suggested name, or No to enter your own lesson name.",
        "btn_yes": "Yes",
        "btn_no": "No",
        "lesson_name_prompt": "Please enter a name for this lesson. Example: \"Jhansi Ki Rani\"",
        "lesson_name_invalid": "Lesson name cannot be blank. Please enter a lesson name, for example \"Jhansi Ki Rani\".",
        "duplicate_lesson_name": "A lesson with this name already exists. Please enter another lesson name, for example \"Jhansi Ki Rani\".",
        "lesson_saved": "Your lesson has been saved.",
        "profile_start": "Let us set up your profile. What is your name?",
        "profile_name_prompt": "Please enter your name.",
        "profile_school_prompt": "Please choose your school from the list below.",
        "profile_school_invalid": "Please choose a school from the list below.",
        "profile_school_empty": "No school list was found in embeddings_documents. Please type your school name.",
        "profile_school_edit": "Current school: {school}\nChoose a new school from the list, or send 'same' to keep it.",
        "school_list_header": "Choose School",
        "school_list_body": "Select your school.",
        "school_list_button": "Schools",
        "school_list_section": "Schools",
        "school_list_footer": "Tap one school below.",
        "new_lesson_no_school": "Please update your profile and choose your school before creating a lesson plan.",
        "lesson_no_match": "No matching lesson/section was found for: {topic}\n\nPlease type the exact lesson, section, or chapter title from the book.",
        "lesson_summary_intro": "I found this lesson/section:\n{title}\nBook Pages: {pages}\n\nSimple summary:\n{summary}\n\nNow choose the lesson day/subsection for the detailed lesson plan.",
        "lesson_day_header": "Choose Day",
        "lesson_day_body": "Select one day/subsection.",
        "lesson_day_button": "Lesson Days",
        "lesson_day_section": "Days",
        "lesson_day_footer": "Tap one day below.",
        "lesson_day_invalid": "Please choose a valid day/subsection from the list.",
        "profile_grade_prompt": "What is your default grade/class? Example: 1, 2, 3",
        "profile_subject_prompt": "What subject do you teach? Example: English",
        "profile_language_prompt": "Please enter preferred language. Options: {options}",
        "profile_language_invalid": "Preferred language is not supported right now. Please enter one of the configured options shown below.",
        "profile_saved": "Your profile has been saved.",
        "profile_updated": "Let us update your profile.",
        "current_profile": "Current profile:\nName: {name}\nSchool: {school}\nGrade: {grade}\nSubject: {subject}\nLanguage: {language}",
        "profile_name_edit": "Reply with your name, or send 'same' to keep the current value.",
        "profile_grade_edit": "Current grade/class: {grade}\nReply with the new grade/class, or send 'same' to keep it. Example: 1, 2, 3",
        "profile_subject_edit": "Current subject: {subject}\nReply with the new subject, or send 'same' to keep it. Example: English",
        "profile_language_edit": "Current language: {language}\nReply with the new language, or send 'same' to keep it. Options: {options}",
        "all_lessons_empty": "You do not have any saved or shared lessons yet.",
        "all_lessons_reply": "All Lessons:\nPlease choose a lesson from the list below.",
        "all_lessons_header": "Saved Lessons",
        "all_lessons_body": "Choose a lesson to open.",
        "all_lessons_button": "View Lessons",
        "all_lessons_section": "Your Lessons",
        "all_lessons_footer": "Tap one lesson below.",
        "all_lessons_fallback": "All Lessons:\n{titles}\n\nReply with the lesson number to open it.\nSend 0 to return to the main menu.",
        "back_main": "Back to main menu.",
        "create_profile_first": "Please create your profile first.",
        "invalid_lesson_number": "Invalid lesson number. Please enter a valid lesson number from the list.\nSend 0 to return to the main menu.",
        "choose_from_list": "Please choose a lesson from the WhatsApp list, or send 0 to return to the main menu.",
        "enter_lesson_number": "Please enter the lesson number from the list.\nSend 0 to return to the main menu.",
        "lesson_not_found_try": "I could not find that lesson. Please try again.\nSend 0 to return to the main menu.",
        "shared_lesson_from": "Shared lesson from: {teacher_name}",
        "lesson_action_prompt": "Please tap one option below.",
        "lesson_actions_header": "Lesson Actions",
        "shared_lesson_body": "This is a shared lesson.",
        "lesson_actions_body": "Choose what you want to do with this lesson.",
        "btn_back": "Back",
        "btn_share": "Share Lesson",
        "btn_delete": "Delete",
        "share_prompt": "Share Lesson: {lesson_name}\nPlease enter the teacher's WhatsApp number, including country code. Example: +15550001111",
        "delete_confirm": "Are you sure you want to delete '{lesson_name}'?",
        "delete_header": "Delete Lesson",
        "btn_confirm_delete": "Yes, Delete",
        "that_lesson_missing": "That lesson is no longer available.",
        "shared_view_only": "This shared lesson is view-only.",
        "choose_action": "Please choose one of the lesson actions below.",
        "owner_only_share": "Only the lesson owner can share this lesson.",
        "recipient_not_found": "I could not find a teacher profile for that WhatsApp number. Please enter a registered teacher number, or send back to return.",
        "share_self": "You cannot share a lesson with yourself. Please enter another teacher's WhatsApp number, or send back to return.",
        "share_failed": "I could not share that lesson. Please try again.",
        "share_success": "'{lesson_name}' was shared with {teacher_name}.",
        "delete_success": "'{lesson_name}' was deleted.",
    },
    "hinglish": {
        "tap_option": "Neeche ek option tap karein.",
        "welcome": "Namaste! Teacher Helper mein welcome. Main lesson plans create, save aur view karne mein help kar sakta hoon.",
        "main_menu_unknown": "Main new lesson create karne, saved lessons dekhne, ya profile update karne mein help kar sakta hoon. Neeche se ek option choose karein.",
        "main_header": "Teacher Helper",
        "main_body": "Option choose karein",
        "main_footer": "Neeche option tap karein",
        "btn_new_lesson": "Naya Lesson",
        "btn_all_lessons": "All Lessons",
        "btn_profile": "Profile",
        "btn_main_menu": "Main Menu",
        "all_lessons_body_page": "Open karne ke liye lesson choose karein. Page {page}/{total_pages}.",
        "all_lessons_next": "Next Page",
        "all_lessons_previous": "Previous Page",
        "new_lesson_without_profile": "Please pehle apni profile complete karein.\nAapka naam kya hai?",
        "new_lesson_topic_prompt": "Aap kis topic par lesson banana chahte hain? Example: \"Jhansi Ki Rani\"",
        "new_lesson_topic_invalid": "Please lesson topic likhein, example: \"Jhansi Ki Rani\".",
        "new_lesson_grade_prompt": "Is lesson ke liye grade/class likhein. Example: 1, 2, 3",
        "new_lesson_subject_prompt": "Is lesson ka subject likhein. Example: English",
        "duration_prompt": "Class duration minutes mein likhein. Example: 35",
        "invalid_duration": "Please class duration minutes mein likhein, example 35.",
        "generated_lesson_prefix": "Yeh aapka generated lesson plan hai:",
        "save_body": "Kya aap is lesson ko save karna chahte hain?",
        "save_footer": "Ek option choose karein",
        "btn_save": "Save Lesson",
        "btn_cancel": "Cancel",
        "save_invalid": "Please ek option choose karein:\n1 → Save Lesson\n2 → Cancel",
        "lesson_cancelled": "Lesson save nahi kiya gaya.",
        "lesson_name_suggestion_body": "Suggested lesson name:\n{lesson_name}\n\nKya aap isi naam se lesson save karna chahte hain?",
        "lesson_name_suggestion_footer": "Yes ya No choose karein",
        "lesson_name_suggestion_invalid": "Please Yes choose karein suggested name use karne ke liye, ya No choose karein apna lesson name likhne ke liye.",
        "btn_yes": "Yes",
        "btn_no": "No",
        "lesson_name_prompt": "Please is lesson ka naam likhein. Example: \"Jhansi Ki Rani\"",
        "lesson_name_invalid": "Lesson name blank nahi ho sakta. Please lesson name likhein, example \"Jhansi Ki Rani\".",
        "duplicate_lesson_name": "Is naam se lesson already exist karta hai. Please dusra naam likhein, example \"Jhansi Ki Rani\".",
        "lesson_saved": "Aapka lesson save ho gaya hai.",
        "profile_start": "Chaliye profile setup karte hain. Aapka naam kya hai?",
        "profile_name_prompt": "Please apna naam likhein.",
        "profile_school_prompt": "Please neeche list se apna school choose karein.",
        "profile_school_invalid": "Please list se valid school choose karein.",
        "profile_school_empty": "embeddings_documents mein school list nahi mili. Please apna school name type karein.",
        "profile_school_edit": "Current school: {school}\nNew school list se choose karein, ya keep karne ke liye 'same' bhejein.",
        "school_list_header": "Choose School",
        "school_list_body": "Apna school select karein.",
        "school_list_button": "Schools",
        "school_list_section": "Schools",
        "school_list_footer": "Neeche ek school tap karein.",
        "new_lesson_no_school": "Lesson plan create karne se pehle please profile update karke school choose karein.",
        "lesson_no_match": "Is topic ke liye matching lesson/section nahi mila: {topic}\n\nPlease book ka exact lesson, section, ya chapter title type karein.",
        "lesson_summary_intro": "Mujhe yeh lesson/section mila:\n{title}\nBook Pages: {pages}\n\nSimple summary:\n{summary}\n\nAb detailed lesson plan ke liye day/subsection choose karein.",
        "lesson_day_header": "Choose Day",
        "lesson_day_body": "Ek day/subsection select karein.",
        "lesson_day_button": "Lesson Days",
        "lesson_day_section": "Days",
        "lesson_day_footer": "Neeche ek day tap karein.",
        "lesson_day_invalid": "Please list se valid day/subsection choose karein.",
        "profile_grade_prompt": "Aapki default grade/class kya hai? Example: 1, 2, 3",
        "profile_subject_prompt": "Aap kaunsa subject padhate hain? Example: English",
        "profile_language_prompt": "Please preferred language likhein. Options: {options}",
        "profile_language_invalid": "Yeh language abhi supported nahi hai. Please neeche diye options mein se ek likhein.",
        "profile_saved": "Aapki profile save ho gayi hai.",
        "profile_updated": "Chaliye profile update karte hain.",
        "current_profile": "Current profile:\nName: {name}\nSchool: {school}\nGrade: {grade}\nSubject: {subject}\nLanguage: {language}",
        "profile_name_edit": "Apna naam reply karein, ya current value rakhne ke liye 'same' bhejein.",
        "profile_grade_edit": "Current grade/class: {grade}\nNew grade/class likhein, ya keep karne ke liye 'same' bhejein. Example: 1, 2, 3",
        "profile_subject_edit": "Current subject: {subject}\nNew subject likhein, ya keep karne ke liye 'same' bhejein. Example: English",
        "profile_language_edit": "Current language: {language}\nNew language likhein, ya keep karne ke liye 'same' bhejein. Options: {options}",
        "all_lessons_empty": "Aapke paas abhi koi saved ya shared lesson nahi hai.",
        "all_lessons_reply": "All Lessons:\nPlease neeche list se ek lesson choose karein.",
        "all_lessons_header": "Saved Lessons",
        "all_lessons_body": "Open karne ke liye lesson choose karein.",
        "all_lessons_button": "View Lessons",
        "all_lessons_section": "Your Lessons",
        "all_lessons_footer": "Neeche ek lesson tap karein.",
        "all_lessons_fallback": "All Lessons:\n{titles}\n\nLesson open karne ke liye number bhejein.\nMain menu par wapas jane ke liye 0 bhejein.",
        "back_main": "Main menu par wapas.",
        "create_profile_first": "Please pehle apni profile create karein.",
        "invalid_lesson_number": "Invalid lesson number. Please list se valid lesson number likhein.\nMain menu par wapas jane ke liye 0 bhejein.",
        "choose_from_list": "Please WhatsApp list se ek lesson choose karein, ya main menu par wapas jane ke liye 0 bhejein.",
        "enter_lesson_number": "Please list se lesson number likhein.\nMain menu par wapas jane ke liye 0 bhejein.",
        "lesson_not_found_try": "Mujhe woh lesson nahi mila. Please phir try karein.\nMain menu par wapas jane ke liye 0 bhejein.",
        "shared_lesson_from": "Shared lesson from: {teacher_name}",
        "lesson_action_prompt": "Neeche ek option tap karein.",
        "lesson_actions_header": "Lesson Actions",
        "shared_lesson_body": "Yeh shared lesson hai.",
        "lesson_actions_body": "Is lesson ke saath kya karna hai?",
        "btn_back": "Back",
        "btn_share": "Share Lesson",
        "btn_delete": "Delete",
        "share_prompt": "Share Lesson: {lesson_name}\nPlease teacher ka WhatsApp number country code ke saath likhein. Example: +15550001111",
        "delete_confirm": "Kya aap sure hain ki '{lesson_name}' delete karna hai?",
        "delete_header": "Delete Lesson",
        "btn_confirm_delete": "Yes, Delete",
        "that_lesson_missing": "Woh lesson ab available nahi hai.",
        "shared_view_only": "Yeh shared lesson view-only hai.",
        "choose_action": "Please neeche lesson actions mein se ek choose karein.",
        "owner_only_share": "Sirf lesson owner is lesson ko share kar sakta hai.",
        "recipient_not_found": "Mujhe us WhatsApp number ki teacher profile nahi mili. Please registered teacher number likhein, ya back bhejein.",
        "share_self": "Aap lesson apne aap se share nahi kar sakte. Please dusre teacher ka WhatsApp number likhein, ya back bhejein.",
        "share_failed": "Main woh lesson share nahi kar paaya. Please phir try karein.",
        "share_success": "'{lesson_name}' {teacher_name} ke saath share ho gaya hai.",
        "delete_success": "'{lesson_name}' delete ho gaya hai.",
    },
}


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.teacher_repo = TeacherRepository(db)
        self.lesson_repo = LessonRepository(db)
        self.embedding_content_repo = EmbeddingContentRepository(db)
        self.session_repo = SessionRepository(db)
        self.lesson_generator = LessonGeneratorService(db)
        self.pdf_content_lesson_service = PdfContentLessonService(db)
        self.lesson_payload_builder = LessonPayloadBuilder()
        self.subject_resolver = SubjectResolver(self.settings)
        self.preferred_language_api = PreferredLanguageApiService(self.settings)

    def handle_message(self, whatsapp_number: str, incoming_text: str) -> ConversationReply:
        session, was_reset = self.session_repo.get_or_create(whatsapp_number)
        self.session_repo.touch(session)
        if was_reset:
            log_event(logger, "session_stale_reset", whatsapp_number=whatsapp_number)

        state = ConversationState(session.current_state)
        text = clean_text(incoming_text)
        log_event(logger, "conversation_inbound", whatsapp_number=whatsapp_number, state=state.value, body=text)

        choice = normalize_choice(text)
        if state != ConversationState.MAIN_MENU and self._is_main_menu_choice(choice):
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            language = self._teacher_language(teacher, whatsapp_number)
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "back_main"), language)

        handler_map = {
            ConversationState.MAIN_MENU: self._handle_main_menu,
            ConversationState.PROFILE_NAME: self._handle_profile_name,
            ConversationState.PROFILE_GRADE: self._handle_profile_grade,
            ConversationState.PROFILE_SCHOOL: self._handle_profile_school,
            ConversationState.PROFILE_SUBJECT: self._handle_profile_subject,
            ConversationState.PROFILE_LANGUAGE: self._handle_profile_language,
            ConversationState.NEW_LESSON_TOPIC: self._handle_new_lesson_topic,
            ConversationState.NEW_LESSON_GRADE: self._handle_new_lesson_grade,
            ConversationState.NEW_LESSON_DAY: self._handle_new_lesson_day,
            ConversationState.NEW_LESSON_SUBJECT: self._handle_new_lesson_subject,
            ConversationState.NEW_LESSON_DURATION: self._handle_new_lesson_duration,
            ConversationState.NEW_LESSON_CONFIRM_SAVE: self._handle_new_lesson_confirm_save,
            ConversationState.NEW_LESSON_CONFIRM_NAME: self._handle_new_lesson_confirm_name,
            ConversationState.NEW_LESSON_NAME: self._handle_new_lesson_name,
            ConversationState.RETRIEVE_LESSON_NAME: self._handle_retrieve_lesson_name,
            ConversationState.LESSON_ACTION_MENU: self._handle_lesson_action_menu,
            ConversationState.SHARE_LESSON_PHONE: self._handle_share_lesson_phone,
            ConversationState.DELETE_LESSON_CONFIRM: self._handle_delete_lesson_confirm,
        }

        result = handler_map[state](session, whatsapp_number, text)
        log_event(
            logger,
            "conversation_transition",
            whatsapp_number=whatsapp_number,
            from_state=state.value,
            to_state=result.current_state,
        )
        return result

    def _reply(
        self,
        reply: str,
        state: ConversationState,
        outbound: dict | None = None,
    ) -> ConversationReply:
        return ConversationReply(reply=reply, current_state=state.value, outbound=outbound)

    def _text(self, active_language: str | None, key: str, **kwargs) -> str:
        lang = language_key(active_language or self._configured_default_language())
        template = TEXT.get(lang, TEXT["english"]).get(key) or TEXT["english"].get(key) or key
        return template.format(**kwargs)

    def _configured_default_language(self) -> str:
        return self.settings.default_language

    def _localize_validation_error(self, error: str | None, language: str) -> str | None:
        if not error:
            return None
        if error.startswith("Grade must be one of:"):
            allowed = error.split(":", 1)[1].strip().rstrip(".") if ":" in error else ""
            key = language_key(language)
            if key == "hindi":
                return f"ग्रेड इनमें से एक होना चाहिए: {allowed}।"
            if key == "hinglish":
                return f"Grade inmein se ek hona chahiye: {allowed}."
        if error == "Subject cannot be blank.":
            key = language_key(language)
            if key == "hindi":
                return "विषय खाली नहीं हो सकता।"
            if key == "hinglish":
                return "Subject blank nahi ho sakta."
        return error

    def _teacher_language(self, teacher, whatsapp_number: str | None = None) -> str:
        default_language = self._configured_default_language()
        preferred_language = (getattr(teacher, "preferred_language", None) or "").strip()
        if preferred_language:
            normalized_language = normalize_language(preferred_language, default=None)
            if normalized_language and normalized_language.casefold() in self.settings.supported_languages_casefold:
                resolved_language = normalized_language
            else:
                resolved_language = default_language
        else:
            resolved_language = default_language

        # Keep the local profile/default-language resolution above, then ask the
        # Jalta Sitara Hotline API for the latest saved preference. If it differs from
        # the Teacher Helper profile, sync the profile so future requests use it.
        api_language = self._preferred_language_from_api(whatsapp_number or getattr(teacher, "whatsapp_number", ""))
        if api_language:
            if teacher and (getattr(teacher, "preferred_language", "") or "").casefold() != api_language.casefold():
                self.teacher_repo.update_preferred_language(
                    getattr(teacher, "whatsapp_number", whatsapp_number or ""),
                    api_language,
                )
            return api_language

        return resolved_language

    def _preferred_language_from_api(self, whatsapp_number: str | None) -> str | None:
        try:
            result = self.preferred_language_api.fetch_preferred_language(whatsapp_number or "")
            return result.preferred_language if result else None
        except Exception as exc:  # pragma: no cover - defensive; Hotline must not break conversation flow.
            log_event(
                logger,
                "preferred_language_api_fetch_ignored",
                whatsapp_number=whatsapp_number or "",
                error=str(exc),
            )
            return None

    def _language_options_text(self) -> str:
        languages = self.settings.supported_languages_list or [DEFAULT_LANGUAGE]
        if len(languages) == 1:
            return languages[0]
        return ", ".join(languages)

    def _main_menu_prompt(self, prefix: str, language: str) -> str:
        prompt = self._text(language, "tap_option")
        clean_prefix = (prefix or "").strip()
        if not clean_prefix:
            return prompt
        return f"{clean_prefix}\n\n{prompt}"

    def _format_numbered_titles(self, titles: list[str]) -> str:
        return "\n".join(f"{index}. {title}" for index, title in enumerate(titles, start=1))

    def _localize_lesson_summaries(
        self,
        lesson_summaries: list[AccessibleLessonSummary],
        language: str,
    ) -> list[AccessibleLessonSummary]:
        localized: list[AccessibleLessonSummary] = []
        for item in lesson_summaries:
            display_title = localize_lesson_display_title(
                lesson_name=item.lesson_name,
                topic=item.topic,
                target_language=language,
            )
            if item.is_shared and not display_title.startswith("*"):
                display_title = f"* {display_title}"
            localized.append(replace(item, display_title=display_title))
        return localized

    def _is_greeting(self, choice: str) -> bool:
        return choice in {
            "hi",
            "hello",
            "hey",
            "hii",
            "hiii",
            "helo",
            "hola",
            "good morning",
            "good afternoon",
            "good evening",
            "start",
            "नमस्ते",
            "नमस्कार",
            "शुरू",
        }

    def _is_keep_value(self, text: str) -> bool:
        return normalize_choice(text) in {"same", "skip", "keep", "current", "सेम", "समान"}

    def _is_main_menu_choice(self, choice: str) -> bool:
        return choice in {
            "menu_main_menu",
            "main menu",
            "back to main menu",
            "menu",
            "home",
            "मुख्य मेनू",
            "मेनू",
            "होम",
        }

    def _main_menu_button(self, language: str) -> dict[str, str]:
        return {"id": "menu_main_menu", "title": self._text(language, "btn_main_menu")}

    def _main_menu_row(self, language: str) -> dict[str, str]:
        return {"id": "menu_main_menu", "title": self._text(language, "btn_main_menu")}

    def _lesson_page_row(self, page: int, title: str) -> dict[str, str]:
        return {"id": f"lesson_page:{page}", "title": title[:24]}

    def _new_lesson_grade_prompt(self, language: str) -> str:
        return self._text(language, "new_lesson_grade_prompt")

    def _new_lesson_subject_prompt(self, language: str) -> str:
        return self._text(language, "new_lesson_subject_prompt")

    def _profile_language_prompt(self, language: str) -> str:
        return self._text(language, "profile_language_prompt", options=self._language_options_text())

    def _profile_update_summary(self, teacher, language: str) -> str:
        return self._text(
            language,
            "current_profile",
            name=teacher.teacher_name,
            school=getattr(teacher, "school_name", None) or "Not selected",
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            language=teacher.preferred_language,
        )

    def _profile_name_edit_prompt(self, teacher, language: str) -> str:
        return (
            f"{self._text(language, 'profile_updated')}\n\n"
            f"{self._profile_update_summary(teacher, language)}\n\n"
            f"{self._text(language, 'profile_name_edit')}"
        )

    def _profile_school_prompt(self, language: str, *, teacher=None) -> ConversationReply:
        schools = self.embedding_content_repo.list_schools()
        if not schools:
            return self._reply(self._text(language, "profile_school_empty"), ConversationState.PROFILE_SCHOOL)

        rows = [
            {"id": f"school:{index}", "title": school[:24], "description": school[:72] if len(school) > 24 else ""}
            for index, school in enumerate(schools[:9], start=1)
        ]
        rows.append(self._main_menu_row(language))
        current = getattr(teacher, "school_name", None) or "Not selected"
        body = (
            self._text(language, "profile_school_edit", school=current)
            if teacher
            else self._text(language, "school_list_body")
        )
        return self._reply(
            self._text(language, "profile_school_prompt"),
            ConversationState.PROFILE_SCHOOL,
            outbound={
                "type": "list",
                "header": self._text(language, "school_list_header"),
                "body": body,
                "button_text": self._text(language, "school_list_button"),
                "section_title": self._text(language, "school_list_section"),
                "footer": self._text(language, "school_list_footer"),
                "rows": rows,
            },
        )

    def _profile_school_edit_prompt(self, teacher, language: str) -> ConversationReply:
        return self._profile_school_prompt(language, teacher=teacher)

    def _profile_grade_edit_prompt(self, teacher, language: str) -> str:
        return self._text(language, "profile_grade_edit", grade=teacher.default_grade)

    def _profile_subject_edit_prompt(self, teacher, language: str) -> str:
        return self._text(language, "profile_subject_edit", subject=teacher.default_subject)

    def _profile_language_edit_prompt(self, teacher, language: str) -> str:
        return self._text(
            language,
            "profile_language_edit",
            language=teacher.preferred_language,
            options=self._language_options_text(),
        )

    def _main_menu_outbound(self, language: str) -> dict:
        return {
            "type": "buttons",
            "header": self._text(language, "main_header"),
            "body": self._text(language, "main_body"),
            "footer": self._text(language, "main_footer"),
            "buttons": [
                {"id": "menu_new_lesson", "title": self._text(language, "btn_new_lesson")},
                {"id": "menu_all_lessons", "title": self._text(language, "btn_all_lessons")},
                {"id": "menu_my_profile", "title": self._text(language, "btn_profile")},
            ],
        }

    def _main_menu_reply(self, prefix: str, language: str) -> ConversationReply:
        return self._reply(
            self._main_menu_prompt(prefix, language),
            ConversationState.MAIN_MENU,
            outbound=self._main_menu_outbound(language),
        )

    def _save_menu_reply(self, lesson_text: str, language: str) -> ConversationReply:
        return self._reply(
            f"{self._text(language, 'generated_lesson_prefix')}\n\n{lesson_text}",
            ConversationState.NEW_LESSON_CONFIRM_SAVE,
            outbound={
                "type": "buttons",
                "header": self._text(language, "main_header"),
                "body": self._text(language, "save_body"),
                "footer": self._text(language, "save_footer"),
                "buttons": [
                    {"id": "save_lesson", "title": self._text(language, "btn_save")},
                    {"id": "cancel_lesson", "title": self._text(language, "btn_cancel")},
                    self._main_menu_button(language),
                ],
            },
        )

    def _lesson_day_reply(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        subsections: list[EmbeddingSubsection],
        summary: str,
        language: str,
    ) -> ConversationReply:
        rows: list[dict[str, str]] = []
        for index, subsection in enumerate(subsections[:9], start=1):
            day_label = f"Day {index}"
            description_parts = [subsection.title]
            if subsection.display_pages != "Not available":
                description_parts.append(f"Pages {subsection.display_pages}")
            rows.append(
                {
                    "id": f"lesson_day:{subsection.id}",
                    "title": day_label[:24],
                    "description": " | ".join(part for part in description_parts if part)[:72],
                }
            )
        rows.append(self._main_menu_row(language))

        reply_text = self._text(
            language,
            "lesson_summary_intro",
            title=lesson.title,
            pages=lesson.display_pages,
            summary=summary,
        )
        return self._reply(
            reply_text,
            ConversationState.NEW_LESSON_DAY,
            outbound={
                "type": "list",
                "header": self._text(language, "lesson_day_header"),
                "body": self._text(language, "lesson_day_body"),
                "button_text": self._text(language, "lesson_day_button"),
                "section_title": self._text(language, "lesson_day_section"),
                "footer": self._text(language, "lesson_day_footer"),
                "rows": rows,
            },
        )

    def _resolve_subsection_choice(
        self,
        *,
        choice: str,
        text: str,
        subsections: list[EmbeddingSubsection],
    ) -> tuple[int, EmbeddingSubsection] | None:
        selected_id = ""
        if choice.startswith("lesson_day:"):
            selected_id = choice.split(":", 1)[1].strip()
        if selected_id:
            for index, subsection in enumerate(subsections, start=1):
                if subsection.id == selected_id:
                    return index, subsection
            subsection = self.embedding_content_repo.get_subsection_by_id(selected_id)
            if subsection:
                return 1, subsection

        raw = (text or choice or "").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(subsections):
                return index, subsections[index - 1]

        normalized = normalize_choice(raw)
        day_match = re.fullmatch(r"day\s*(\d+)", normalized)
        if day_match:
            index = int(day_match.group(1))
            if 1 <= index <= len(subsections):
                return index, subsections[index - 1]

        return None

    def _suggest_lesson_name(self, topic: str | None, language: str | None = None) -> str:
        base = self._lesson_name_base_for_language(topic, language)
        date_suffix = datetime.now().strftime("%d_%b_%Y")
        return f"{base}_{date_suffix}"

    def _lesson_name_base_for_language(self, topic: str | None, language: str | None = None) -> str:
        base = re.sub(r"\s+", " ", (topic or "").strip())
        is_hindi = (language or "").strip().casefold() == "hindi"

        if is_hindi:
            base = self._topic_to_devanagari_lesson_name_base(base)
            base = re.sub(r"[^0-9\u0900-\u097F]+", "", base)
            base = base[:48].strip()
            return base or "पाठ"

        # English/Hinglish saved lesson names use PascalCase/CamelCase style:
        # "Jhansi Ki Rani" -> "JhansiKiRani". Only the date keeps underscores.
        base = re.sub(r"[^0-9A-Za-z\u0900-\u097F ]+", " ", base)
        base = re.sub(r"\s+", " ", base).strip() or "Lesson"
        base = self._shorten_lesson_name_base(base, max_chars=48)
        base = self._to_compact_pascal_case(base)
        return base or "Lesson"

    def _topic_to_devanagari_lesson_name_base(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", (value or "").strip())
        if not cleaned:
            return "पाठ"

        # If the teacher already entered the topic in Devanagari, preserve it
        # and only remove spaces/punctuation for the suggested saved name.
        if re.search(r"[\u0900-\u097F]", cleaned):
            return cleaned

        normalized = self._normalize_roman_topic_key(cleaned)
        phrase_aliases = {
            "jhansi ki rani": "झाँसी की रानी",
            "jhansi rani": "झाँसी की रानी",
            "rani of jhansi": "झाँसी की रानी",
            "ganit": "गणित",
            "math": "गणित",
            "maths": "गणित",
            "mathematics": "गणित",
            "vigyan": "विज्ञान",
            "science": "विज्ञान",
            "angrezi": "अंग्रेज़ी",
            "english": "अंग्रेज़ी",
            "hindi": "हिंदी",
            "samajik vigyan": "सामाजिक विज्ञान",
            "social science": "सामाजिक विज्ञान",
            "social studies": "सामाजिक विज्ञान",
        }
        if normalized in phrase_aliases:
            return phrase_aliases[normalized]

        # A small word-level fallback covers common Hindi classroom words.
        # Unknown Roman words are kept as-is instead of guessing incorrectly.
        word_aliases = {
            "jhansi": "झाँसी",
            "ki": "की",
            "rani": "रानी",
            "ganit": "गणित",
            "math": "गणित",
            "maths": "गणित",
            "mathematics": "गणित",
            "vigyan": "विज्ञान",
            "science": "विज्ञान",
            "samajik": "सामाजिक",
            "social": "सामाजिक",
            "studies": "विज्ञान",
            "angrezi": "अंग्रेज़ी",
            "english": "अंग्रेज़ी",
            "hindi": "हिंदी",
        }
        words = normalized.split()
        converted = [word_aliases.get(word, word) for word in words]
        return " ".join(converted).strip() or cleaned

    def _normalize_roman_topic_key(self, value: str) -> str:
        value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
        value = re.sub(r"[^0-9A-Za-z]+", " ", value)
        return re.sub(r"\s+", " ", value).strip().casefold()

    def _to_compact_pascal_case(self, value: str) -> str:
        words = re.findall(r"[0-9A-Za-z\u0900-\u097F]+", value or "")
        pieces: list[str] = []
        for word in words:
            if re.search(r"[\u0900-\u097F]", word):
                pieces.append(word)
            elif word.isupper() and len(word) > 1:
                pieces.append(word)
            else:
                pieces.append(word[:1].upper() + word[1:].lower())
        return "".join(pieces)

    def _shorten_lesson_name_base(self, value: str, *, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value

        words = value.split()
        shortened = ""
        for word in words:
            candidate = f"{shortened} {word}".strip()
            if len(candidate) > max_chars:
                break
            shortened = candidate

        if shortened:
            return shortened.rstrip("_")
        return value[:max_chars].rstrip()

    def _confirm_lesson_name_reply(self, lesson_name: str, language: str) -> ConversationReply:
        return self._reply(
            self._text(language, "lesson_name_suggestion_body", lesson_name=lesson_name),
            ConversationState.NEW_LESSON_CONFIRM_NAME,
            outbound={
                "type": "buttons",
                "header": self._text(language, "main_header"),
                "body": self._text(language, "lesson_name_suggestion_body", lesson_name=lesson_name),
                "footer": self._text(language, "lesson_name_suggestion_footer"),
                "buttons": [
                    {"id": "confirm_suggested_lesson_name", "title": self._text(language, "btn_yes")},
                    {"id": "enter_custom_lesson_name", "title": self._text(language, "btn_no")},
                    self._main_menu_button(language),
                ],
            },
        )

    def _lesson_day_label_for_summary(self, item: AccessibleLessonSummary) -> str | None:
        if item.day_title:
            return item.day_title.strip()
        if item.day_number:
            return f"Day {item.day_number}"
        return None

    def _lesson_option_title(self, item: AccessibleLessonSummary) -> str:
        day_label = self._lesson_day_label_for_summary(item)
        title = item.display_title or item.lesson_name
        if not day_label:
            return title
        # Keep the selected day visible in the WhatsApp option title whenever possible.
        short_day = day_label.replace("Day ", "D") if day_label.startswith("Day ") else day_label
        max_title_len = max(8, 23 - len(short_day))
        base = title[:max_title_len].rstrip()
        return f"{base} {short_day}".strip()

    def _lesson_option_description(self, item: AccessibleLessonSummary) -> str:
        parts: list[str] = []
        day_label = self._lesson_day_label_for_summary(item)
        if day_label:
            parts.append(day_label)
        if item.subsection_title and item.subsection_title != day_label:
            parts.append(item.subsection_title)
        if item.book_title:
            parts.append(item.book_title)
        if item.book_pages:
            parts.append(f"Pages {item.book_pages}")
        return " | ".join(part for part in parts if part)

    def _all_lessons_interactive_reply(
        self,
        lesson_summaries: list[AccessibleLessonSummary],
        language: str,
        page: int = 0,
    ) -> ConversationReply:
        # WhatsApp list messages support up to 10 rows. Keep the same WhatsApp
        # list-style menu for larger lesson libraries by paginating the list and
        # reserving rows for navigation plus Back to Main Menu.
        page_size = 7
        total_lessons = len(lesson_summaries)
        total_pages = max(1, (total_lessons + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        start_index = page * page_size
        page_lessons = lesson_summaries[start_index : start_index + page_size]

        rows = []
        for item_summary in page_lessons:
            row_title = self._lesson_option_title(item_summary)
            row_description = self._lesson_option_description(item_summary)
            item = {
                "id": f"lesson_id:{item_summary.lesson_id}",
                "title": row_title[:24],
            }
            if row_description:
                item["description"] = row_description[:72]
            elif len(row_title) > 24:
                item["description"] = row_title[:72]
            rows.append(item)

        if page > 0:
            rows.append(self._lesson_page_row(page - 1, self._text(language, "all_lessons_previous")))
        if page < total_pages - 1:
            rows.append(self._lesson_page_row(page + 1, self._text(language, "all_lessons_next")))
        rows.append(self._main_menu_row(language))

        return self._reply(
            self._text(language, "all_lessons_reply"),
            ConversationState.RETRIEVE_LESSON_NAME,
            outbound={
                "type": "list",
                "header": self._text(language, "all_lessons_header"),
                "body": self._text(
                    language,
                    "all_lessons_body_page",
                    page=page + 1,
                    total_pages=total_pages,
                ),
                "button_text": self._text(language, "all_lessons_button"),
                "section_title": self._text(language, "all_lessons_section"),
                "footer": self._text(language, "all_lessons_footer"),
                "rows": rows,
            },
        )

    def _all_lessons_fallback_reply(self, titles: list[str], language: str) -> ConversationReply:
        # Kept only for backward compatibility; All Lessons now uses WhatsApp
        # list-style outbound options even when there are more than 10 lessons.
        reply_text = self._text(
            language,
            "all_lessons_fallback",
            titles=self._format_numbered_titles(titles),
        )
        return self._reply(reply_text, ConversationState.RETRIEVE_LESSON_NAME)

    def _show_accessible_lessons(self, session, teacher_id: int, language: str, page: int = 0) -> ConversationReply:
        lesson_summaries = self._localize_lesson_summaries(
            self.lesson_repo.list_accessible_summaries_for_teacher(teacher_id),
            language,
        )
        if not lesson_summaries:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "all_lessons_empty"), language)

        session.current_state = ConversationState.RETRIEVE_LESSON_NAME.value
        session.temp_selected_lesson_id = None
        self.session_repo.save(session)

        return self._all_lessons_interactive_reply(
            lesson_summaries,
            language,
            page=page,
        )

    def _lesson_action_reply(
        self,
        lesson_text: str,
        *,
        is_shared: bool,
        language: str,
        shared_by_teacher_name: str | None = None,
        prefix: str | None = None,
    ) -> ConversationReply:
        shared_note = ""
        if is_shared:
            teacher_name = (shared_by_teacher_name or "another teacher").strip()
            shared_note = f"\n\n{self._text(language, 'shared_lesson_from', teacher_name=teacher_name)}"

        message_parts = []
        if prefix:
            message_parts.append(prefix.strip())
        message_parts.append(f"{lesson_text}{shared_note}\n\n{self._text(language, 'lesson_action_prompt')}")

        if is_shared:
            outbound = {
                "type": "buttons",
                "header": self._text(language, "lesson_actions_header"),
                "body": self._text(language, "shared_lesson_body"),
                "footer": self._text(language, "main_footer"),
                "buttons": [
                    self._main_menu_button(language),
                ],
            }
        else:
            outbound = {
                "type": "buttons",
                "header": self._text(language, "lesson_actions_header"),
                "body": self._text(language, "lesson_actions_body"),
                "footer": self._text(language, "main_footer"),
                "buttons": [
                    {"id": "lesson_action_share", "title": self._text(language, "btn_share")},
                    {"id": "lesson_action_delete", "title": self._text(language, "btn_delete")},
                    self._main_menu_button(language),
                ],
            }

        return self._reply(
            "\n\n".join(part for part in message_parts if part),
            ConversationState.LESSON_ACTION_MENU,
            outbound=outbound,
        )

    def _share_lesson_phone_prompt(self, lesson_name: str, language: str) -> ConversationReply:
        return self._reply(
            self._text(language, "share_prompt", lesson_name=lesson_name),
            ConversationState.SHARE_LESSON_PHONE,
        )

    def _delete_lesson_confirm_reply(self, lesson_name: str, language: str) -> ConversationReply:
        return self._reply(
            self._text(language, "delete_confirm", lesson_name=lesson_name),
            ConversationState.DELETE_LESSON_CONFIRM,
            outbound={
                "type": "buttons",
                "header": self._text(language, "delete_header"),
                "body": self._text(language, "delete_confirm", lesson_name=lesson_name),
                "footer": self._text(language, "save_footer"),
                "buttons": [
                    {"id": "confirm_delete_lesson", "title": self._text(language, "btn_confirm_delete")},
                    {"id": "cancel_delete_lesson", "title": self._text(language, "btn_cancel")},
                    self._main_menu_button(language),
                ],
            },
        )

    def _handle_main_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if not choice or self._is_greeting(choice):
            return self._main_menu_reply(self._text(language, "welcome"), language)

        if choice in {"1", "new lesson", "menu_new_lesson", "naya lesson", "नया पाठ"}:
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

            if not (getattr(teacher, "school_name", None) or "").strip():
                self.session_repo.clear_temp_profile(session)
                session.temp_profile_name = teacher.teacher_name
                session.temp_profile_grade = teacher.default_grade
                session.temp_profile_subject = teacher.default_subject
                session.current_state = ConversationState.PROFILE_SCHOOL.value
                self.session_repo.save(session)
                school_reply = self._profile_school_edit_prompt(teacher, language)
                return self._reply(
                    f"{self._text(language, 'new_lesson_no_school')}\n\n{school_reply.reply}",
                    ConversationState.PROFILE_SCHOOL,
                    outbound=school_reply.outbound,
                )

            self.session_repo.clear_temp_lesson(session)
            session.current_state = ConversationState.NEW_LESSON_TOPIC.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_topic_prompt"), ConversationState.NEW_LESSON_TOPIC)

        if choice in {"2", "all lessons", "menu_all_lessons", "sab lessons", "सभी पाठ"}:
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

            return self._show_accessible_lessons(session, teacher.id, language)

        if choice in {"3", "my profile", "menu_my_profile", "profile", "प्रोफ़ाइल", "प्रोफाइल"}:
            self.session_repo.clear_temp_profile(session)
            session.current_state = ConversationState.PROFILE_NAME.value

            if teacher:
                session.temp_profile_name = teacher.teacher_name
                session.temp_profile_grade = teacher.default_grade
                session.temp_profile_subject = teacher.default_subject
                session.temp_profile_school = getattr(teacher, "school_name", None)
                self.session_repo.save(session)
                return self._reply(self._profile_name_edit_prompt(teacher, language), ConversationState.PROFILE_NAME)

            self.session_repo.save(session)
            return self._reply(self._text(language, "profile_start"), ConversationState.PROFILE_NAME)

        return self._main_menu_reply(self._text(language, "main_menu_unknown"), language)

    def _handle_profile_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_name_edit_prompt(teacher, language), ConversationState.PROFILE_NAME)
            return self._reply(self._text(language, "profile_name_prompt"), ConversationState.PROFILE_NAME)

        if teacher and self._is_keep_value(text):
            session.temp_profile_name = teacher.teacher_name
        else:
            session.temp_profile_name = text

        session.current_state = ConversationState.PROFILE_SCHOOL.value
        self.session_repo.save(session)

        if teacher:
            return self._profile_school_edit_prompt(teacher, language)
        return self._profile_school_prompt(language)

    def _handle_profile_school(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        schools = self.embedding_content_repo.list_schools()

        if not text:
            if teacher:
                return self._profile_school_edit_prompt(teacher, language)
            return self._profile_school_prompt(language)

        if teacher and self._is_keep_value(text):
            school_value = getattr(teacher, "school_name", None) or ""
        elif schools:
            school_value = self.embedding_content_repo.resolve_school_choice(text) or ""
            if not school_value:
                prompt = self._profile_school_edit_prompt(teacher, language) if teacher else self._profile_school_prompt(language)
                return self._reply(
                    f"{self._text(language, 'profile_school_invalid')}\n{prompt.reply}",
                    ConversationState.PROFILE_SCHOOL,
                    outbound=prompt.outbound,
                )
        else:
            school_value = text.strip()

        session.temp_profile_school = school_value
        session.current_state = ConversationState.PROFILE_GRADE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_grade_edit_prompt(teacher, language), ConversationState.PROFILE_GRADE)
        return self._reply(self._text(language, "profile_grade_prompt"), ConversationState.PROFILE_GRADE)

    def _handle_profile_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_grade_edit_prompt(teacher, language), ConversationState.PROFILE_GRADE)
            return self._reply(self._text(language, "profile_grade_prompt"), ConversationState.PROFILE_GRADE)

        if teacher and self._is_keep_value(text):
            grade_value = teacher.default_grade
        else:
            grade_value = normalize_grade(text)
            grade_error = self._localize_validation_error(validate_profile_grade(grade_value, self.settings), language)
            if grade_error:
                log_event(logger, "validation_failure", field="default_grade", value=text)
                prompt = self._profile_grade_edit_prompt(teacher, language) if teacher else self._text(language, "profile_grade_prompt")
                return self._reply(
                    f"{grade_error}\n{prompt}",
                    ConversationState.PROFILE_GRADE,
                )

        session.temp_profile_grade = grade_value
        session.current_state = ConversationState.PROFILE_SUBJECT.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_subject_edit_prompt(teacher, language), ConversationState.PROFILE_SUBJECT)
        return self._reply(self._text(language, "profile_subject_prompt"), ConversationState.PROFILE_SUBJECT)

    def _handle_profile_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_subject_edit_prompt(teacher, language), ConversationState.PROFILE_SUBJECT)
            return self._reply(self._text(language, "profile_subject_prompt"), ConversationState.PROFILE_SUBJECT)

        if teacher and self._is_keep_value(text):
            subject_value = teacher.default_subject
        else:
            subject_value = self.subject_resolver.resolve(text, language=language)
            subject_error = self._localize_validation_error(
                validate_profile_subject(
                    subject_value,
                    session.temp_profile_grade or "",
                    self.settings,
                ),
                language,
            )
            if subject_error:
                log_event(logger, "validation_failure", field="default_subject", value=text)
                prompt = self._profile_subject_edit_prompt(teacher, language) if teacher else self._text(language, "profile_subject_prompt")
                return self._reply(
                    f"{subject_error}\n{prompt}",
                    ConversationState.PROFILE_SUBJECT,
                )

        session.temp_profile_subject = subject_value

        # Always ask for the preferred language while creating/updating a profile.
        # After the teacher answers, _handle_profile_language saves it locally and
        # syncs the same value back to Jalta Sitara Hotline when needed.
        session.current_state = ConversationState.PROFILE_LANGUAGE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_language_edit_prompt(teacher, language), ConversationState.PROFILE_LANGUAGE)
        return self._reply(self._profile_language_prompt(language), ConversationState.PROFILE_LANGUAGE)

    def _handle_profile_language(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_language_edit_prompt(teacher, language), ConversationState.PROFILE_LANGUAGE)
            return self._reply(self._profile_language_prompt(language), ConversationState.PROFILE_LANGUAGE)

        if teacher and self._is_keep_value(text):
            language_value = teacher.preferred_language
        else:
            normalized_language = normalize_language(text.strip(), default=None)
            if not normalized_language or normalized_language.casefold() not in self.settings.supported_languages_casefold:
                log_event(logger, "validation_failure", field="preferred_language", value=text)
                prompt = self._profile_language_edit_prompt(teacher, language) if teacher else self._profile_language_prompt(language)
                return self._reply(
                    f"{self._text(language, 'profile_language_invalid')}\n{prompt}",
                    ConversationState.PROFILE_LANGUAGE,
                )
            language_value = normalized_language

        # Teacher Helper is the source of truth for a profile edit/create action.
        # Save locally first. Hotline sync is best-effort and must never block the profile flow.
        self.teacher_repo.upsert(
            whatsapp_number=whatsapp_number,
            teacher_name=session.temp_profile_name or "",
            default_grade=session.temp_profile_grade or "",
            default_subject=session.temp_profile_subject or "",
            school_name=session.temp_profile_school or None,
            preferred_language=language_value,
        )
        try:
            self.preferred_language_api.sync_preferred_language_if_needed(
                phone_number=whatsapp_number,
                selected_language=language_value,
            )
        except Exception as exc:  # pragma: no cover - defensive; profile save already succeeded.
            log_event(
                logger,
                "preferred_language_sync_ignored",
                whatsapp_number=whatsapp_number,
                preferred_language=language_value,
                error=str(exc),
            )
        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(self._text(language_value, "profile_saved"), language_value)

    def _handle_new_lesson_topic(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            log_event(logger, "validation_failure", field="topic", value=text)
            return self._reply(self._text(language, "new_lesson_topic_invalid"), ConversationState.NEW_LESSON_TOPIC)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        school_name = (getattr(teacher, "school_name", None) or "").strip()
        if not school_name:
            session.current_state = ConversationState.PROFILE_SCHOOL.value
            self.session_repo.save(session)
            school_reply = self._profile_school_edit_prompt(teacher, language)
            return self._reply(
                f"{self._text(language, 'new_lesson_no_school')}\n\n{school_reply.reply}",
                ConversationState.PROFILE_SCHOOL,
                outbound=school_reply.outbound,
            )

        # Keep the exact teacher-entered topic. The older flow asked grade, subject,
        # and class duration before generation; these values now drive DB matching,
        # prompt metadata, the visible lesson header, and saved lesson_plan fields.
        session.temp_topic = text.strip()
        session.temp_profile_grade = None
        session.temp_profile_subject = None
        session.temp_duration_minutes = None
        session.current_state = ConversationState.NEW_LESSON_GRADE.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_grade_prompt(language), ConversationState.NEW_LESSON_GRADE)

    def _handle_new_lesson_day(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        lesson = self.embedding_content_repo.get_lesson_by_chapter_id(session.temp_content_chapter_id or "")
        if not lesson:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=session.temp_topic or ""), language)

        subsections = self.embedding_content_repo.list_subsections_for_lesson(lesson)
        selected = self._resolve_subsection_choice(choice=choice, text=text, subsections=subsections)
        if not selected:
            summary = session.temp_lesson_summary or ""
            day_reply = self._lesson_day_reply(
                lesson=lesson,
                subsections=subsections,
                summary=summary,
                language=language,
            )
            return self._reply(
                f"{self._text(language, 'lesson_day_invalid')}\n\n{day_reply.reply}",
                ConversationState.NEW_LESSON_DAY,
                outbound=day_reply.outbound,
            )

        day_number, subsection = selected
        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject
        requested_duration = session.temp_duration_minutes or 0
        result = self.pdf_content_lesson_service.generate_day_lesson_plan(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=requested_duration,
        )
        session.temp_content_subsection_id = subsection.id
        session.temp_lesson_day_number = day_number
        session.temp_lesson_day_title = f"Day {day_number}"
        session.temp_lesson_book_title = lesson.book_title
        session.temp_lesson_document_key = lesson.document_key
        session.temp_lesson_school_name = lesson.school_name
        session.temp_lesson_chapter_title = lesson.chapter_title
        session.temp_lesson_section_title = lesson.section_title
        session.temp_lesson_subsection_number = subsection.subsection_number
        session.temp_lesson_subsection_title = subsection.title
        session.temp_lesson_book_pages = subsection.display_pages
        session.temp_lesson_pdf_start_page = subsection.pdf_start_page
        session.temp_lesson_pdf_end_page = subsection.pdf_end_page
        session.temp_lesson_printed_start_page = subsection.printed_start_page
        session.temp_lesson_printed_end_page = subsection.printed_end_page
        session.temp_topic = lesson.title
        session.temp_duration_minutes = requested_duration or result.duration_minutes
        session.temp_generated_lesson = result.lesson_text
        session.current_state = ConversationState.NEW_LESSON_CONFIRM_SAVE.value
        self.session_repo.save(session)

        log_event(
            logger,
            "lesson_day_generated_from_embedding_subsection",
            teacher_id=teacher.id,
            chapter_id=lesson.chapter_id,
            subsection_id=subsection.id,
            day_number=day_number,
            teacher_input_grade=lesson_grade,
            teacher_input_subject=lesson_subject,
            teacher_input_duration_minutes=requested_duration,
            provider_used=result.provider_used,
        )
        return self._save_menu_reply(result.lesson_text, language)

    def _handle_new_lesson_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            return self._reply(self._new_lesson_grade_prompt(language), ConversationState.NEW_LESSON_GRADE)

        grade_value = normalize_grade(text)
        grade_error = self._localize_validation_error(validate_profile_grade(grade_value, self.settings), language)
        if grade_error:
            log_event(logger, "validation_failure", field="lesson_grade", value=text)
            return self._reply(
                f"{grade_error}\n{self._new_lesson_grade_prompt(language)}",
                ConversationState.NEW_LESSON_GRADE,
            )

        session.temp_profile_grade = grade_value
        session.current_state = ConversationState.NEW_LESSON_SUBJECT.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_subject_prompt(language), ConversationState.NEW_LESSON_SUBJECT)

    def _handle_new_lesson_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            return self._reply(self._new_lesson_subject_prompt(language), ConversationState.NEW_LESSON_SUBJECT)

        lesson_grade = session.temp_profile_grade or ""
        normalized_subject = self.subject_resolver.resolve(text, language=language)
        subject_error = self._localize_validation_error(validate_profile_subject(normalized_subject, lesson_grade, self.settings), language)
        if subject_error:
            log_event(logger, "validation_failure", field="lesson_subject", value=text)
            return self._reply(
                f"{subject_error}\n{self._new_lesson_subject_prompt(language)}",
                ConversationState.NEW_LESSON_SUBJECT,
            )

        session.temp_profile_subject = normalized_subject
        session.current_state = ConversationState.NEW_LESSON_DURATION.value
        self.session_repo.save(session)
        return self._reply(self._text(language, "duration_prompt"), ConversationState.NEW_LESSON_DURATION)

    def _handle_new_lesson_duration(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        duration = parse_duration_minutes(text)
        if duration is None:
            log_event(logger, "validation_failure", field="duration_minutes", value=text)
            return self._reply(self._text(language, "invalid_duration"), ConversationState.NEW_LESSON_DURATION)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        school_name = (getattr(teacher, "school_name", None) or "").strip()
        if not school_name:
            session.current_state = ConversationState.PROFILE_SCHOOL.value
            self.session_repo.save(session)
            school_reply = self._profile_school_edit_prompt(teacher, language)
            return self._reply(
                f"{self._text(language, 'new_lesson_no_school')}\n\n{school_reply.reply}",
                ConversationState.PROFILE_SCHOOL,
                outbound=school_reply.outbound,
            )

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject
        topic = (session.temp_topic or "").strip()
        session.temp_duration_minutes = duration

        lesson_match = self.embedding_content_repo.find_lesson_match(
            school_name=school_name,
            grade=lesson_grade,
            subject=lesson_subject,
            topic=topic,
        )
        if not lesson_match:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=topic), language)

        subsections = self.embedding_content_repo.list_subsections_for_lesson(lesson_match)
        if not subsections:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=topic), language)

        summary, provider_used = self.pdf_content_lesson_service.generate_section_summary(
            lesson=lesson_match,
            teacher=teacher,
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=duration,
        )
        session.temp_topic = lesson_match.title
        session.temp_content_document_id = lesson_match.document_id
        session.temp_content_chapter_id = lesson_match.chapter_id
        session.temp_lesson_document_key = lesson_match.document_key
        session.temp_lesson_book_title = lesson_match.book_title
        session.temp_lesson_school_name = lesson_match.school_name
        session.temp_lesson_chapter_title = lesson_match.chapter_title
        session.temp_lesson_section_title = lesson_match.section_title
        session.temp_lesson_summary = summary
        session.current_state = ConversationState.NEW_LESSON_DAY.value
        self.session_repo.save(session)

        log_event(
            logger,
            "lesson_topic_matched_to_embedding_section",
            teacher_id=teacher.id,
            topic=topic,
            match_title=lesson_match.title,
            chapter_id=lesson_match.chapter_id,
            subsection_count=len(subsections),
            teacher_input_grade=lesson_grade,
            teacher_input_subject=lesson_subject,
            teacher_input_duration_minutes=duration,
            summary_provider=provider_used,
        )
        return self._lesson_day_reply(
            lesson=lesson_match,
            subsections=subsections,
            summary=summary,
            language=language,
        )

    def _handle_new_lesson_confirm_save(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if choice in {"1", "yes", "save lesson", "save_lesson", "पाठ सेव करें"}:
            suggested_name = self._suggest_lesson_name(session.temp_topic, language)
            session.temp_lesson_name = suggested_name
            session.current_state = ConversationState.NEW_LESSON_CONFIRM_NAME.value
            self.session_repo.save(session)
            return self._confirm_lesson_name_reply(suggested_name, language)

        if choice in {"2", "no", "cancel", "cancel_lesson", "रद्द करें", "radd"}:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_cancelled"), language)

        return self._reply(
            self._text(language, "save_invalid"),
            ConversationState.NEW_LESSON_CONFIRM_SAVE,
            outbound={
                "type": "buttons",
                "header": self._text(language, "main_header"),
                "body": self._text(language, "save_body"),
                "footer": self._text(language, "save_footer"),
                "buttons": [
                    {"id": "save_lesson", "title": self._text(language, "btn_save")},
                    {"id": "cancel_lesson", "title": self._text(language, "btn_cancel")},
                    self._main_menu_button(language),
                ],
            },
        )

    def _handle_new_lesson_confirm_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        suggested_name = (session.temp_lesson_name or self._suggest_lesson_name(session.temp_topic, language)).strip()
        session.temp_lesson_name = suggested_name

        if choice in {"1", "yes", "confirm_suggested_lesson_name", "हाँ", "हां"}:
            return self._save_generated_lesson_with_name(session, teacher, suggested_name, language)

        if choice in {"2", "no", "enter_custom_lesson_name", "नहीं", "नही"}:
            session.current_state = ConversationState.NEW_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "lesson_name_prompt"), ConversationState.NEW_LESSON_NAME)

        # Backward-compatible browser/local testing support: if someone types a
        # custom lesson name instead of tapping Yes/No, use that custom name.
        if text and choice not in {""}:
            return self._save_generated_lesson_with_name(session, teacher, text.strip(), language)

        return self._reply(
            self._text(language, "lesson_name_suggestion_invalid"),
            ConversationState.NEW_LESSON_CONFIRM_NAME,
            outbound=self._confirm_lesson_name_reply(suggested_name, language).outbound,
        )

    def _save_generated_lesson_with_name(self, session, teacher, lesson_name: str, language: str) -> ConversationReply:
        lesson_name = (lesson_name or "").strip()
        if not lesson_name:
            log_event(logger, "validation_failure", field="lesson_name", value=lesson_name)
            return self._reply(self._text(language, "lesson_name_invalid"), ConversationState.NEW_LESSON_NAME)

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject

        lesson_payload = self.lesson_payload_builder.build(
            teacher_id=teacher.id,
            lesson_name=lesson_name,
            grade=lesson_grade,
            subject=lesson_subject,
            topic=session.temp_topic or "",
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
        )
        source_reference = {}
        if session.temp_content_subsection_id:
            source_reference = {
                **(lesson_payload.get("source_reference") or {}),
                "source_type": "pdf_to_embeddings_subsection",
                "document_id": session.temp_content_document_id,
                "document_key": session.temp_lesson_document_key,
                "book_title": session.temp_lesson_book_title,
                "school_name": session.temp_lesson_school_name,
                "chapter_id": session.temp_content_chapter_id,
                "subsection_id": session.temp_content_subsection_id,
                "chapter_title": session.temp_lesson_chapter_title,
                "section_title": session.temp_lesson_section_title,
                "subsection_number": session.temp_lesson_subsection_number,
                "subsection_title": session.temp_lesson_subsection_title,
                "day_number": session.temp_lesson_day_number,
                "day_title": session.temp_lesson_day_title,
                "book_pages": session.temp_lesson_book_pages,
                "pdf_start_page": session.temp_lesson_pdf_start_page,
                "pdf_end_page": session.temp_lesson_pdf_end_page,
                "printed_start_page": session.temp_lesson_printed_start_page,
                "printed_end_page": session.temp_lesson_printed_end_page,
                "resource_profile": "Resource-Limited",
                "format_profile": "Detailed",
                "topic_name": session.temp_topic or "",
            }
            lesson_payload["source_type"] = "pdf_to_embeddings_subsection"
            lesson_payload["source_reference"] = source_reference

        lesson = self.lesson_repo.create_or_update_by_policy(
            teacher_id=teacher.id,
            lesson_name=lesson_name,
            topic=session.temp_topic or "",
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
            lesson_payload=lesson_payload,
            document_id=session.temp_content_document_id,
            document_key=session.temp_lesson_document_key,
            book_title=session.temp_lesson_book_title,
            school_name=session.temp_lesson_school_name,
            chapter_id=session.temp_content_chapter_id,
            subsection_id=session.temp_content_subsection_id,
            chapter_title=session.temp_lesson_chapter_title,
            section_title=session.temp_lesson_section_title,
            subsection_number=session.temp_lesson_subsection_number,
            subsection_title=session.temp_lesson_subsection_title,
            day_number=session.temp_lesson_day_number,
            day_title=session.temp_lesson_day_title,
            book_pages=session.temp_lesson_book_pages,
            pdf_start_page=session.temp_lesson_pdf_start_page,
            pdf_end_page=session.temp_lesson_pdf_end_page,
            printed_start_page=session.temp_lesson_printed_start_page,
            printed_end_page=session.temp_lesson_printed_end_page,
            resource_profile="Resource-Limited" if session.temp_content_subsection_id else None,
            format_profile="Detailed" if session.temp_content_subsection_id else None,
        )
        if lesson is None:
            session.current_state = ConversationState.NEW_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "duplicate_lesson_name"), ConversationState.NEW_LESSON_NAME)

        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(self._text(language, "lesson_saved"), language)

    def _handle_new_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not text:
            log_event(logger, "validation_failure", field="lesson_name", value=text)
            return self._reply(self._text(language, "lesson_name_invalid"), ConversationState.NEW_LESSON_NAME)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        return self._save_generated_lesson_with_name(session, teacher, text, language)

    def _handle_retrieve_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if choice in {"0", "back", "वापस"} or self._is_main_menu_choice(choice):
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "back_main"), language)

        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "create_profile_first"), language)

        lesson_summaries = self._localize_lesson_summaries(
            self.lesson_repo.list_accessible_summaries_for_teacher(teacher.id),
            language,
        )
        if not lesson_summaries:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "all_lessons_empty"), language)

        if choice.startswith("lesson_page:"):
            raw_page = choice.split(":", 1)[1].strip()
            page = int(raw_page) if raw_page.isdigit() else 0
            return self._show_accessible_lessons(session, teacher.id, language, page=page)

        selected_summary = None

        if choice.startswith("lesson_id:"):
            raw_lesson_id = choice.split(":", 1)[1].strip()
            if raw_lesson_id.isdigit():
                selected_summary = next(
                    (item for item in lesson_summaries if item.lesson_id == int(raw_lesson_id)),
                    None,
                )
        elif text and text.isdigit():
            lesson_index = int(text)
            if 1 <= lesson_index <= len(lesson_summaries):
                selected_summary = lesson_summaries[lesson_index - 1]
            else:
                return self._reply(
                    self._text(language, "invalid_lesson_number"),
                    ConversationState.RETRIEVE_LESSON_NAME,
                )
        else:
            exact_match = next(
                (
                    item
                    for item in lesson_summaries
                    if item.display_title.casefold() == choice or item.lesson_name.casefold() == choice
                ),
                None,
            )
            if exact_match:
                selected_summary = exact_match
            else:
                prefix_matches = [
                    item
                    for item in lesson_summaries
                    if item.display_title.casefold().startswith(choice) or item.lesson_name.casefold().startswith(choice)
                ]
                if len(prefix_matches) == 1:
                    selected_summary = prefix_matches[0]
                else:
                    if len(lesson_summaries) <= 10:
                        return self._reply(
                            self._text(language, "choose_from_list"),
                            ConversationState.RETRIEVE_LESSON_NAME,
                        )
                    return self._reply(
                        self._text(language, "enter_lesson_number"),
                        ConversationState.RETRIEVE_LESSON_NAME,
                    )

        if not selected_summary:
            return self._reply(
                self._text(language, "lesson_not_found_try"),
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        accessible_lesson = self.lesson_repo.get_accessible_lesson_by_teacher_and_id(
            teacher.id,
            selected_summary.lesson_id,
        )
        if not accessible_lesson:
            return self._reply(
                self._text(language, "lesson_not_found_try"),
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        session.temp_selected_lesson_id = accessible_lesson.lesson.id
        session.current_state = ConversationState.LESSON_ACTION_MENU.value
        self.session_repo.save(session)

        return self._lesson_action_reply(
            accessible_lesson.lesson.lesson_text,
            is_shared=accessible_lesson.is_shared,
            shared_by_teacher_name=accessible_lesson.shared_by_teacher_name,
            language=language,
        )

    def _handle_lesson_action_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "create_profile_first"), language)

        lesson_id = session.temp_selected_lesson_id
        if not lesson_id:
            return self._show_accessible_lessons(session, teacher.id, language)

        accessible_lesson = self.lesson_repo.get_accessible_lesson_by_teacher_and_id(teacher.id, lesson_id)
        if not accessible_lesson:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "that_lesson_missing"), language)

        choice = normalize_choice(text)

        if choice in {"lesson_action_back", "3", "0", "back", "cancel", "menu", "main menu", "वापस"}:
            return self._show_accessible_lessons(session, teacher.id, language)

        if accessible_lesson.is_shared:
            return self._lesson_action_reply(
                accessible_lesson.lesson.lesson_text,
                is_shared=True,
                shared_by_teacher_name=accessible_lesson.shared_by_teacher_name,
                prefix=self._text(language, "shared_view_only"),
                language=language,
            )

        if choice in {"lesson_action_share", "1", "share", "share lesson", "साझा करें"}:
            session.current_state = ConversationState.SHARE_LESSON_PHONE.value
            self.session_repo.save(session)
            return self._share_lesson_phone_prompt(accessible_lesson.lesson.lesson_name, language)

        if choice in {"lesson_action_delete", "2", "delete", "delete lesson", "डिलीट"}:
            session.current_state = ConversationState.DELETE_LESSON_CONFIRM.value
            self.session_repo.save(session)
            return self._delete_lesson_confirm_reply(accessible_lesson.lesson.lesson_name, language)

        return self._lesson_action_reply(
            accessible_lesson.lesson.lesson_text,
            is_shared=False,
            prefix=self._text(language, "choose_action"),
            language=language,
        )

    def _handle_share_lesson_phone(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "create_profile_first"), language)

        lesson_id = session.temp_selected_lesson_id
        if not lesson_id:
            return self._show_accessible_lessons(session, teacher.id, language)

        accessible_lesson = self.lesson_repo.get_accessible_lesson_by_teacher_and_id(teacher.id, lesson_id)
        if not accessible_lesson:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "that_lesson_missing"), language)

        if accessible_lesson.is_shared:
            session.current_state = ConversationState.LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._lesson_action_reply(
                accessible_lesson.lesson.lesson_text,
                is_shared=True,
                shared_by_teacher_name=accessible_lesson.shared_by_teacher_name,
                prefix=self._text(language, "owner_only_share"),
                language=language,
            )

        choice = normalize_choice(text)
        if choice in {"0", "back", "cancel", "lesson_action_back", "वापस"}:
            session.current_state = ConversationState.LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._lesson_action_reply(accessible_lesson.lesson.lesson_text, is_shared=False, language=language)

        recipient_number = (text or "").strip()
        if not recipient_number:
            return self._share_lesson_phone_prompt(accessible_lesson.lesson.lesson_name, language)

        recipient_teacher = self.teacher_repo.get_by_whatsapp_number(recipient_number)
        if not recipient_teacher:
            return self._reply(
                self._text(language, "recipient_not_found"),
                ConversationState.SHARE_LESSON_PHONE,
            )

        if recipient_teacher.id == teacher.id:
            return self._reply(
                self._text(language, "share_self"),
                ConversationState.SHARE_LESSON_PHONE,
            )

        share = self.lesson_repo.share_owned_lesson(
            lesson_id=accessible_lesson.lesson.id,
            owner_teacher_id=teacher.id,
            shared_with_teacher_id=recipient_teacher.id,
        )
        if share is None:
            session.current_state = ConversationState.LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._lesson_action_reply(
                accessible_lesson.lesson.lesson_text,
                is_shared=False,
                prefix=self._text(language, "share_failed"),
                language=language,
            )

        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(
            self._text(language, "share_success", lesson_name=accessible_lesson.lesson.lesson_name, teacher_name=recipient_teacher.teacher_name),
            language,
        )

    def _handle_delete_lesson_confirm(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "create_profile_first"), language)

        lesson_id = session.temp_selected_lesson_id
        if not lesson_id:
            return self._show_accessible_lessons(session, teacher.id, language)

        lesson = self.lesson_repo.get_by_teacher_and_id(teacher.id, lesson_id)
        if not lesson:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "that_lesson_missing"), language)

        choice = normalize_choice(text)

        if choice in {"cancel_delete_lesson", "2", "cancel", "no", "back", "0", "रद्द करें", "वापस"}:
            session.current_state = ConversationState.LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._lesson_action_reply(lesson.lesson_text, is_shared=False, language=language)

        if choice in {"confirm_delete_lesson", "1", "yes", "yes, delete", "delete", "हाँ", "डिलीट"}:
            lesson_name = lesson.lesson_name
            deleted = self.lesson_repo.delete_owned_lesson(teacher.id, lesson.id)
            if not deleted:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply(self._text(language, "that_lesson_missing"), language)

            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "delete_success", lesson_name=lesson_name), language)

        return self._delete_lesson_confirm_reply(lesson.lesson_name, language)
