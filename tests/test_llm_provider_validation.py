from app.services.lesson_generation_provider import PromptBundle
from app.services.llm_provider_openai import OpenAILessonGenerationProvider


HINDI_LESSON_WITH_SOURCE = """पाठ योजना
टॉपिक: झाँसी की रानी
ग्रेड/कक्षा: 8
विषय: सामाजिक विज्ञान
अवधि: 45 मिनट

पाठ शीर्षक
- 1857 के विद्रोह में रानी लक्ष्मीबाई की भूमिका

उद्देश्य
- रानी लक्ष्मीबाई के जीवन की मुख्य घटनाएँ बताना
- 1857 के विद्रोह में झाँसी के महत्व को समझना
- साहस, नेतृत्व और देशभक्ति के उदाहरण पहचानना

1. शुरुआत (5 min)
- प्रश्न: रानी लक्ष्मीबाई को वीरांगना क्यों कहा जाता है?
- शिक्षक गतिविधि: झाँसी, ग्वालियर और 1857 को बोर्ड पर जोड़कर दिखाना
- जोड़ी चर्चा: यदि आपका राज्य संकट में हो तो आप क्या करेंगे?

2. अवधारणा शिक्षण (13 min)
- मणिकर्णिका से रानी लक्ष्मीबाई तक: बचपन, विवाह, झाँसी की रानी बनना
- दत्तक पुत्र, राज्य हड़प नीति और झाँसी पर अंग्रेज़ी दावा
- 1857 का विद्रोह, झाँसी की रक्षा, कालपी और ग्वालियर की घटनाएँ

3. निर्देशित अभ्यास (9 min)
- गतिविधि: घटनाओं को सही क्रम में लगाओ
- विद्यार्थी कार्य: विवाह, दत्तक ग्रहण, 1857 विद्रोह, ग्वालियर को क्रम में लिखना
- शिक्षक जाँच: झाँसी संघर्ष का मुख्य कारण क्या था?

4. अवधारणा सुदृढ़ीकरण (6 min)
- रानी लक्ष्मीबाई: साहस, नेतृत्व, त्वरित निर्णय
- झाँसी का संघर्ष: व्यक्तिगत नहीं, राजनीतिक और राष्ट्रीय महत्व

5. स्वतंत्र अभ्यास (5 min)
- दो वाक्यों में लिखो: रानी लक्ष्मीबाई का सबसे बड़ा गुण
- उत्तर संकेत: साहस, नेतृत्व, मातृभूमि की रक्षा

6. मूल्यांकन / जाँच (4 min)
- रानी लक्ष्मीबाई का बचपन का नाम क्या था?
- झाँसी पर अंग्रेज़ों ने दावा किस नीति से किया?
- 1857 के विद्रोह में झाँसी क्यों महत्वपूर्ण था?

7. समापन (3 min)
- समापन: रानी लक्ष्मीबाई 1857 के विद्रोह की प्रमुख वीरांगना थीं
- एग्ज़िट टिकट: एक कारण लिखो कि आज भी लोग उन्हें क्यों याद करते हैं

शिक्षण सुझाव
- बोर्ड पर समयरेखा बनाकर पढ़ाएँ
- स्थानों को मानचित्र पर दिखाएँ

स्रोत:
NCERT
Book: हमारे अतीत-III
Chapter: जब जनता बगावत करती है 1857 और उसके बाद
"""


def _provider() -> OpenAILessonGenerationProvider:
    return object.__new__(OpenAILessonGenerationProvider)


def test_hindi_lesson_with_llm_ncert_source_does_not_require_learn_more():
    provider = _provider()
    prompt = PromptBundle(
        system_prompt="",
        user_prompt="",
        metadata={"has_ncert_match": False, "preferred_language": "Hindi"},
    )

    assert provider._has_ncert_source_block(HINDI_LESSON_WITH_SOURCE)
    assert provider._response_structure_failures(HINDI_LESSON_WITH_SOURCE, prompt) == []


def test_learn_more_required_only_when_no_app_match_and_no_llm_source():
    provider = _provider()
    prompt = PromptBundle(system_prompt="", user_prompt="", metadata={"has_ncert_match": False})

    text_without_source_or_learn_more = HINDI_LESSON_WITH_SOURCE.replace(
        "\nस्रोत:\nNCERT\nBook: हमारे अतीत-III\nChapter: जब जनता बगावत करती है 1857 और उसके बाद\n",
        "\n",
    )

    assert "learn_more_requirement_failed" in provider._response_structure_failures(
        text_without_source_or_learn_more,
        prompt,
    )


def test_app_ncert_match_alone_is_not_enough_because_llm_must_return_source_or_learn_more():
    provider = _provider()
    prompt = PromptBundle(system_prompt="", user_prompt="", metadata={"has_ncert_match": True})

    text_without_source_or_learn_more = HINDI_LESSON_WITH_SOURCE.replace(
        "\nस्रोत:\nNCERT\nBook: हमारे अतीत-III\nChapter: जब जनता बगावत करती है 1857 और उसके बाद\n",
        "\n",
    )

    assert "learn_more_requirement_failed" in provider._response_structure_failures(
        text_without_source_or_learn_more,
        prompt,
    )


def test_revision_instruction_requires_llm_source_instead_of_app_source_append():
    provider = _provider()

    instruction = provider._revision_source_or_learn_more_instruction(
        has_app_ncert_match=True,
        has_llm_source_block=False,
    )

    assert "app will not add Source separately" in instruction
    assert "Do not add Source because the app adds it separately" not in instruction
