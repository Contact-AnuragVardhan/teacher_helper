from app.utils.lesson_title_localization import localize_lesson_display_title


def test_devanagari_titles_convert_to_hinglish_even_without_generated_date_suffix():
    assert localize_lesson_display_title("झाँसी की रानी-1", None, "English") == "JhansiKiRani-1"


def test_devanagari_titles_convert_to_hinglish_with_generated_date_variants():
    assert (
        localize_lesson_display_title("झाँसीकीरानी_28_Apr_2026-", None, "English")
        == "JhansiKiRani_28_Apr_2026-"
    )
    assert (
        localize_lesson_display_title("झाँसीकीरानी_28_April_2026", None, "Hinglish")
        == "JhansiKiRani_28_April_2026"
    )


def test_roman_titles_convert_to_devanagari_and_preserve_date_suffix():
    assert (
        localize_lesson_display_title("JhansiKiRani_28_Apr_2026", None, "Hindi")
        == "झाँसीकीरानी_28_Apr_2026"
    )


def test_shared_prefix_is_preserved():
    assert (
        localize_lesson_display_title("* झाँसीकीरानी_28_April_2026", None, "English")
        == "* JhansiKiRani_28_April_2026"
    )
