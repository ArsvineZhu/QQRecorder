from plugins.grok.vision.video_schemas import normalize_video_analysis


def test_normalize_video_analysis_accepts_structured_time_range():
    analysis = normalize_video_analysis(
        {
            "media_type": "video",
            "video_type": "screen_recording",
            "key_events": [
                {
                    "time_range": {
                        "start_time": "00:01:00",
                        "end_time": "00:05:00",
                        "approximate": True,
                    },
                    "event": "滚动查看聊天记录",
                }
            ],
            "visible_text": [],
            "audio_or_speech_summary": "",
            "semantic_meaning": "",
            "contextual_meaning": "",
            "affective_reading": {"tone": [], "evidence": ""},
            "uncertainty": {
                "ambiguous_points": [],
                "possible_alternative_meanings": [],
            },
            "safety_and_privacy": {
                "contains_real_person_face": False,
                "contains_personal_info": False,
                "contains_qr_or_barcode": False,
                "contains_sensitive_document": False,
            },
            "confidence": 0.7,
        }
    )

    assert len(analysis.key_events) == 1
    assert analysis.key_events[0].time_range == "00:01:00-00:05:00"
