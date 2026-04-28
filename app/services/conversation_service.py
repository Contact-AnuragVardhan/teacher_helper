from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import DEFAULT_LANGUAGE, language_key, normalize_language
from app.core.logging import get_logger, log_event
from app.repositories.lesson_repository import LessonRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.teacher_repository import TeacherRepository
from app.services.lesson_generator import LessonGeneratorService
from app.services.lesson_payload_builder import LessonPayloadBuilder
from app.state_machine.states import ConversationState
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.subject_normalization import normalize_subject
from app.utils.text import clean_text, normalize_choice

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
        "new_lesson_without_profile": "कृपया पहले अपनी प्रोफ़ाइल पूरी करें।\nआपका नाम क्या है?",
        "new_lesson_topic_prompt": "आप किस विषय पर पाठ पढ़ाना चाहते हैं? उदाहरण: \"The Portrait of a Lady\"",
        "new_lesson_topic_invalid": "कृपया पाठ का विषय लिखें, उदाहरण: \"The Portrait of a Lady\"।",
        "new_lesson_grade_prompt": "इस पाठ के लिए ग्रेड/कक्षा लिखें। उदाहरण: 1, 2, 3",
        "new_lesson_subject_prompt": "इस पाठ का विषय/सब्जेक्ट लिखें। उदाहरण: English",
        "duration_prompt": "कक्षा की अवधि मिनटों में लिखें। उदाहरण: 35",
        "invalid_duration": "कृपया कक्षा की अवधि मिनटों में लिखें, उदाहरण 35।",
        "generated_lesson_prefix": "यह आपकी तैयार की गई पाठ योजना है:",
        "save_body": "क्या आप इस पाठ को सेव करना चाहते हैं?",
        "save_footer": "एक विकल्प चुनें",
        "btn_save": "पाठ सेव करें",
        "btn_cancel": "रद्द करें",
        "save_invalid": "कृपया एक विकल्प चुनें:\n1 → पाठ सेव करें\n2 → रद्द करें",
        "lesson_cancelled": "पाठ सेव नहीं किया गया।",
        "lesson_name_prompt": "कृपया इस पाठ का नाम लिखें। उदाहरण: \"The Portrait of a Lady\"",
        "lesson_name_invalid": "पाठ का नाम खाली नहीं हो सकता। कृपया पाठ का नाम लिखें, उदाहरण: \"The Portrait of a Lady\"।",
        "duplicate_lesson_name": "इस नाम से एक पाठ पहले से मौजूद है। कृपया कोई दूसरा नाम लिखें, उदाहरण \"The Portrait of a Lady\"।",
        "lesson_saved": "आपका पाठ सेव हो गया है।",
        "profile_start": "आइए आपकी प्रोफ़ाइल सेट करते हैं। आपका नाम क्या है?",
        "profile_name_prompt": "कृपया अपना नाम लिखें।",
        "profile_grade_prompt": "आपकी डिफ़ॉल्ट ग्रेड/कक्षा क्या है? उदाहरण: 1, 2, 3",
        "profile_subject_prompt": "आप कौन सा विषय पढ़ाते हैं? उदाहरण: English",
        "profile_language_prompt": "कृपया पसंदीदा भाषा लिखें। विकल्प: {options}",
        "profile_language_invalid": "यह भाषा अभी समर्थित नहीं है। कृपया नीचे दिए गए विकल्पों में से एक लिखें।",
        "profile_saved": "आपकी प्रोफ़ाइल सेव हो गई है।",
        "profile_updated": "आइए आपकी प्रोफ़ाइल अपडेट करते हैं।",
        "current_profile": "वर्तमान प्रोफ़ाइल:\nनाम: {name}\nग्रेड: {grade}\nविषय: {subject}\nभाषा: {language}",
        "profile_name_edit": "अपना नाम लिखें, या वर्तमान नाम रखने के लिए 'same' भेजें।",
        "profile_grade_edit": "वर्तमान ग्रेड/कक्षा: {grade}\nनई ग्रेड/कक्षा लिखें, या रखने के लिए 'same' भेजें। उदाहरण: 1, 2, 3",
        "profile_subject_edit": "वर्तमान विषय: {subject}\nनया विषय लिखें, या रखने के लिए 'same' भेजें। उदाहरण: English",
        "profile_language_edit": "वर्तमान भाषा: {language}\nनई भाषा लिखें, या रखने के लिए 'same' भेजें। विकल्प: {options}",
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
        "new_lesson_without_profile": "Please complete your profile first.\nWhat is your name?",
        "new_lesson_topic_prompt": "What lesson topic would you like to teach? Example: \"The Portrait of a Lady\"",
        "new_lesson_topic_invalid": "Please enter a lesson topic, for example \"The Portrait of a Lady\".",
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
        "lesson_name_prompt": "Please enter a name for this lesson. Example: \"The Portrait of a Lady\"",
        "lesson_name_invalid": "Lesson name cannot be blank. Please enter a lesson name, for example \"The Portrait of a Lady\".",
        "duplicate_lesson_name": "A lesson with this name already exists. Please enter another lesson name, for example \"The Portrait of a Lady\".",
        "lesson_saved": "Your lesson has been saved.",
        "profile_start": "Let us set up your profile. What is your name?",
        "profile_name_prompt": "Please enter your name.",
        "profile_grade_prompt": "What is your default grade/class? Example: 1, 2, 3",
        "profile_subject_prompt": "What subject do you teach? Example: English",
        "profile_language_prompt": "Please enter preferred language. Options: {options}",
        "profile_language_invalid": "Preferred language is not supported right now. Please enter one of the configured options shown below.",
        "profile_saved": "Your profile has been saved.",
        "profile_updated": "Let us update your profile.",
        "current_profile": "Current profile:\nName: {name}\nGrade: {grade}\nSubject: {subject}\nLanguage: {language}",
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
        "new_lesson_without_profile": "Please pehle apni profile complete karein.\nAapka naam kya hai?",
        "new_lesson_topic_prompt": "Aap kis topic par lesson banana chahte hain? Example: \"The Portrait of a Lady\"",
        "new_lesson_topic_invalid": "Please lesson topic likhein, example: \"The Portrait of a Lady\".",
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
        "lesson_name_prompt": "Please is lesson ka naam likhein. Example: \"The Portrait of a Lady\"",
        "lesson_name_invalid": "Lesson name blank nahi ho sakta. Please lesson name likhein, example \"The Portrait of a Lady\".",
        "duplicate_lesson_name": "Is naam se lesson already exist karta hai. Please dusra naam likhein, example \"The Portrait of a Lady\".",
        "lesson_saved": "Aapka lesson save ho gaya hai.",
        "profile_start": "Chaliye profile setup karte hain. Aapka naam kya hai?",
        "profile_name_prompt": "Please apna naam likhein.",
        "profile_grade_prompt": "Aapki default grade/class kya hai? Example: 1, 2, 3",
        "profile_subject_prompt": "Aap kaunsa subject padhate hain? Example: English",
        "profile_language_prompt": "Please preferred language likhein. Options: {options}",
        "profile_language_invalid": "Yeh language abhi supported nahi hai. Please neeche diye options mein se ek likhein.",
        "profile_saved": "Aapki profile save ho gayi hai.",
        "profile_updated": "Chaliye profile update karte hain.",
        "current_profile": "Current profile:\nName: {name}\nGrade: {grade}\nSubject: {subject}\nLanguage: {language}",
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
        self.session_repo = SessionRepository(db)
        self.lesson_generator = LessonGeneratorService(db)
        self.lesson_payload_builder = LessonPayloadBuilder()

    def handle_message(self, whatsapp_number: str, incoming_text: str) -> ConversationReply:
        session, was_reset = self.session_repo.get_or_create(whatsapp_number)
        self.session_repo.touch(session)
        if was_reset:
            log_event(logger, "session_stale_reset", whatsapp_number=whatsapp_number)

        state = ConversationState(session.current_state)
        text = clean_text(incoming_text)
        log_event(logger, "conversation_inbound", whatsapp_number=whatsapp_number, state=state.value, body=text)

        handler_map = {
            ConversationState.MAIN_MENU: self._handle_main_menu,
            ConversationState.PROFILE_NAME: self._handle_profile_name,
            ConversationState.PROFILE_GRADE: self._handle_profile_grade,
            ConversationState.PROFILE_SUBJECT: self._handle_profile_subject,
            ConversationState.PROFILE_LANGUAGE: self._handle_profile_language,
            ConversationState.NEW_LESSON_TOPIC: self._handle_new_lesson_topic,
            ConversationState.NEW_LESSON_GRADE: self._handle_new_lesson_grade,
            ConversationState.NEW_LESSON_SUBJECT: self._handle_new_lesson_subject,
            ConversationState.NEW_LESSON_DURATION: self._handle_new_lesson_duration,
            ConversationState.NEW_LESSON_CONFIRM_SAVE: self._handle_new_lesson_confirm_save,
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

    def _text(self, language: str | None, key: str, **kwargs) -> str:
        lang = language_key(language)
        template = TEXT.get(lang, TEXT["hindi"]).get(key) or TEXT["english"].get(key) or key
        return template.format(**kwargs)

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

    def _teacher_language(self, teacher) -> str:
        return normalize_language(getattr(teacher, "preferred_language", None)) or DEFAULT_LANGUAGE

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
        return normalize_choice(text) in {"same", "skip", "keep", "current"}

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
                ],
            },
        )

    def _all_lessons_interactive_reply(self, lesson_summaries: list[tuple[int, str]], language: str) -> ConversationReply:
        rows = []
        for lesson_id, title in lesson_summaries:
            item = {
                "id": f"lesson_id:{lesson_id}",
                "title": title[:24],
            }
            if len(title) > 24:
                item["description"] = title[:72]
            rows.append(item)

        return self._reply(
            self._text(language, "all_lessons_reply"),
            ConversationState.RETRIEVE_LESSON_NAME,
            outbound={
                "type": "list",
                "header": self._text(language, "all_lessons_header"),
                "body": self._text(language, "all_lessons_body"),
                "button_text": self._text(language, "all_lessons_button"),
                "section_title": self._text(language, "all_lessons_section"),
                "footer": self._text(language, "all_lessons_footer"),
                "rows": rows,
            },
        )

    def _all_lessons_fallback_reply(self, titles: list[str], language: str) -> ConversationReply:
        reply_text = self._text(
            language,
            "all_lessons_fallback",
            titles=self._format_numbered_titles(titles),
        )
        return self._reply(reply_text, ConversationState.RETRIEVE_LESSON_NAME)

    def _show_accessible_lessons(self, session, teacher_id: int, language: str) -> ConversationReply:
        lesson_summaries = self.lesson_repo.list_accessible_summaries_for_teacher(teacher_id)
        if not lesson_summaries:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "all_lessons_empty"), language)

        session.current_state = ConversationState.RETRIEVE_LESSON_NAME.value
        session.temp_selected_lesson_id = None
        self.session_repo.save(session)

        if len(lesson_summaries) <= 10:
            return self._all_lessons_interactive_reply(
                [(item.lesson_id, item.display_title) for item in lesson_summaries],
                language,
            )

        return self._all_lessons_fallback_reply([item.display_title for item in lesson_summaries], language)

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
                    {"id": "lesson_action_back", "title": self._text(language, "btn_back")},
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
                    {"id": "lesson_action_back", "title": self._text(language, "btn_back")},
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
                ],
            },
        )

    def _handle_main_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        choice = normalize_choice(text)

        if not choice or self._is_greeting(choice):
            return self._main_menu_reply(self._text(language, "welcome"), language)

        if choice in {"1", "new lesson", "menu_new_lesson", "naya lesson", "नया पाठ"}:
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

            session.temp_profile_grade = None
            session.temp_profile_subject = None
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
                self.session_repo.save(session)
                return self._reply(self._profile_name_edit_prompt(teacher, language), ConversationState.PROFILE_NAME)

            self.session_repo.save(session)
            return self._reply(self._text(language, "profile_start"), ConversationState.PROFILE_NAME)

        return self._main_menu_reply(self._text(language, "main_menu_unknown"), language)

    def _handle_profile_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            if teacher:
                return self._reply(self._profile_name_edit_prompt(teacher, language), ConversationState.PROFILE_NAME)
            return self._reply(self._text(language, "profile_name_prompt"), ConversationState.PROFILE_NAME)

        if teacher and self._is_keep_value(text):
            session.temp_profile_name = teacher.teacher_name
        else:
            session.temp_profile_name = text

        session.current_state = ConversationState.PROFILE_GRADE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_grade_edit_prompt(teacher, language), ConversationState.PROFILE_GRADE)
        return self._reply(self._text(language, "profile_grade_prompt"), ConversationState.PROFILE_GRADE)

    def _handle_profile_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            if teacher:
                return self._reply(self._profile_grade_edit_prompt(teacher, language), ConversationState.PROFILE_GRADE)
            return self._reply(self._text(language, "profile_grade_prompt"), ConversationState.PROFILE_GRADE)

        if teacher and self._is_keep_value(text):
            grade_value = teacher.default_grade
        else:
            grade_value = text.strip()
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
        language = self._teacher_language(teacher)
        if not text:
            if teacher:
                return self._reply(self._profile_subject_edit_prompt(teacher, language), ConversationState.PROFILE_SUBJECT)
            return self._reply(self._text(language, "profile_subject_prompt"), ConversationState.PROFILE_SUBJECT)

        if teacher and self._is_keep_value(text):
            subject_value = teacher.default_subject
        else:
            subject_value = normalize_subject(text)
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
        session.current_state = ConversationState.PROFILE_LANGUAGE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_language_edit_prompt(teacher, language), ConversationState.PROFILE_LANGUAGE)
        return self._reply(self._profile_language_prompt(language), ConversationState.PROFILE_LANGUAGE)

    def _handle_profile_language(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
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

        self.teacher_repo.upsert(
            whatsapp_number=whatsapp_number,
            teacher_name=session.temp_profile_name or "",
            default_grade=session.temp_profile_grade or "",
            default_subject=session.temp_profile_subject or "",
            preferred_language=language_value,
        )
        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(self._text(language_value, "profile_saved"), language_value)

    def _handle_new_lesson_topic(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            log_event(logger, "validation_failure", field="topic", value=text)
            return self._reply(self._text(language, "new_lesson_topic_invalid"), ConversationState.NEW_LESSON_TOPIC)

        session.temp_topic = text
        session.current_state = ConversationState.NEW_LESSON_GRADE.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_grade_prompt(language), ConversationState.NEW_LESSON_GRADE)

    def _handle_new_lesson_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            return self._reply(self._new_lesson_grade_prompt(language), ConversationState.NEW_LESSON_GRADE)

        grade_error = self._localize_validation_error(validate_profile_grade(text, self.settings), language)
        if grade_error:
            log_event(logger, "validation_failure", field="lesson_grade", value=text)
            return self._reply(
                f"{grade_error}\n{self._new_lesson_grade_prompt(language)}",
                ConversationState.NEW_LESSON_GRADE,
            )

        session.temp_profile_grade = text.strip()
        session.current_state = ConversationState.NEW_LESSON_SUBJECT.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_subject_prompt(language), ConversationState.NEW_LESSON_SUBJECT)

    def _handle_new_lesson_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            return self._reply(self._new_lesson_subject_prompt(language), ConversationState.NEW_LESSON_SUBJECT)

        lesson_grade = session.temp_profile_grade or ""
        normalized_subject = normalize_subject(text)
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
        language = self._teacher_language(teacher)
        try:
            duration = int(text)
            if duration <= 0:
                raise ValueError
        except (TypeError, ValueError):
            log_event(logger, "validation_failure", field="duration_minutes", value=text)
            return self._reply(self._text(language, "invalid_duration"), ConversationState.NEW_LESSON_DURATION)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject

        generation_result = self.lesson_generator.generate(
            teacher=teacher,
            topic=session.temp_topic or "",
            duration_minutes=duration,
            grade=lesson_grade,
            subject=lesson_subject,
        )
        session.temp_duration_minutes = duration
        session.temp_generated_lesson = generation_result.lesson_text
        session.current_state = ConversationState.NEW_LESSON_CONFIRM_SAVE.value
        self.session_repo.save(session)

        return self._save_menu_reply(generation_result.lesson_text, language)

    def _handle_new_lesson_confirm_save(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        choice = normalize_choice(text)

        if choice in {"1", "save lesson", "save_lesson", "पाठ सेव करें"}:
            session.current_state = ConversationState.NEW_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "lesson_name_prompt"), ConversationState.NEW_LESSON_NAME)

        if choice in {"2", "cancel", "cancel_lesson", "रद्द करें", "radd"}:
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
                ],
            },
        )

    def _handle_new_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        if not text:
            log_event(logger, "validation_failure", field="lesson_name", value=text)
            return self._reply(self._text(language, "lesson_name_invalid"), ConversationState.NEW_LESSON_NAME)

        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject

        lesson_payload = self.lesson_payload_builder.build(
            teacher_id=teacher.id,
            lesson_name=text,
            grade=lesson_grade,
            subject=lesson_subject,
            topic=session.temp_topic or "",
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
        )

        lesson = self.lesson_repo.create_or_update_by_policy(
            teacher_id=teacher.id,
            lesson_name=text,
            topic=session.temp_topic or "",
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
            lesson_payload=lesson_payload,
        )
        if lesson is None:
            return self._reply(self._text(language, "duplicate_lesson_name"), ConversationState.NEW_LESSON_NAME)

        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(self._text(language, "lesson_saved"), language)

    def _handle_retrieve_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher)
        choice = normalize_choice(text)

        if choice in {"0", "menu", "main menu", "back", "वापस"}:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "back_main"), language)

        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "create_profile_first"), language)

        lesson_summaries = self.lesson_repo.list_accessible_summaries_for_teacher(teacher.id)
        if not lesson_summaries:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "all_lessons_empty"), language)

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
        language = self._teacher_language(teacher)
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
        language = self._teacher_language(teacher)
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
        language = self._teacher_language(teacher)
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
