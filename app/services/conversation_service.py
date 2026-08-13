from dataclasses import dataclass, replace
import base64
import json
from datetime import datetime
import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import DEFAULT_LANGUAGE, language_key, normalize_language
from app.core.logging import get_logger, log_event
from app.repositories.embedding_content_repository import (
    EmbeddingContentRepository,
    EmbeddingLessonMatch,
    EmbeddingPageExtraction,
    EmbeddingSubsection,
    EmbeddingTeacherSchedule,
    EmbeddingTeacherScheduleDay,
)
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.lesson_repository import AccessibleLessonSummary, LessonRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.teacher_repository import TeacherRepository
from app.services.feedback_survey_service import FeedbackSurveyService
from app.services.lesson_generator import LessonGeneratorService
from app.services.lesson_payload_builder import LessonPayloadBuilder
from app.services.lesson_pdf_service import LessonPdfMetadata, LessonPdfService
from app.services.pdf_content_lesson_service import PdfContentLessonService
from app.services.preferred_language_api_service import PreferredLanguageApiService
from app.services.subject_resolver import SubjectResolver
from app.state_machine.states import ConversationState
from app.utils.lesson_title_localization import localize_lesson_display_title
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.subject_normalization import normalize_subject, subject_display_name
from app.utils.toc_terminology import toc_label
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
        "main_menu_unknown": "मैं नया पाठ बनाने, सेव किए गए पाठ देखने, प्रोफ़ाइल अपडेट करने या फीडबैक देने में मदद कर सकता हूँ। कृपया नीचे दिए गए विकल्पों में से एक चुनें।",
        "main_header": "Teacher Helper",
        "main_body": "एक विकल्प चुनें",
        "main_footer": "नीचे एक विकल्प टैप करें",
        "btn_new_lesson": "नया पाठ",
        "btn_all_lessons": "सभी पाठ",
        "btn_profile": "प्रोफ़ाइल",
        "btn_feedback": "फीडबैक",
        "main_menu_button": "मेनू",
        "main_menu_section": "Teacher Helper",
        "feedback_intro": "कृपया इस सप्ताह की Lesson Plans के बारे में छोटा फीडबैक दें। अंतिम जवाब के बाद आपके जवाब सेव हो जाएंगे।",
        "feedback_choice_invalid": "कृपया Yes, Sometimes या No चुनें।",
        "feedback_text_invalid": "कृपया इस प्रश्न का छोटा जवाब लिखें।",
        "feedback_short_answer_instruction": "कृपया अपना छोटा जवाब लिखें।",
        "feedback_saved": "धन्यवाद। आपका फीडबैक सेव हो गया है।",
        "feedback_unavailable": "फीडबैक फॉर्म अभी उपलब्ध नहीं है। कृपया बाद में फिर कोशिश करें।",
        "btn_main_menu": "मुख्य मेनू",
        "all_lessons_body_page": "खोलने के लिए पाठ चुनें। पेज {page}/{total_pages}",
        "all_lessons_next": "अगला पेज",
        "all_lessons_previous": "पिछला पेज",
        "new_lesson_without_profile": "कृपया पहले अपनी प्रोफ़ाइल पूरी करें।\nआपका नाम क्या है?",
        "new_lesson_topic_prompt": "कृपया नीचे पुस्तक की विषय-सूची (TOC) से सही पाठ/अध्याय चुनें।",
        "new_lesson_topic_invalid": "कृपया पुस्तक की विषय-सूची (TOC) से सही विकल्प चुनें।",
        "lesson_topic_header": "पुस्तक TOC से चुनें",
        "lesson_topic_body": "ग्रेड और विषय के आधार पर पुस्तक TOC से विकल्प चुनें। पेज {page}/{total_pages}.",
        "lesson_topic_button": "पुस्तक TOC",
        "lesson_topic_section": "पुस्तक TOC",
        "lesson_topic_footer": "नीचे सही TOC विकल्प टैप करें।",
        "lesson_topic_empty": "{school_name} में कक्षा {grade} / {subject} के लिए पुस्तक TOC का कोई विकल्प नहीं मिला। कृपया विषय फिर से लिखें या मुख्य मेनू पर वापस जाएँ।",
        "lesson_topic_next": "अगला पेज",
        "lesson_topic_previous": "पिछला पेज",
        "new_lesson_grade_prompt": "इस पाठ के लिए ग्रेड/कक्षा लिखें। उदाहरण: 1, 2, 3",
        "new_lesson_subject_prompt": "इस पाठ का विषय/सब्जेक्ट लिखें। उदाहरण: गणित",
        "duration_prompt": "कक्षा की अवधि मिनटों में लिखें। उदाहरण: 35",
        "invalid_duration": "कृपया कक्षा की अवधि मिनटों में लिखें, उदाहरण 35।",
        "generated_lesson_prefix": "यह आपकी तैयार की गई पाठ योजना है:",
        "lesson_ready_action_body": "अब इस पाठ के लिए एक विकल्प चुनें।",
        "lesson_ready_action_footer": "पाठ का उपयोग, बदलाव या प्रिंट चुनें",
        "btn_use_lesson": "पाठ उपयोग करें",
        "btn_customize_lesson": "पाठ बदलें",
        "btn_print_lesson": "पाठ प्रिंट करें",
        "lesson_ready_invalid": "कृपया पाठ का उपयोग करें, पाठ बदलें या पाठ प्रिंट करें विकल्प चुनें।",
        "print_lesson_ready": "आपकी पाठ योजना PDF तैयार है।",
        "print_lesson_failed": "पाठ योजना PDF नहीं बन सकी। कृपया फिर से Print Lesson चुनें।",
        "print_lesson_caption": "Teacher Helper - पाठ योजना",
        "customize_header": "पाठ बदलें",
        "customize_body": "वर्तमान पुस्तक पृष्ठ सीमा: {current_range}\n{item_type} पुस्तक पृष्ठ सीमा: {chapter_range}\nचुना हुआ From Book Page: {from_page}\nचुना हुआ To Book Page: {to_page}",
        "not_selected": "नहीं चुना गया",
        "customize_button": "विकल्प",
        "customize_section": "पेज बदलें",
        "customize_footer": "From/To बदलें, फिर updated lesson बनाएँ।",
        "customize_invalid": "कृपया From Book Page, To Book Page, बनाएँ/सेव करें या वापस चुनें।",
        "customize_from_row": "1. From Book Page",
        "customize_to_row": "2. To Book Page",
        "customize_create_row": "4. बनाएँ/सेव करें",
        "customize_back_row": "5. वापस",
        "customize_from_prompt": "नया From Book Page लिखें। यह {item_type} की पुस्तक पृष्ठ सीमा {chapter_range} के भीतर होना चाहिए।",
        "customize_to_prompt": "नया To Book Page लिखें। यह {item_type} की पुस्तक पृष्ठ सीमा {chapter_range} के भीतर होना चाहिए।",
        "customize_page_invalid": "यह पुस्तक पृष्ठ इस {item_type} में नहीं है। उपलब्ध पुस्तक पृष्ठ सीमा: {chapter_range}।",
        "customize_range_invalid": "From Book Page, To Book Page से आगे नहीं हो सकता और सभी चुने हुए पुस्तक पृष्ठ लगातार होने चाहिए। वर्तमान चयन: {from_page}-{to_page}।",
        "customize_pages_unavailable": "इस {item_type} के पुस्तक-पृष्ठ extraction उपलब्ध नहीं हैं, इसलिए पुस्तक पृष्ठ के अनुसार बदलाव नहीं किया जा सकता।",
        "customize_text_unavailable": "चुने हुए पुस्तक पृष्ठों में पाठ बनाने के लिए टेक्स्ट नहीं मिला। कृपया दूसरी लगातार पुस्तक-पृष्ठ सीमा चुनें।",
        "customized_lesson_prefix": "यह चुने हुए पुस्तक पृष्ठों से दोबारा तैयार किया गया पाठ है:",
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
        "lesson_no_match": "इसके लिए पुस्तक TOC में कोई मिलान नहीं मिला: {topic}\n\nकृपया किताब की विषय-सूची से सही शीर्षक लिखें।",
        "lesson_summary_intro": "मुझे यह {item_type} मिला:\n{title}\nपुस्तक पृष्ठ: {pages}\n\nसरल सारांश:\n{summary}\n\nअब detailed पाठ योजना के लिए दिन चुनें।",
        "lesson_day_header": "दिन चुनें",
        "lesson_day_body": "एक दिन चुनें।",
        "lesson_day_button": "दिन",
        "lesson_day_section": "दिन",
        "day_label": "दिन {number}",
        "chapter_number_label": "{item_type} {number}",
        "pages_label": "पुस्तक पृष्ठ {pages}",
        "lesson_day_footer": "नीचे एक दिन टैप करें।",
        "lesson_day_invalid": "कृपया सूची से सही दिन चुनें।",
        "lesson_schedule_header": "सप्ताह चुनें",
        "lesson_schedule_body": "इस अध्याय के लिए शिक्षक की एक से अधिक साप्ताहिक योजनाएँ मिलीं। सही सप्ताह चुनें।",
        "lesson_schedule_button": "सप्ताह",
        "lesson_schedule_section": "शिक्षक योजना",
        "lesson_schedule_footer": "नीचे सही सप्ताह टैप करें।",
        "lesson_schedule_invalid": "कृपया सूची से सही सप्ताह चुनें।",
        "lesson_schedule_intro": "इस अध्याय के लिए शिक्षक की साप्ताहिक योजना उपलब्ध है।",
        "lesson_schedule_day_body": "{week_label} | अभ्यास {exercise}\nदिन चुनें।",
        "lesson_schedule_day_footer": "निर्धारित प्रश्न और पुस्तक पृष्ठ के अनुसार दिन चुनें।",
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
        "main_menu_unknown": "I can help with creating a new lesson, viewing saved lessons, updating your profile, or giving feedback. Please choose one of the options below.",
        "main_header": "Teacher Helper",
        "main_body": "Choose an option",
        "main_footer": "Tap one option below",
        "btn_new_lesson": "New Lesson",
        "btn_all_lessons": "All Lessons",
        "btn_profile": "My Profile",
        "btn_feedback": "Feedback",
        "main_menu_button": "Menu",
        "main_menu_section": "Teacher Helper",
        "feedback_intro": "Please answer this short weekly Lesson Plan feedback. Your answers will be saved after the final question.",
        "feedback_choice_invalid": "Please choose Yes, Sometimes, or No.",
        "feedback_text_invalid": "Please type a short answer for this question.",
        "feedback_short_answer_instruction": "Please type your short answer.",
        "feedback_saved": "Thank you. Your feedback has been saved.",
        "feedback_unavailable": "The feedback form is temporarily unavailable. Please try again later.",
        "btn_main_menu": "Back to Main Menu",
        "all_lessons_body_page": "Choose a lesson to open. Page {page}/{total_pages}.",
        "all_lessons_next": "Next Page",
        "all_lessons_previous": "Previous Page",
        "new_lesson_without_profile": "Please complete your profile first.\nWhat is your name?",
        "new_lesson_topic_prompt": "Please select what you would like to teach from the book TOC below.",
        "new_lesson_topic_invalid": "Please select a valid item from the book TOC below.",
        "lesson_topic_header": "Choose from Book TOC",
        "lesson_topic_body": "Select an item from the book TOC for the grade and subject you entered. Page {page}/{total_pages}.",
        "lesson_topic_button": "Book TOC",
        "lesson_topic_section": "Book TOC",
        "lesson_topic_footer": "Tap one TOC item below.",
        "lesson_topic_empty": "No book TOC item was found for {school_name}, Class {grade}, {subject}. Please enter the subject again, or send Main Menu to go back.",
        "lesson_topic_next": "Next Page",
        "lesson_topic_previous": "Previous Page",
        "new_lesson_grade_prompt": "Please enter the grade/class for this lesson. Example: 1, 2, 3",
        "new_lesson_subject_prompt": "Please enter the subject for this lesson. Example: English",
        "duration_prompt": "Please enter class duration in minutes. Example: 35",
        "invalid_duration": "Please enter class duration in minutes, for example 35.",
        "generated_lesson_prefix": "Here is your generated lesson plan:",
        "lesson_ready_action_body": "Choose what you want to do with this generated lesson.",
        "lesson_ready_action_footer": "Use, customize, or print the lesson",
        "btn_use_lesson": "Use this lesson",
        "btn_customize_lesson": "Customize Lesson",
        "btn_print_lesson": "Print Lesson",
        "lesson_ready_invalid": "Please choose Use this lesson, Customize Lesson, or Print Lesson.",
        "print_lesson_ready": "Your lesson plan PDF is ready.",
        "print_lesson_failed": "The lesson plan PDF could not be created. Please choose Print Lesson again.",
        "print_lesson_caption": "Teacher Helper - Lesson Plan",
        "customize_header": "Customize Lesson",
        "customize_body": "Current book-page range: {current_range}\n{item_type} book-page range: {chapter_range}\nSelected From Book Page: {from_page}\nSelected To Book Page: {to_page}",
        "not_selected": "Not selected",
        "customize_button": "Options",
        "customize_section": "Change Pages",
        "customize_footer": "Change From/To Book Pages, then create and save the updated lesson.",
        "customize_invalid": "Please choose From Book Page, To Book Page, Create/Save, or Back.",
        "customize_from_row": "1. From Book Page",
        "customize_to_row": "2. To Book Page",
        "customize_create_row": "4. Create/Save",
        "customize_back_row": "5. Back",
        "customize_from_prompt": "Enter the new From Book Page. It must be within this {item_type} book-page range: {chapter_range}.",
        "customize_to_prompt": "Enter the new To Book Page. It must be within this {item_type} book-page range: {chapter_range}.",
        "customize_page_invalid": "That book page is not inside this {item_type}. Available book-page range: {chapter_range}.",
        "customize_range_invalid": "From Book Page cannot be after To Book Page, and every selected book page must be contiguous. Current selection: {from_page}-{to_page}.",
        "customize_pages_unavailable": "Book-page extraction is not available for this {item_type}, so the lesson cannot be customized by book page.",
        "customize_text_unavailable": "No usable text was found in the selected book pages. Please choose another contiguous book-page range.",
        "customized_lesson_prefix": "Here is the lesson regenerated from your selected book pages:",
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
        "lesson_no_match": "No matching item was found in the book TOC for: {topic}\n\nPlease type the exact title from the book TOC.",
        "lesson_summary_intro": "I found this {item_type}:\n{title}\nBook Pages: {pages}\n\nSimple summary:\n{summary}\n\nNow choose the day for the detailed lesson plan.",
        "lesson_day_header": "Choose Day",
        "lesson_day_body": "Select one day.",
        "lesson_day_button": "Days",
        "lesson_day_section": "Days",
        "day_label": "Day {number}",
        "chapter_number_label": "{item_type} {number}",
        "pages_label": "Book Pages {pages}",
        "lesson_day_footer": "Tap one day below.",
        "lesson_day_invalid": "Please choose a valid day from the list.",
        "lesson_schedule_header": "Choose Week",
        "lesson_schedule_body": "More than one teacher schedule is available for this chapter. Choose the week you want to teach.",
        "lesson_schedule_button": "Weeks",
        "lesson_schedule_section": "Teacher Schedule",
        "lesson_schedule_footer": "Tap the correct week below.",
        "lesson_schedule_invalid": "Please choose a valid week from the list.",
        "lesson_schedule_intro": "A teacher weekly schedule is available for this chapter.",
        "lesson_schedule_day_body": "{week_label} | Exercise {exercise}\nChoose a day.",
        "lesson_schedule_day_footer": "Choose the day based on the assigned questions and book pages.",
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
        "main_menu_unknown": "Main new lesson create karne, saved lessons dekhne, profile update karne, ya feedback dene mein help kar sakta hoon. Neeche se ek option choose karein.",
        "main_header": "Teacher Helper",
        "main_body": "Option choose karein",
        "main_footer": "Neeche option tap karein",
        "btn_new_lesson": "Naya Lesson",
        "btn_all_lessons": "All Lessons",
        "btn_profile": "Profile",
        "btn_feedback": "Feedback",
        "main_menu_button": "Menu",
        "main_menu_section": "Teacher Helper",
        "feedback_intro": "Please is week ke Lesson Plans par short feedback dein. Final answer ke baad aapke answers save ho jayenge.",
        "feedback_choice_invalid": "Please Yes, Sometimes, ya No choose karein.",
        "feedback_text_invalid": "Please is question ka short answer type karein.",
        "feedback_short_answer_instruction": "Please apna short answer type karein.",
        "feedback_saved": "Thank you. Aapka feedback save ho gaya hai.",
        "feedback_unavailable": "Feedback form abhi available nahi hai. Please baad mein phir try karein.",
        "btn_main_menu": "Main Menu",
        "all_lessons_body_page": "Open karne ke liye lesson choose karein. Page {page}/{total_pages}.",
        "all_lessons_next": "Next Page",
        "all_lessons_previous": "Previous Page",
        "new_lesson_without_profile": "Please pehle apni profile complete karein.\nAapka naam kya hai?",
        "new_lesson_topic_prompt": "Please neeche book TOC se jo padhana hai woh choose karein.",
        "new_lesson_topic_invalid": "Please book TOC se valid item choose karein.",
        "lesson_topic_header": "Choose from Book TOC",
        "lesson_topic_body": "Entered grade aur subject ke liye book TOC item choose karein. Page {page}/{total_pages}.",
        "lesson_topic_button": "Book TOC",
        "lesson_topic_section": "Book TOC",
        "lesson_topic_footer": "Neeche ek TOC item tap karein.",
        "lesson_topic_empty": "{school_name} mein Class {grade} / {subject} ke liye koi book TOC item nahi mila. Please subject phir se likhein ya Main Menu bhejein.",
        "lesson_topic_next": "Next Page",
        "lesson_topic_previous": "Previous Page",
        "new_lesson_grade_prompt": "Is lesson ke liye grade/class likhein. Example: 1, 2, 3",
        "new_lesson_subject_prompt": "Is lesson ka subject likhein. Example: English",
        "duration_prompt": "Class duration minutes mein likhein. Example: 35",
        "invalid_duration": "Please class duration minutes mein likhein, example 35.",
        "generated_lesson_prefix": "Yeh aapka generated lesson plan hai:",
        "lesson_ready_action_body": "Generated lesson ke saath kya karna hai, option choose karein.",
        "lesson_ready_action_footer": "Use, customize ya print choose karein",
        "btn_use_lesson": "Use Lesson",
        "btn_customize_lesson": "Customize",
        "btn_print_lesson": "Print Lesson",
        "lesson_ready_invalid": "Please Use Lesson, Customize, ya Print Lesson choose karein.",
        "print_lesson_ready": "Aapki lesson plan PDF ready hai.",
        "print_lesson_failed": "Lesson plan PDF create nahi ho saki. Please Print Lesson dobara choose karein.",
        "print_lesson_caption": "Teacher Helper - Lesson Plan",
        "customize_header": "Customize Lesson",
        "customize_body": "Current book-page range: {current_range}\n{item_type} book-page range: {chapter_range}\nSelected From Book Page: {from_page}\nSelected To Book Page: {to_page}",
        "not_selected": "Not selected",
        "customize_button": "Options",
        "customize_section": "Change Pages",
        "customize_footer": "From/To Book Pages change karke updated lesson create/save karein.",
        "customize_invalid": "Please From Book Page, To Book Page, Create/Save ya Back choose karein.",
        "customize_from_row": "1. From Book Page",
        "customize_to_row": "2. To Book Page",
        "customize_create_row": "4. Create/Save",
        "customize_back_row": "5. Back",
        "customize_from_prompt": "New From Book Page likhein. Yeh {item_type} book-page range {chapter_range} ke andar hona chahiye.",
        "customize_to_prompt": "New To Book Page likhein. Yeh {item_type} book-page range {chapter_range} ke andar hona chahiye.",
        "customize_page_invalid": "Yeh book page is {item_type} ke andar nahi hai. Available book-page range: {chapter_range}.",
        "customize_range_invalid": "From Book Page, To Book Page ke baad nahi ho sakta aur selected book pages contiguous hone chahiye. Current selection: {from_page}-{to_page}.",
        "customize_pages_unavailable": "Is {item_type} ke book-page extractions available nahi hain, isliye book-page customization possible nahi hai.",
        "customize_text_unavailable": "Selected book pages mein usable text nahi mila. Please doosra contiguous book-page range choose karein.",
        "customized_lesson_prefix": "Yeh selected book pages se regenerated lesson hai:",
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
        "lesson_no_match": "Is topic ke liye book TOC mein matching item nahi mila: {topic}\n\nPlease book TOC ka exact title type karein.",
        "lesson_summary_intro": "Mujhe yeh {item_type} mila:\n{title}\nBook Pages: {pages}\n\nSimple summary:\n{summary}\n\nAb detailed lesson plan ke liye day choose karein.",
        "lesson_day_header": "Choose Day",
        "lesson_day_body": "Ek day select karein.",
        "lesson_day_button": "Days",
        "lesson_day_section": "Days",
        "day_label": "Day {number}",
        "chapter_number_label": "{item_type} {number}",
        "pages_label": "Book Pages {pages}",
        "lesson_day_footer": "Neeche ek day tap karein.",
        "lesson_day_invalid": "Please list se valid day choose karein.",
        "lesson_schedule_header": "Choose Week",
        "lesson_schedule_body": "Is chapter ke liye ek se zyada teacher schedules available hain. Sahi week choose karein.",
        "lesson_schedule_button": "Weeks",
        "lesson_schedule_section": "Teacher Schedule",
        "lesson_schedule_footer": "Neeche correct week tap karein.",
        "lesson_schedule_invalid": "Please list se valid week choose karein.",
        "lesson_schedule_intro": "Is chapter ke liye teacher weekly schedule available hai.",
        "lesson_schedule_day_body": "{week_label} | Exercise {exercise}\nEk day choose karein.",
        "lesson_schedule_day_footer": "Assigned questions aur book pages ke hisaab se day choose karein.",
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
        self.feedback_repo = FeedbackRepository(db)
        self.lesson_repo = LessonRepository(db)
        self.embedding_content_repo = EmbeddingContentRepository(db)
        self.session_repo = SessionRepository(db)
        self.feedback_survey_service = FeedbackSurveyService()
        self.lesson_generator = LessonGeneratorService(db)
        self.pdf_content_lesson_service = PdfContentLessonService(db)
        self.lesson_payload_builder = LessonPayloadBuilder()
        self.lesson_pdf_service = LessonPdfService(self.settings)
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
        # A greeting is a global home command. This prevents values such as
        # "Hi"/"Hello"/"Namaste" from being accidentally stored as a profile
        # field, page choice, lesson name, feedback answer, etc.
        if self._is_greeting(choice):
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            language = self._teacher_language(teacher, whatsapp_number)
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "welcome"), language)

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
            ConversationState.NEW_LESSON_SCHEDULE: self._handle_new_lesson_schedule,
            ConversationState.NEW_LESSON_DAY: self._handle_new_lesson_day,
            ConversationState.NEW_LESSON_SUBJECT: self._handle_new_lesson_subject,
            ConversationState.NEW_LESSON_DURATION: self._handle_new_lesson_duration,
            ConversationState.NEW_LESSON_ACTION_MENU: self._handle_new_lesson_action_menu,
            ConversationState.NEW_LESSON_CUSTOMIZE_MENU: self._handle_new_lesson_customize_menu,
            ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE: self._handle_new_lesson_customize_from_page,
            ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE: self._handle_new_lesson_customize_to_page,
            ConversationState.NEW_LESSON_CONFIRM_SAVE: self._handle_new_lesson_confirm_save,
            ConversationState.NEW_LESSON_CONFIRM_NAME: self._handle_new_lesson_confirm_name,
            ConversationState.NEW_LESSON_NAME: self._handle_new_lesson_name,
            ConversationState.RETRIEVE_LESSON_NAME: self._handle_retrieve_lesson_name,
            ConversationState.LESSON_ACTION_MENU: self._handle_lesson_action_menu,
            ConversationState.SHARE_LESSON_PHONE: self._handle_share_lesson_phone,
            ConversationState.DELETE_LESSON_CONFIRM: self._handle_delete_lesson_confirm,
            ConversationState.FEEDBACK_QUESTION: self._handle_feedback_question,
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
        normalized = re.sub(r"[^0-9a-zA-Z\u0900-\u097F]+", " ", (choice or "").casefold()).strip()
        if not normalized:
            return False
        exact_greetings = {
            "hi", "hii", "hiii", "hello", "helo", "hey", "hola",
            "namaste", "namaskar", "pranam", "hello ji", "hi ji", "namaste ji",
            "good morning", "good afternoon", "good evening", "good night", "start",
            "नमस्ते", "नमस्कार", "प्रणाम", "नमस्ते जी", "नमस्कार जी", "शुरू",
        }
        if normalized in exact_greetings:
            return True
        # Treat a message beginning with an unambiguous greeting as the same
        # global home command, e.g. "Hello teacher" or "Namaste sir".
        return bool(
            re.match(
                r"^(?:hi+|hello|helo|hey|hola|namaste|namaskar|pranam|good\s+(?:morning|afternoon|evening|night)|नमस्ते|नमस्कार|प्रणाम)(?:\s|$)",
                normalized,
            )
        )

    def _toc_item_label(self, lesson: EmbeddingLessonMatch, language: str, *, title_case: bool = False) -> str:
        label = toc_label(lesson.toc_kind, language)
        if title_case or language_key(language) == "hindi":
            return label
        return label.casefold()

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
        # WhatsApp reply-button messages support at most 3 buttons. The main menu
        # now has 4 choices, so use a list message to keep every option tappable.
        return {
            "type": "list",
            "header": self._text(language, "main_header"),
            "body": self._text(language, "main_body"),
            "button_text": self._text(language, "main_menu_button"),
            "section_title": self._text(language, "main_menu_section"),
            "footer": self._text(language, "main_footer"),
            "rows": [
                {"id": "menu_new_lesson", "title": self._text(language, "btn_new_lesson")},
                {"id": "menu_all_lessons", "title": self._text(language, "btn_all_lessons")},
                {"id": "menu_my_profile", "title": self._text(language, "btn_profile")},
                {"id": "menu_feedback", "title": self._text(language, "btn_feedback")},
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

    def _generated_lesson_action_outbound(self, language: str) -> dict:
        return {
            "type": "buttons",
            "header": self._text(language, "main_header"),
            "body": self._text(language, "lesson_ready_action_body"),
            "footer": self._text(language, "lesson_ready_action_footer"),
            "buttons": [
                {"id": "use_generated_lesson", "title": self._text(language, "btn_use_lesson")},
                {"id": "customize_generated_lesson", "title": self._text(language, "btn_customize_lesson")},
                {"id": "print_generated_lesson", "title": self._text(language, "btn_print_lesson")},
            ],
        }

    def _generated_lesson_action_reply(
        self,
        lesson_text: str,
        language: str,
        *,
        prefix: str | None = None,
    ) -> ConversationReply:
        reply_parts = []
        if prefix:
            reply_parts.append(prefix.strip())
        reply_parts.append(f"{self._text(language, 'generated_lesson_prefix')}\n\n{lesson_text}")
        return self._reply(
            "\n\n".join(part for part in reply_parts if part),
            ConversationState.NEW_LESSON_ACTION_MENU,
            outbound=self._generated_lesson_action_outbound(language),
        )

    def _print_generated_lesson_reply(self, *, session, teacher, language: str) -> ConversationReply:
        lesson_text = (session.temp_generated_lesson or "").strip()
        if not lesson_text:
            return self._generated_lesson_action_reply(
                "",
                language,
                prefix=self._text(language, "print_lesson_failed"),
            )

        day_title = session.temp_lesson_day_title or (
            f"Day {session.temp_lesson_day_number}" if session.temp_lesson_day_number else ""
        )
        pdf_subject = subject_display_name(
            normalize_subject(session.temp_profile_subject or getattr(teacher, "default_subject", "") or ""),
            language=language,
        )
        source_lesson = self.embedding_content_repo.get_lesson_by_chapter_id(session.temp_content_chapter_id or "")
        metadata = LessonPdfMetadata(
            teacher_name=getattr(teacher, "teacher_name", "") or "",
            school_name=session.temp_lesson_school_name or getattr(teacher, "school_name", "") or "",
            grade=session.temp_profile_grade or getattr(teacher, "default_grade", "") or "",
            subject=pdf_subject,
            duration_minutes=session.temp_duration_minutes,
            book_title=session.temp_lesson_book_title or "",
            chapter_title=session.temp_lesson_chapter_title or session.temp_topic or "",
            section_title=session.temp_lesson_section_title or "",
            content_type_label=(toc_label(source_lesson.toc_kind, language) if source_lesson else ""),
            content_title=(source_lesson.title if source_lesson else ""),
            day_title=day_title,
            pages=session.temp_lesson_book_pages or "",
            is_customized=bool(session.temp_lesson_is_customized),
            preferred_language=language,
        )

        try:
            generated_pdf = self.lesson_pdf_service.generate(
                lesson_text=lesson_text,
                metadata=metadata,
            )
        except Exception as exc:
            log_event(
                logger,
                "lesson_pdf_generation_failed",
                teacher_id=getattr(teacher, "id", None),
                chapter_id=session.temp_content_chapter_id,
                error=str(exc),
            )
            return self._generated_lesson_action_reply(
                lesson_text,
                language,
                prefix=self._text(language, "print_lesson_failed"),
            )

        encoded_pdf = base64.b64encode(generated_pdf.content).decode("ascii")
        session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
        self.session_repo.save(session)
        log_event(
            logger,
            "lesson_pdf_generated",
            teacher_id=getattr(teacher, "id", None),
            chapter_id=session.temp_content_chapter_id,
            filename=generated_pdf.filename,
            pdf_size_bytes=len(generated_pdf.content),
            customized=bool(session.temp_lesson_is_customized),
        )
        return self._reply(
            self._text(language, "print_lesson_ready"),
            ConversationState.NEW_LESSON_ACTION_MENU,
            outbound={
                "type": "sequence",
                "messages": [
                    {
                        "type": "document",
                        "filename": generated_pdf.filename,
                        "content_type": "application/pdf",
                        "content_base64": encoded_pdf,
                        "caption": self._text(language, "print_lesson_caption"),
                    },
                    self._generated_lesson_action_outbound(language),
                ],
            },
        )

    def _customize_lesson_reply(
        self,
        *,
        session,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
        language: str,
        prefix: str | None = None,
    ) -> ConversationReply:
        chapter_range = self._chapter_page_range(lesson, pages)
        current_range = self._current_day_book_page_range(session, lesson, pages)
        item_type = self._toc_item_label(lesson, language)
        from_page = session.temp_customize_from_page or session.temp_lesson_printed_start_page or self._text(language, "not_selected")
        to_page = session.temp_customize_to_page or session.temp_lesson_printed_end_page or self._text(language, "not_selected")
        body = self._text(
            language,
            "customize_body",
            current_range=current_range,
            chapter_range=chapter_range,
            from_page=from_page,
            to_page=to_page,
            item_type=item_type,
        )
        reply_parts = [prefix.strip()] if prefix else []
        reply_parts.append(body)
        return self._reply(
            "\n\n".join(reply_parts),
            ConversationState.NEW_LESSON_CUSTOMIZE_MENU,
            outbound={
                "type": "list",
                "header": self._text(language, "customize_header"),
                "body": body,
                "button_text": self._text(language, "customize_button"),
                "section_title": self._text(language, "customize_section"),
                "footer": self._text(language, "customize_footer"),
                "rows": [
                    {"id": "customize_from_page", "title": self._text(language, "customize_from_row")[:24]},
                    {"id": "customize_to_page", "title": self._text(language, "customize_to_row")[:24]},
                    {"id": "customize_create_save", "title": self._text(language, "customize_create_row")[:24]},
                    {"id": "customize_back", "title": self._text(language, "customize_back_row")[:24]},
                ],
            },
        )

    def _customize_from_page_prompt_reply(
        self,
        *,
        session,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
        language: str,
        prefix: str | None = None,
    ) -> ConversationReply:
        chapter_range = self._chapter_page_range(lesson, pages)
        current_range = self._current_day_book_page_range(session, lesson, pages)
        item_type = self._toc_item_label(lesson, language)
        parts = []
        if prefix:
            parts.append(prefix.strip())
        parts.append(
            f"{self._text(language, 'customize_header')}\n"
            f"{self._text(language, 'customize_body', current_range=current_range, chapter_range=chapter_range, from_page=self._text(language, 'not_selected'), to_page=self._text(language, 'not_selected'), item_type=item_type)}\n\n"
            f"{self._text(language, 'customize_from_prompt', chapter_range=chapter_range, item_type=item_type)}"
        )
        return self._reply(
            "\n\n".join(parts),
            ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE,
        )

    def _customize_to_page_prompt_reply(
        self,
        *,
        session,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
        language: str,
        prefix: str | None = None,
    ) -> ConversationReply:
        chapter_range = self._chapter_page_range(lesson, pages)
        current_range = self._current_day_book_page_range(session, lesson, pages)
        item_type = self._toc_item_label(lesson, language)
        from_page = session.temp_customize_from_page or self._text(language, "not_selected")
        parts = []
        if prefix:
            parts.append(prefix.strip())
        parts.append(
            f"{self._text(language, 'customize_header')}\n"
            f"{self._text(language, 'customize_body', current_range=current_range, chapter_range=chapter_range, from_page=from_page, to_page=self._text(language, 'not_selected'), item_type=item_type)}\n\n"
            f"{self._text(language, 'customize_to_prompt', chapter_range=chapter_range, item_type=item_type)}"
        )
        return self._reply(
            "\n\n".join(parts),
            ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE,
        )

    @staticmethod
    def _is_missing_book_page_range(value: str | None) -> bool:
        normalized = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
        return normalized in {
            "",
            "not available",
            "n/a",
            "na",
            "none",
            "null",
            "not selected",
        }

    def _current_day_book_page_range(
        self,
        session,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
    ) -> str:
        """Resolve the current selected day's teacher-facing book-page range.

        Do not trust an old session value containing the literal
        ``Not available``. Prefer the selected day's stored printed bounds,
        then recover from page_extractions using the selected day's internal
        PDF coordinates. Physical PDF numbers are never displayed.
        """
        stored = getattr(session, "temp_lesson_book_pages", None)
        if not self._is_missing_book_page_range(stored):
            return str(stored).strip()

        printed_start = getattr(session, "temp_lesson_printed_start_page", None)
        printed_end = getattr(session, "temp_lesson_printed_end_page", None)
        if printed_start and printed_end:
            if str(printed_start).strip() == str(printed_end).strip():
                return str(printed_start).strip()
            return f"{str(printed_start).strip()}-{str(printed_end).strip()}"

        pdf_start = getattr(session, "temp_lesson_pdf_start_page", None)
        pdf_end = getattr(session, "temp_lesson_pdf_end_page", None)
        if pdf_start is not None and pdf_end is not None:
            selected_book_pages = [
                page
                for page in pages
                if pdf_start <= page.pdf_page_number <= pdf_end and page.book_page_label
            ]
            if selected_book_pages:
                start_label = selected_book_pages[0].display_page
                end_label = selected_book_pages[-1].display_page
                resolved = start_label if start_label == end_label else f"{start_label}-{end_label}"
                # Repair stale session state while we have authoritative data.
                session.temp_lesson_book_pages = resolved
                session.temp_lesson_printed_start_page = start_label
                session.temp_lesson_printed_end_page = end_label
                # Persist the repaired metadata because each WhatsApp message
                # may run in a fresh database session/request.
                self.session_repo.save(session)
                return resolved

        subsection_id = getattr(session, "temp_content_subsection_id", None)
        if subsection_id:
            subsection = self.embedding_content_repo.get_subsection_by_id(subsection_id)
            if subsection and not self._is_missing_book_page_range(subsection.display_pages):
                session.temp_lesson_book_pages = subsection.display_pages
                session.temp_lesson_printed_start_page = subsection.printed_start_page
                session.temp_lesson_printed_end_page = subsection.printed_end_page
                self.session_repo.save(session)
                return subsection.display_pages

        return lesson.display_pages

    def _chapter_page_range(
        self,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
    ) -> str:
        book_pages = [page for page in pages if page.book_page_label]
        if book_pages:
            return f"{book_pages[0].display_page}-{book_pages[-1].display_page}"
        return lesson.display_pages

    def _initialize_custom_page_selection(
        self,
        session,
        pages: list[EmbeddingPageExtraction],
    ) -> None:
        start_choice = session.temp_lesson_printed_start_page or None
        end_choice = session.temp_lesson_printed_end_page or None
        start_page = self.embedding_content_repo.resolve_page_choice(pages, start_choice)
        end_page = self.embedding_content_repo.resolve_page_choice(pages, end_choice)
        book_pages = [page for page in pages if page.book_page_label]
        if not start_page and book_pages:
            start_page = book_pages[0]
        if not end_page and book_pages:
            end_page = book_pages[-1]
        session.temp_customize_from_page = start_page.display_page if start_page else start_choice
        session.temp_customize_to_page = end_page.display_page if end_page else end_choice

    def _ensure_customized_lesson_name(self, lesson_name: str) -> str:
        cleaned = (lesson_name or "").strip()
        if cleaned.endswith("*"):
            return cleaned
        return f"{cleaned[:254]}*"

    def _lesson_topic_reply(
        self,
        *,
        lessons: list[EmbeddingLessonMatch],
        language: str,
        page: int = 0,
    ) -> ConversationReply:
        page_size = 7
        total_lessons = len(lessons)
        total_pages = max(1, (total_lessons + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        start_index = page * page_size
        page_lessons = lessons[start_index : start_index + page_size]

        rows: list[dict[str, str]] = []
        for index, lesson in enumerate(page_lessons, start=start_index + 1):
            title = lesson.title or f"Lesson {index}"
            description_parts: list[str] = []
            if lesson.toc_number:
                description_parts.append(
                    self._text(
                        language,
                        "chapter_number_label",
                        item_type=self._toc_item_label(lesson, language, title_case=True),
                        number=lesson.toc_number,
                    )
                )
            # The book has already been selected before the TOC is shown.
            # Repeating the (often long) book title here can consume WhatsApp's
            # short list-row description and hide the more useful book-page range.
            if lesson.display_pages != "Not available":
                description_parts.append(self._text(language, "pages_label", pages=lesson.display_pages))
            rows.append(
                {
                    "id": f"lesson_topic:{lesson.chapter_id}",
                    "title": title[:24],
                    "description": " | ".join(part for part in description_parts if part)[:72],
                }
            )

        if page > 0:
            rows.append({"id": f"lesson_topic_page:{page - 1}", "title": self._text(language, "lesson_topic_previous")[:24]})
        if page < total_pages - 1:
            rows.append({"id": f"lesson_topic_page:{page + 1}", "title": self._text(language, "lesson_topic_next")[:24]})
        rows.append(self._main_menu_row(language))

        return self._reply(
            self._text(language, "new_lesson_topic_prompt"),
            ConversationState.NEW_LESSON_TOPIC,
            outbound={
                "type": "list",
                "header": self._text(language, "lesson_topic_header"),
                "body": self._text(
                    language,
                    "lesson_topic_body",
                    page=page + 1,
                    total_pages=total_pages,
                ),
                "button_text": self._text(language, "lesson_topic_button"),
                "section_title": self._text(language, "lesson_topic_section"),
                "footer": self._text(language, "lesson_topic_footer"),
                "rows": rows,
            },
        )

    def _lesson_topic_list_for_session(self, session, teacher) -> list[EmbeddingLessonMatch]:
        return self.embedding_content_repo.list_lessons_for_selection(
            school_name=(getattr(teacher, "school_name", None) or "").strip(),
            grade=(session.temp_profile_grade or "").strip() or teacher.default_grade,
            subject=(session.temp_profile_subject or "").strip() or teacher.default_subject,
        )

    def _resolve_lesson_topic_choice(
        self,
        *,
        choice: str,
        text: str,
        lessons: list[EmbeddingLessonMatch],
        teacher,
        session,
    ) -> EmbeddingLessonMatch | None:
        selected_id = ""
        if choice.startswith("lesson_topic:"):
            selected_id = choice.split(":", 1)[1].strip()
        if selected_id:
            for lesson in lessons:
                if lesson.chapter_id == selected_id:
                    return lesson
            return self.embedding_content_repo.get_lesson_by_chapter_id(selected_id)

        raw = (text or choice or "").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(lessons):
                return lessons[index - 1]

        if raw:
            return self.embedding_content_repo.find_lesson_match(
                school_name=(getattr(teacher, "school_name", None) or "").strip(),
                grade=(session.temp_profile_grade or "").strip() or teacher.default_grade,
                subject=(session.temp_profile_subject or "").strip() or teacher.default_subject,
                topic=raw,
            )
        return None

    def _store_selected_lesson_topic(self, session, lesson: EmbeddingLessonMatch) -> None:
        session.temp_topic = lesson.title
        session.temp_content_document_id = lesson.document_id
        session.temp_content_chapter_id = lesson.chapter_id
        session.temp_lesson_document_key = lesson.document_key
        session.temp_lesson_book_title = lesson.book_title
        session.temp_lesson_school_name = lesson.school_name
        session.temp_lesson_chapter_title = lesson.chapter_title
        session.temp_lesson_section_title = lesson.section_title

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
            day_label = self._text(language, "day_label", number=index)
            description_parts = [subsection.title]
            if subsection.display_pages != "Not available":
                description_parts.append(self._text(language, "pages_label", pages=subsection.display_pages))
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
            item_type=self._toc_item_label(lesson, language),
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

    def _lesson_schedule_reply(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        schedules: list[EmbeddingTeacherSchedule],
        summary: str,
        language: str,
    ) -> ConversationReply:
        rows: list[dict[str, str]] = []
        for schedule in schedules[:9]:
            week_label = self._format_teacher_schedule_date(schedule.week_start_date)
            exercise = (schedule.exercise or "").strip()
            title_parts = [week_label]
            if exercise:
                title_parts.append(f"Ex {exercise}")
            title = " · ".join(part for part in title_parts if part) or "Teacher Schedule"
            description = f"{max(schedule.day_count, 0)} days"
            rows.append(
                {
                    "id": f"lesson_schedule:{schedule.id}",
                    "title": title[:24],
                    "description": description[:72],
                }
            )
        rows.append(self._main_menu_row(language))

        reply_parts = [
            self._text(language, "lesson_schedule_intro"),
            f"{self._toc_item_label(lesson, language)}: {lesson.title}",
            self._text(language, "pages_label", pages=lesson.display_pages),
        ]
        if summary:
            reply_parts.extend(["", summary])
        reply_parts.extend(["", self._text(language, "lesson_schedule_body")])
        reply_text = "\n".join(reply_parts)
        return self._reply(
            reply_text,
            ConversationState.NEW_LESSON_SCHEDULE,
            outbound={
                "type": "list",
                "header": self._text(language, "lesson_schedule_header"),
                "body": self._text(language, "lesson_schedule_body"),
                "button_text": self._text(language, "lesson_schedule_button"),
                "section_title": self._text(language, "lesson_schedule_section"),
                "footer": self._text(language, "lesson_schedule_footer"),
                "rows": rows,
            },
        )

    def _teacher_schedule_day_reply(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        schedule: EmbeddingTeacherSchedule,
        days: list[EmbeddingTeacherScheduleDay],
        summary: str,
        language: str,
    ) -> ConversationReply:
        rows: list[dict[str, str]] = []
        plain_day_lines: list[str] = []
        for index, day in enumerate(days[:9], start=1):
            weekday = (day.weekday or f"Day {day.day or index}").strip()
            questions = day.questions_display
            pages = day.display_pages
            description_parts: list[str] = []
            if questions:
                description_parts.append(questions)
            if pages != "Not available":
                description_parts.append(self._text(language, "pages_label", pages=pages))
            if not description_parts and day.activity:
                description_parts.append(day.activity)

            description = " | ".join(description_parts)
            rows.append(
                {
                    "id": f"teacher_day:{day.id}",
                    "title": weekday[:24],
                    "description": description[:72],
                }
            )

            # Keep a plain-text copy of the day menu in the message itself.
            # WhatsApp still receives the interactive list below, while browser/
            # local tester clients (or any channel that cannot render the list)
            # can still see and choose the scheduled days.
            line_parts = [f"{index}. {weekday}"]
            if questions:
                line_parts.append(f"Questions: {questions}")
            if pages != "Not available":
                line_parts.append(self._text(language, "pages_label", pages=pages))
            if len(line_parts) == 1 and day.activity:
                line_parts.append(day.activity)
            plain_day_lines.append(" — ".join(line_parts))

        rows.append(self._main_menu_row(language))

        week_label = self._format_teacher_schedule_date(schedule.week_start_date)
        exercise = (schedule.exercise or "-").strip() or "-"
        body = self._text(
            language,
            "lesson_schedule_day_body",
            week_label=week_label,
            exercise=exercise,
        )
        reply_parts = [
            self._text(language, "lesson_schedule_intro"),
            f"{self._toc_item_label(lesson, language)}: {lesson.title}",
            body,
        ]
        if plain_day_lines:
            reply_parts.extend(["", *plain_day_lines])
        if summary:
            reply_parts.extend(["", summary])
        reply_text = "\n".join(reply_parts)
        return self._reply(
            reply_text,
            ConversationState.NEW_LESSON_DAY,
            outbound={
                "type": "list",
                "header": self._text(language, "lesson_day_header"),
                "body": body,
                "button_text": self._text(language, "lesson_day_button"),
                "section_title": self._text(language, "lesson_day_section"),
                "footer": self._text(language, "lesson_schedule_day_footer"),
                "rows": rows,
            },
        )

    def _resolve_teacher_schedule_choice(
        self,
        *,
        choice: str,
        text: str,
        schedules: list[EmbeddingTeacherSchedule],
    ) -> EmbeddingTeacherSchedule | None:
        selected_id = ""
        if choice.startswith("lesson_schedule:"):
            selected_id = choice.split(":", 1)[1].strip()
        if selected_id:
            return next((item for item in schedules if item.id == selected_id), None) or self.embedding_content_repo.get_teacher_schedule_by_id(selected_id)

        raw = (text or choice or "").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(schedules):
                return schedules[index - 1]
        return None

    def _resolve_teacher_schedule_day_choice(
        self,
        *,
        choice: str,
        text: str,
        days: list[EmbeddingTeacherScheduleDay],
    ) -> tuple[int, EmbeddingTeacherScheduleDay] | None:
        selected_id = ""
        if choice.startswith("teacher_day:"):
            selected_id = choice.split(":", 1)[1].strip()
        if selected_id:
            for index, item in enumerate(days, start=1):
                if item.id == selected_id:
                    return index, item
            day = self.embedding_content_repo.get_teacher_schedule_day_by_id(selected_id)
            if day:
                return int(day.day or 1), day

        raw = (text or choice or "").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(days):
                return index, days[index - 1]

        normalized = normalize_choice(raw)
        for index, item in enumerate(days, start=1):
            if item.weekday and normalized == normalize_choice(item.weekday):
                return index, item
        return None

    @staticmethod
    def _format_teacher_schedule_date(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return "Week"
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
            return parsed.strftime("%b %d, %Y")
        except ValueError:
            return raw

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

    def _lesson_day_label_for_summary(self, item: AccessibleLessonSummary, language: str) -> str | None:
        if item.day_number:
            return self._text(language, "day_label", number=item.day_number)
        if item.day_title:
            return item.day_title.strip()
        return None

    def _lesson_option_title(self, item: AccessibleLessonSummary, language: str) -> str:
        day_label = self._lesson_day_label_for_summary(item, language)
        title = item.display_title or item.lesson_name
        if not day_label:
            return title
        # Keep the selected day visible in the WhatsApp option title whenever possible.
        short_day = day_label.replace("Day ", "D") if day_label.startswith("Day ") else day_label
        max_title_len = max(8, 23 - len(short_day))
        base = title[:max_title_len].rstrip()
        return f"{base} {short_day}".strip()

    def _lesson_option_description(self, item: AccessibleLessonSummary, language: str) -> str:
        parts: list[str] = []
        day_label = self._lesson_day_label_for_summary(item, language)
        if day_label:
            parts.append(day_label)
        if item.subsection_title and item.subsection_title != day_label:
            parts.append(item.subsection_title)
        if item.book_title:
            parts.append(item.book_title)
        if item.book_pages:
            parts.append(self._text(language, "pages_label", pages=item.book_pages))
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
            row_title = self._lesson_option_title(item_summary, language)
            row_description = self._lesson_option_description(item_summary, language)
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

    def _feedback_survey_or_none(self, language: str):
        try:
            return self.feedback_survey_service.load()
        except Exception as exc:  # pragma: no cover - defensive configuration handling.
            log_event(logger, "feedback_survey_unavailable", error=str(exc))
            return None

    @staticmethod
    def _feedback_answers(session) -> dict[str, str]:
        raw = (getattr(session, "temp_feedback_answers_json", None) or "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    @staticmethod
    def _feedback_choice_id(text: str) -> str | None:
        choice = normalize_choice(text)
        if choice.startswith("feedback_answer:"):
            value = choice.split(":", 1)[1].strip()
            return value if value in {"yes", "sometimes", "no"} else None

        aliases = {
            "yes": "yes",
            "y": "yes",
            "1": "yes",
            "haan": "yes",
            "ha": "yes",
            "हाँ": "yes",
            "sometimes": "sometimes",
            "sometime": "sometimes",
            "2": "sometimes",
            "kabhi kabhi": "sometimes",
            "कभी कभी": "sometimes",
            "कभी-कभी": "sometimes",
            "no": "no",
            "n": "no",
            "3": "no",
            "nahi": "no",
            "nahin": "no",
            "नहीं": "no",
        }
        return aliases.get(choice)

    def _feedback_question_reply(
        self,
        *,
        survey,
        question_index: int,
        language: str,
        include_intro: bool = False,
        validation_message: str | None = None,
    ) -> ConversationReply:
        questions = survey.flattened_questions()
        if not questions:
            return self._main_menu_reply(self._text(language, "feedback_unavailable"), language)

        question_index = max(0, min(question_index, len(questions) - 1))
        part, question = questions[question_index]
        question_text = f"{part.title}\n\n{question.number}. {question.text}"

        prefix_parts: list[str] = []
        if include_intro:
            prefix_parts.append(self._text(language, "feedback_intro"))
        if validation_message:
            prefix_parts.append(validation_message)

        if question.type == "choice":
            # The question itself is shown in the interactive button message.
            reply = "\n\n".join(prefix_parts).strip()
            return self._reply(
                reply,
                ConversationState.FEEDBACK_QUESTION,
                outbound={
                    "type": "buttons",
                    "header": survey.title,
                    "body": question_text,
                    "footer": f"Answer Format: {survey.choice_answer_format}",
                    "buttons": [
                        {"id": f"feedback_answer:{option.id}", "title": option.label}
                        for option in survey.choice_options
                    ],
                },
            )

        instruction = self._text(language, "feedback_short_answer_instruction")
        text_parts = [part.title, f"{question.number}. {question.text}", instruction]
        if include_intro:
            text_parts.insert(0, self._text(language, "feedback_intro"))
        if validation_message:
            text_parts.insert(0, validation_message)
        return self._reply(
            "\n\n".join(item for item in text_parts if item),
            ConversationState.FEEDBACK_QUESTION,
        )

    def _start_feedback(self, session, teacher, whatsapp_number: str, language: str) -> ConversationReply:
        survey = self._feedback_survey_or_none(language)
        if survey is None:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "feedback_unavailable"), language)

        session.temp_feedback_survey_key = survey.key
        session.temp_feedback_question_index = 0
        session.temp_feedback_answers_json = "{}"
        session.current_state = ConversationState.FEEDBACK_QUESTION.value
        self.session_repo.save(session)
        log_event(
            logger,
            "feedback_started",
            teacher_id=teacher.id,
            whatsapp_number=whatsapp_number,
            survey_id=survey.survey_id,
            survey_version=survey.version,
        )
        return self._feedback_question_reply(
            survey=survey,
            question_index=0,
            language=language,
            include_intro=True,
        )

    def _handle_feedback_question(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        survey = self._feedback_survey_or_none(language)
        if survey is None:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "feedback_unavailable"), language)

        if session.temp_feedback_survey_key != survey.key:
            return self._start_feedback(session, teacher, whatsapp_number, language)

        questions = survey.flattened_questions()
        question_index = session.temp_feedback_question_index or 0
        if question_index < 0 or question_index >= len(questions):
            return self._start_feedback(session, teacher, whatsapp_number, language)

        _, question = questions[question_index]
        answers = self._feedback_answers(session)

        if question.type == "choice":
            option_id = self._feedback_choice_id(text)
            option_lookup = {option.id: option.label for option in survey.choice_options}
            if option_id not in option_lookup:
                return self._feedback_question_reply(
                    survey=survey,
                    question_index=question_index,
                    language=language,
                    validation_message=self._text(language, "feedback_choice_invalid"),
                )
            answers[question.id] = option_lookup[option_id]
        else:
            answer_text = clean_text(text)
            if question.required and not answer_text:
                return self._feedback_question_reply(
                    survey=survey,
                    question_index=question_index,
                    language=language,
                    validation_message=self._text(language, "feedback_text_invalid"),
                )
            answers[question.id] = answer_text

        next_index = question_index + 1
        if next_index >= len(questions):
            self.feedback_repo.create_submission(
                teacher=teacher,
                whatsapp_number=whatsapp_number,
                survey=survey,
                answers=answers,
            )
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "feedback_saved"), language)

        session.temp_feedback_question_index = next_index
        session.temp_feedback_answers_json = json.dumps(answers, ensure_ascii=False)
        session.current_state = ConversationState.FEEDBACK_QUESTION.value
        self.session_repo.save(session)
        return self._feedback_question_reply(
            survey=survey,
            question_index=next_index,
            language=language,
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
            session.current_state = ConversationState.NEW_LESSON_GRADE.value
            self.session_repo.save(session)
            return self._reply(self._new_lesson_grade_prompt(language), ConversationState.NEW_LESSON_GRADE)

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

        if choice in {"4", "feedback", "menu_feedback", "फीडबैक"}:
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)
            return self._start_feedback(session, teacher, whatsapp_number, language)

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
        choice = normalize_choice(text)

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

        lessons = self._lesson_topic_list_for_session(session, teacher)
        if choice.startswith("lesson_topic_page:"):
            raw_page = choice.split(":", 1)[1].strip()
            page = int(raw_page) if raw_page.isdigit() else 0
            return self._lesson_topic_reply(lessons=lessons, language=language, page=page)

        if not text:
            log_event(logger, "validation_failure", field="lesson_topic_choice", value=text)
            return self._reply(
                f"{self._text(language, 'new_lesson_topic_invalid')}\n\n{self._text(language, 'new_lesson_topic_prompt')}",
                ConversationState.NEW_LESSON_TOPIC,
                outbound=self._lesson_topic_reply(lessons=lessons, language=language).outbound,
            )

        lesson_match = self._resolve_lesson_topic_choice(
            choice=choice,
            text=text,
            lessons=lessons,
            teacher=teacher,
            session=session,
        )
        if not lesson_match:
            log_event(
                logger,
                "embedding_lesson_topic_choice_invalid",
                teacher_id=teacher.id,
                school_name=school_name,
                grade=session.temp_profile_grade,
                subject=session.temp_profile_subject,
                value=text,
                option_count=len(lessons),
            )
            topic_reply = self._lesson_topic_reply(lessons=lessons, language=language)
            return self._reply(
                f"{self._text(language, 'new_lesson_topic_invalid')}\n\n{topic_reply.reply}",
                ConversationState.NEW_LESSON_TOPIC,
                outbound=topic_reply.outbound,
            )

        self._store_selected_lesson_topic(session, lesson_match)
        session.temp_content_subsection_id = None
        session.temp_teacher_schedule_id = None
        session.temp_teacher_schedule_day_id = None
        session.temp_duration_minutes = None
        session.current_state = ConversationState.NEW_LESSON_DURATION.value
        self.session_repo.save(session)

        log_event(
            logger,
            "lesson_topic_selected_from_embedding_list",
            teacher_id=teacher.id,
            school_name=school_name,
            grade=session.temp_profile_grade,
            subject=session.temp_profile_subject,
            chapter_id=lesson_match.chapter_id,
            title=lesson_match.title,
        )
        return self._reply(self._text(language, "duration_prompt"), ConversationState.NEW_LESSON_DURATION)

    def _handle_new_lesson_schedule(self, session, whatsapp_number: str, text: str) -> ConversationReply:
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

        schedules = self.embedding_content_repo.list_teacher_schedules_for_lesson(lesson)
        if not schedules:
            # Tables/schedules may have disappeared between requests. Fall back
            # to the original structural day flow rather than breaking the book.
            session.temp_teacher_schedule_id = None
            session.temp_teacher_schedule_day_id = None
            subsections = self.embedding_content_repo.list_subsections_for_lesson(lesson)
            if not subsections:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply(self._text(language, "lesson_no_match", topic=session.temp_topic or ""), language)
            session.current_state = ConversationState.NEW_LESSON_DAY.value
            self.session_repo.save(session)
            return self._lesson_day_reply(
                lesson=lesson,
                subsections=subsections,
                summary=session.temp_lesson_summary or "",
                language=language,
            )

        selected = self._resolve_teacher_schedule_choice(choice=choice, text=text, schedules=schedules)
        if not selected:
            reply = self._lesson_schedule_reply(
                lesson=lesson,
                schedules=schedules,
                summary="",
                language=language,
            )
            return self._reply(
                f"{self._text(language, 'lesson_schedule_invalid')}\n\n{reply.reply}",
                ConversationState.NEW_LESSON_SCHEDULE,
                outbound=reply.outbound,
            )

        days = self.embedding_content_repo.list_teacher_schedule_days(selected.id)
        if not days:
            # Do not strand the user on malformed schedule metadata.
            session.temp_teacher_schedule_id = None
            session.temp_teacher_schedule_day_id = None
            subsections = self.embedding_content_repo.list_subsections_for_lesson(lesson)
            if not subsections:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply(self._text(language, "lesson_no_match", topic=session.temp_topic or ""), language)
            session.current_state = ConversationState.NEW_LESSON_DAY.value
            self.session_repo.save(session)
            return self._lesson_day_reply(
                lesson=lesson,
                subsections=subsections,
                summary=session.temp_lesson_summary or "",
                language=language,
            )

        session.temp_teacher_schedule_id = selected.id
        session.temp_teacher_schedule_day_id = None
        session.current_state = ConversationState.NEW_LESSON_DAY.value
        self.session_repo.save(session)
        return self._teacher_schedule_day_reply(
            lesson=lesson,
            schedule=selected,
            days=days,
            summary="",
            language=language,
        )

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

        # New optional real-teacher schedule flow. It is entered only when the
        # selected chapter has rows in the additive schedule tables. Every book
        # without such rows continues into the original subsection flow below.
        if session.temp_teacher_schedule_id:
            schedule = self.embedding_content_repo.get_teacher_schedule_by_id(session.temp_teacher_schedule_id)
            days = self.embedding_content_repo.list_teacher_schedule_days(session.temp_teacher_schedule_id)
            if schedule and days:
                selected_schedule_day = self._resolve_teacher_schedule_day_choice(
                    choice=choice,
                    text=text,
                    days=days,
                )
                if not selected_schedule_day:
                    day_reply = self._teacher_schedule_day_reply(
                        lesson=lesson,
                        schedule=schedule,
                        days=days,
                        summary="",
                        language=language,
                    )
                    return self._reply(
                        f"{self._text(language, 'lesson_day_invalid')}\n\n{day_reply.reply}",
                        ConversationState.NEW_LESSON_DAY,
                        outbound=day_reply.outbound,
                    )

                day_number, schedule_day = selected_schedule_day
                subsection = self.embedding_content_repo.build_subsection_from_teacher_schedule_day(
                    lesson,
                    schedule,
                    schedule_day,
                )
                if subsection:
                    lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
                    lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject
                    requested_duration = session.temp_duration_minutes or 0
                    result = self.pdf_content_lesson_service.generate_day_lesson_plan(
                        lesson=lesson,
                        subsection=subsection,
                        day_number=int(schedule_day.day or day_number),
                        teacher=teacher,
                        grade=lesson_grade,
                        subject=lesson_subject,
                        duration_minutes=requested_duration,
                        preferred_language=language,
                    )
                    session.temp_content_subsection_id = subsection.id
                    session.temp_teacher_schedule_day_id = schedule_day.id
                    session.temp_lesson_day_number = int(schedule_day.day or day_number)
                    session.temp_lesson_day_title = (schedule_day.weekday or f"Day {day_number}")[:100]
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
                    session.temp_customize_from_page = subsection.printed_start_page
                    session.temp_customize_to_page = subsection.printed_end_page
                    session.temp_lesson_is_customized = False
                    session.temp_topic = lesson.title
                    session.temp_duration_minutes = requested_duration or result.duration_minutes
                    session.temp_generated_lesson = result.lesson_text
                    session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
                    self.session_repo.save(session)

                    log_event(
                        logger,
                        "lesson_day_generated_from_teacher_schedule",
                        teacher_id=teacher.id,
                        chapter_id=lesson.chapter_id,
                        teacher_schedule_id=schedule.id,
                        teacher_schedule_day_id=schedule_day.id,
                        week_start_date=schedule.week_start_date,
                        exercise=schedule.exercise,
                        questions=schedule_day.questions,
                        selected_book_pages=schedule_day.selected_book_pages,
                        selected_pdf_pages=schedule_day.selected_pdf_pages,
                        provider_used=result.provider_used,
                    )
                    return self._generated_lesson_action_reply(result.lesson_text, language)

                # If exact scheduled page text is unavailable, fail safe to the
                # original chapter/subsection flow instead of generating from a
                # partial or guessed source.
                log_event(
                    logger,
                    "teacher_schedule_day_source_unavailable_fallback",
                    chapter_id=lesson.chapter_id,
                    teacher_schedule_id=schedule.id,
                    teacher_schedule_day_id=schedule_day.id,
                )

            session.temp_teacher_schedule_id = None
            session.temp_teacher_schedule_day_id = None
            self.session_repo.save(session)

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
        # Re-resolve the selected day's printed/book page range immediately
        # before generation. This prevents a raw/stale subsection object from
        # turning a valid range such as 1-2 into "Not available".
        subsection = self.embedding_content_repo.hydrate_subsection_book_pages(lesson, subsection)
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
            preferred_language=language,
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
        # Teacher-facing page state must always use the printed/book label.
        # Physical PDF coordinates remain internal retrieval metadata only.
        session.temp_customize_from_page = subsection.printed_start_page
        session.temp_customize_to_page = subsection.printed_end_page
        session.temp_lesson_is_customized = False
        session.temp_topic = lesson.title
        session.temp_duration_minutes = requested_duration or result.duration_minutes
        session.temp_generated_lesson = result.lesson_text
        session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
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
        return self._generated_lesson_action_reply(result.lesson_text, language)

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
        session.temp_topic = None
        session.temp_content_document_id = None
        session.temp_content_chapter_id = None
        session.temp_content_subsection_id = None
        session.temp_teacher_schedule_id = None
        session.temp_teacher_schedule_day_id = None

        lessons = self._lesson_topic_list_for_session(session, teacher)
        if not lessons:
            self.session_repo.save(session)
            return self._reply(
                f"{self._text(language, 'lesson_topic_empty', school_name=school_name, grade=lesson_grade, subject=normalized_subject)}\n\n{self._new_lesson_subject_prompt(language)}",
                ConversationState.NEW_LESSON_SUBJECT,
            )

        session.current_state = ConversationState.NEW_LESSON_TOPIC.value
        self.session_repo.save(session)
        return self._lesson_topic_reply(lessons=lessons, language=language)

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

        lesson_match = None
        if session.temp_content_chapter_id:
            lesson_match = self.embedding_content_repo.get_lesson_by_chapter_id(session.temp_content_chapter_id)
        if not lesson_match and topic:
            lesson_match = self.embedding_content_repo.find_lesson_match(
                school_name=school_name,
                grade=lesson_grade,
                subject=lesson_subject,
                topic=topic,
            )
        if not lesson_match:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=topic), language)

        summary, provider_used = self.pdf_content_lesson_service.generate_section_summary(
            lesson=lesson_match,
            teacher=teacher,
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=duration,
            preferred_language=language,
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

        # Optional question-targeted teacher schedules take precedence only for
        # chapters where such rows exist. Every existing book/chapter without
        # schedule rows uses the original structural subsection/day behavior.
        schedules = self.embedding_content_repo.list_teacher_schedules_for_lesson(lesson_match)
        session.temp_teacher_schedule_id = None
        session.temp_teacher_schedule_day_id = None

        if schedules:
            if len(schedules) == 1:
                schedule = schedules[0]
                days = self.embedding_content_repo.list_teacher_schedule_days(schedule.id)
                if days:
                    session.temp_teacher_schedule_id = schedule.id
                    session.current_state = ConversationState.NEW_LESSON_DAY.value
                    self.session_repo.save(session)
                    log_event(
                        logger,
                        "lesson_teacher_schedule_selected_automatically",
                        teacher_id=teacher.id,
                        chapter_id=lesson_match.chapter_id,
                        teacher_schedule_id=schedule.id,
                        week_start_date=schedule.week_start_date,
                        exercise=schedule.exercise,
                        day_count=len(days),
                    )
                    return self._teacher_schedule_day_reply(
                        lesson=lesson_match,
                        schedule=schedule,
                        days=days,
                        summary=summary,
                        language=language,
                    )

            else:
                session.current_state = ConversationState.NEW_LESSON_SCHEDULE.value
                self.session_repo.save(session)
                log_event(
                    logger,
                    "lesson_teacher_schedule_choice_required",
                    teacher_id=teacher.id,
                    chapter_id=lesson_match.chapter_id,
                    schedule_count=len(schedules),
                )
                return self._lesson_schedule_reply(
                    lesson=lesson_match,
                    schedules=schedules,
                    summary=summary,
                    language=language,
                )

        subsections = self.embedding_content_repo.list_subsections_for_lesson(lesson_match)
        if not subsections:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=topic), language)

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

    def _handle_new_lesson_action_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)
        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)

        if choice in {"1", "use this lesson", "use lesson", "use_generated_lesson"}:
            session.current_state = ConversationState.NEW_LESSON_CONFIRM_SAVE.value
            self.session_repo.save(session)
            return self._save_menu_reply(session.temp_generated_lesson or "", language)

        if choice in {"2", "customize lesson", "customize", "customize_generated_lesson", "पाठ बदलें"}:
            lesson = self.embedding_content_repo.get_lesson_by_chapter_id(session.temp_content_chapter_id or "")
            if not lesson:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply(self._text(language, "lesson_no_match", topic=session.temp_topic or ""), language)
            pages = self.embedding_content_repo.list_pages_for_lesson(lesson)
            if not pages:
                return self._generated_lesson_action_reply(
                    session.temp_generated_lesson or "",
                    language,
                    prefix=self._text(language, "customize_pages_unavailable", item_type=self._toc_item_label(lesson, language)),
                )

            # Start the direct customization sequence. Do not show a second menu:
            # Customize Lesson -> From Book Page -> To Book Page -> regenerate lesson.
            session.temp_customize_from_page = None
            session.temp_customize_to_page = None
            session.current_state = ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE.value
            self.session_repo.save(session)
            return self._customize_from_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
            )

        if choice in {"3", "print lesson", "print_generated_lesson", "पाठ प्रिंट करें"}:
            return self._print_generated_lesson_reply(
                session=session,
                teacher=teacher,
                language=language,
            )

        return self._generated_lesson_action_reply(
            session.temp_generated_lesson or "",
            language,
            prefix=self._text(language, "lesson_ready_invalid"),
        )

    def _handle_new_lesson_customize_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
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
        pages = self.embedding_content_repo.list_pages_for_lesson(lesson)
        if not pages:
            session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._generated_lesson_action_reply(
                session.temp_generated_lesson or "",
                language,
                prefix=self._text(language, "customize_pages_unavailable", item_type=self._toc_item_label(lesson, language)),
            )

        chapter_range = self._chapter_page_range(lesson, pages)
        if choice in {"1", "from page", "customize_from_page"}:
            session.current_state = ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE.value
            self.session_repo.save(session)
            return self._reply(
                self._text(language, "customize_from_prompt", chapter_range=chapter_range, item_type=self._toc_item_label(lesson, language)),
                ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE,
            )

        if choice in {"2", "to page", "customize_to_page"}:
            session.current_state = ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
            self.session_repo.save(session)
            return self._reply(
                self._text(language, "customize_to_prompt", chapter_range=chapter_range, item_type=self._toc_item_label(lesson, language)),
                ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE,
            )

        if choice in {"4", "create/save updated lesson", "create/save", "customize_create_save"}:
            return self._generate_customized_lesson(
                session=session,
                teacher=teacher,
                lesson=lesson,
                pages=pages,
                language=language,
            )

        if choice in {"5", "back", "customize_back", "वापस"}:
            session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._generated_lesson_action_reply(session.temp_generated_lesson or "", language)

        return self._customize_lesson_reply(
            session=session,
            lesson=lesson,
            pages=pages,
            language=language,
            prefix=self._text(language, "customize_invalid"),
        )

    def _handle_new_lesson_customize_from_page(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        return self._store_custom_page_choice(
            session=session,
            whatsapp_number=whatsapp_number,
            text=text,
            is_from_page=True,
        )

    def _handle_new_lesson_customize_to_page(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        return self._store_custom_page_choice(
            session=session,
            whatsapp_number=whatsapp_number,
            text=text,
            is_from_page=False,
        )

    def _store_custom_page_choice(
        self,
        *,
        session,
        whatsapp_number: str,
        text: str,
        is_from_page: bool,
    ) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(self._text(language, "new_lesson_without_profile"), ConversationState.PROFILE_NAME)
        lesson = self.embedding_content_repo.get_lesson_by_chapter_id(session.temp_content_chapter_id or "")
        if not lesson:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply(self._text(language, "lesson_no_match", topic=session.temp_topic or ""), language)
        pages = self.embedding_content_repo.list_pages_for_lesson(lesson)
        if normalize_choice(text) in {"5", "back", "customize_back", "वापस"}:
            session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._generated_lesson_action_reply(session.temp_generated_lesson or "", language)
        if not pages:
            session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
            self.session_repo.save(session)
            return self._generated_lesson_action_reply(
                session.temp_generated_lesson or "",
                language,
                prefix=self._text(language, "customize_pages_unavailable", item_type=self._toc_item_label(lesson, language)),
            )

        selected_page = self.embedding_content_repo.resolve_page_choice(pages, text)
        if not selected_page:
            chapter_range = self._chapter_page_range(lesson, pages)
            prefix = self._text(language, "customize_page_invalid", chapter_range=chapter_range, item_type=self._toc_item_label(lesson, language))
            if is_from_page:
                return self._customize_from_page_prompt_reply(
                    session=session,
                    lesson=lesson,
                    pages=pages,
                    language=language,
                    prefix=prefix,
                )
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=prefix,
            )

        if is_from_page:
            session.temp_customize_from_page = selected_page.display_page
            session.temp_customize_to_page = None
            session.current_state = ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
            self.session_repo.save(session)
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
            )

        session.temp_customize_to_page = selected_page.display_page
        self.session_repo.save(session)
        return self._generate_customized_lesson(
            session=session,
            teacher=teacher,
            lesson=lesson,
            pages=pages,
            language=language,
        )

    def _generate_customized_lesson(
        self,
        *,
        session,
        teacher,
        lesson: EmbeddingLessonMatch,
        pages: list[EmbeddingPageExtraction],
        language: str,
    ) -> ConversationReply:
        from_page = self.embedding_content_repo.resolve_page_choice(pages, session.temp_customize_from_page)
        to_page = self.embedding_content_repo.resolve_page_choice(pages, session.temp_customize_to_page)
        chapter_range = self._chapter_page_range(lesson, pages)
        if not from_page:
            return self._customize_from_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=self._text(language, "customize_page_invalid", chapter_range=chapter_range, item_type=self._toc_item_label(lesson, language)),
            )
        if not to_page:
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=self._text(language, "customize_page_invalid", chapter_range=chapter_range, item_type=self._toc_item_label(lesson, language)),
            )

        page_indexes = {page.pdf_page_number: index for index, page in enumerate(pages)}
        start_index = page_indexes[from_page.pdf_page_number]
        end_index = page_indexes[to_page.pdf_page_number]
        if start_index > end_index:
            session.temp_customize_to_page = None
            self.session_repo.save(session)
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=self._text(
                    language,
                    "customize_range_invalid",
                    from_page=from_page.display_page,
                    to_page=to_page.display_page,
                ),
            )

        selected_pages = pages[start_index : end_index + 1]
        is_contiguous = all(
            current.pdf_page_number == previous.pdf_page_number + 1
            for previous, current in zip(selected_pages, selected_pages[1:])
        )
        if not is_contiguous:
            session.temp_customize_to_page = None
            self.session_repo.save(session)
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=self._text(
                    language,
                    "customize_range_invalid",
                    from_page=from_page.display_page,
                    to_page=to_page.display_page,
                ),
            )

        page_text_parts = [
            f"Book Page {page.display_page}\n{page.text.strip()}"
            for page in selected_pages
            if page.text and page.text.strip()
        ]
        if not page_text_parts:
            session.temp_customize_to_page = None
            self.session_repo.save(session)
            return self._customize_to_page_prompt_reply(
                session=session,
                lesson=lesson,
                pages=pages,
                language=language,
                prefix=self._text(language, "customize_text_unavailable"),
            )

        original_subsection = self.embedding_content_repo.get_subsection_by_id(session.temp_content_subsection_id or "")
        if not original_subsection:
            original_subsection = EmbeddingSubsection(
                id=session.temp_content_subsection_id or "customized-page-range",
                document_id=lesson.document_id,
                subsection_number=session.temp_lesson_subsection_number,
                subsection_title=session.temp_lesson_subsection_title,
                anchor_marker=session.temp_lesson_day_title,
                pdf_start_page=from_page.pdf_page_number,
                pdf_end_page=to_page.pdf_page_number,
                printed_start_page=from_page.display_page,
                printed_end_page=to_page.display_page,
                page_numbers=[],
                printed_page_numbers=[],
                includes=[],
                text="",
                text_length_chars=0,
                include_in_embeddings=True,
                embedding_readiness="ready",
                quality_flags=[],
            )

        printed_numbers = [
            int(page.printed_page_number)
            for page in selected_pages
            if (page.printed_page_number or "").strip().isdigit()
        ]
        schedule = (
            self.embedding_content_repo.get_teacher_schedule_by_id(session.temp_teacher_schedule_id or "")
            if session.temp_teacher_schedule_id
            else None
        )
        schedule_day = (
            self.embedding_content_repo.get_teacher_schedule_day_by_id(session.temp_teacher_schedule_day_id or "")
            if session.temp_teacher_schedule_day_id
            else None
        )
        customized_subsection = EmbeddingSubsection(
            id=original_subsection.id,
            document_id=lesson.document_id,
            subsection_number=original_subsection.subsection_number,
            subsection_title=original_subsection.subsection_title,
            anchor_marker=original_subsection.anchor_marker,
            pdf_start_page=from_page.pdf_page_number,
            pdf_end_page=to_page.pdf_page_number,
            printed_start_page=from_page.display_page,
            printed_end_page=to_page.display_page,
            page_numbers=[page.pdf_page_number for page in selected_pages],
            printed_page_numbers=printed_numbers,
            includes=original_subsection.includes,
            text="\n\n".join(page_text_parts),
            text_length_chars=sum(len(part) for part in page_text_parts),
            include_in_embeddings=True,
            embedding_readiness="ready",
            quality_flags=list(original_subsection.quality_flags or []),
            source_kind=("teacher_schedule_day" if schedule and schedule_day else None),
            schedule_week_start_date=(schedule.week_start_date if schedule else None),
            schedule_exercise=((schedule.exercise or schedule_day.exercise) if schedule and schedule_day else None),
            schedule_questions=(list(schedule_day.questions or []) if schedule_day else None),
            schedule_topic=(schedule_day.topic if schedule_day else None),
            schedule_activity=(schedule_day.activity if schedule_day else None),
        )

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject
        requested_duration = session.temp_duration_minutes or 0
        result = self.pdf_content_lesson_service.generate_day_lesson_plan(
            lesson=lesson,
            subsection=customized_subsection,
            day_number=session.temp_lesson_day_number or 1,
            teacher=teacher,
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=requested_duration,
            preferred_language=language,
        )

        session.temp_generated_lesson = result.lesson_text
        session.temp_duration_minutes = requested_duration or result.duration_minutes
        session.temp_lesson_book_pages = customized_subsection.display_pages
        session.temp_lesson_pdf_start_page = customized_subsection.pdf_start_page
        session.temp_lesson_pdf_end_page = customized_subsection.pdf_end_page
        session.temp_lesson_printed_start_page = customized_subsection.printed_start_page
        session.temp_lesson_printed_end_page = customized_subsection.printed_end_page
        session.temp_customize_from_page = from_page.display_page
        session.temp_customize_to_page = to_page.display_page
        session.temp_lesson_is_customized = True
        session.temp_lesson_name = self._ensure_customized_lesson_name(
            self._suggest_lesson_name(session.temp_topic, language)
        )
        session.current_state = ConversationState.NEW_LESSON_ACTION_MENU.value
        self.session_repo.save(session)

        log_event(
            logger,
            "lesson_customized_from_page_extractions",
            teacher_id=getattr(teacher, "id", None),
            chapter_id=lesson.chapter_id,
            subsection_id=session.temp_content_subsection_id,
            pdf_start_page=from_page.pdf_page_number,
            pdf_end_page=to_page.pdf_page_number,
            printed_start_page=from_page.display_page,
            printed_end_page=to_page.display_page,
            selected_page_count=len(selected_pages),
            provider_used=result.provider_used,
        )
        return self._generated_lesson_action_reply(
            result.lesson_text,
            language,
            prefix=self._text(language, "customized_lesson_prefix"),
        )

    def _handle_new_lesson_confirm_save(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        language = self._teacher_language(teacher, whatsapp_number)
        choice = normalize_choice(text)

        if choice in {"1", "yes", "save lesson", "save_lesson", "पाठ सेव करें"}:
            suggested_name = (session.temp_lesson_name or self._suggest_lesson_name(session.temp_topic, language)).strip()
            if session.temp_lesson_is_customized:
                suggested_name = self._ensure_customized_lesson_name(suggested_name)
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
        if session.temp_lesson_is_customized and lesson_name:
            lesson_name = self._ensure_customized_lesson_name(lesson_name)
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
            source_type = (
                "pdf_to_embeddings_page_range"
                if session.temp_lesson_is_customized
                else "pdf_to_embeddings_subsection"
            )
            source_reference = {
                **(lesson_payload.get("source_reference") or {}),
                "source_type": source_type,
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
                "is_customized": bool(session.temp_lesson_is_customized),
                "customized_page_range": {
                    "from_page": session.temp_customize_from_page,
                    "to_page": session.temp_customize_to_page,
                } if session.temp_lesson_is_customized else None,
            }
            lesson_payload["source_type"] = source_type
            lesson_payload["is_customized"] = bool(session.temp_lesson_is_customized)
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
