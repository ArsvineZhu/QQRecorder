import pytest
from plugins.qq_recorder.sticker_detector import (
    detect_by_text,
    detect_by_metadata,
    detect_by_heuristics,
    combined_detection,
)


# ------------------------------
# detect_by_text tests
# ------------------------------
def test_detect_by_text_has_sticker_keyword():
    """Test detect_by_text: CQ code contains sub_type=1 (sticker indicator)"""
    raw = '[CQ:image,summary=&#91;&#211;&#197;&#187;&#173;&#177;&#237;&#199;&#233;&#93;,file=abc.png,sub_type=1,url=https://example.com/img,file_size=23850]'
    is_sticker, confidence = detect_by_text(raw)
    assert is_sticker is True
    assert confidence > 0.5


def test_detect_by_text_no_sticker_keyword():
    """Test detect_by_text: CQ code has sub_type=0 (regular image)"""
    raw = '[CQ:image,file=photo.jpg,sub_type=0,url=https://example.com/photo,file_size=125070]'
    is_sticker, confidence = detect_by_text(raw)
    assert is_sticker is False
    assert confidence < 0.5


# ------------------------------
# detect_by_metadata tests
# ------------------------------
def test_detect_by_metadata_is_sticker():
    """Test detect_by_metadata: segment has sub_type=1 (animated expression)"""
    segment_data = {
        "file": "abc.png",
        "url": "https://example.com/sticker.png",
        "file_size": 23850,
        "sub_type": 1,
        "summary": "[动画表情]",
    }
    is_sticker, confidence = detect_by_metadata(segment_data)
    assert is_sticker is True
    assert confidence > 0.8


def test_detect_by_metadata_not_sticker():
    """Test detect_by_metadata: segment has sub_type=0 (regular photo)"""
    segment_data = {
        "file": "photo.jpg",
        "url": "https://example.com/photo.jpg",
        "file_size": 125070,
        "sub_type": 0,
    }
    is_sticker, confidence = detect_by_metadata(segment_data)
    assert is_sticker is False
    assert confidence < 0.3


# ------------------------------
# detect_by_heuristics tests
# ------------------------------
def test_detect_by_heuristics_is_sticker_small_size_gif():
    """Test detect_by_heuristics: small GIF is likely a sticker"""
    is_sticker, confidence = detect_by_heuristics(
        local_path="data/images/2026/05/11/abc123.gif",
        file_size=24500,
        file_ext=".gif",
    )
    assert is_sticker is True
    assert confidence > 0.6


def test_detect_by_heuristics_not_sticker_large_size_jpg():
    """Test detect_by_heuristics: large JPG is likely a photo not a sticker"""
    is_sticker, confidence = detect_by_heuristics(
        local_path="data/images/2026/05/11/def456.jpg",
        file_size=3200000,
        file_ext=".jpg",
    )
    assert is_sticker is False
    assert confidence < 0.4


# ------------------------------
# combined_detection tests
# ------------------------------
def test_combined_detection_all_agree_positive():
    """Test combined_detection: all three methods detect sticker"""
    raw_message = '[CQ:image,summary=&#91;&#211;&#197;&#187;&#173;&#177;&#237;&#199;&#233;&#93;,file=abc.gif,sub_type=1,url=https://example.com/img,file_size=24500]'
    segment_data = {
        "file": "abc.gif",
        "url": "https://example.com/img",
        "file_size": 24500,
        "sub_type": 1,
        "summary": "[动画表情]",
    }
    is_sticker, confidence = combined_detection(
        raw_message=raw_message,
        segment_data=segment_data,
        local_path="test.gif",
        file_size=24500,
        file_ext=".gif",
    )
    assert is_sticker is True
    assert confidence > 0.8


def test_combined_detection_all_agree_negative():
    """Test combined_detection: all three methods detect non-sticker"""
    raw_message = '[CQ:image,file=photo.jpg,sub_type=0,url=https://example.com/photo,file_size=2500000]'
    segment_data = {
        "file": "photo.jpg",
        "url": "https://example.com/photo",
        "file_size": 2500000,
        "sub_type": 0,
    }
    is_sticker, confidence = combined_detection(
        raw_message=raw_message,
        segment_data=segment_data,
        local_path="photo.jpg",
        file_size=2500000,
        file_ext=".jpg",
    )
    assert is_sticker is False
    assert confidence < 0.3
