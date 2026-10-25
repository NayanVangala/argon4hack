"""Synthetic tests for autodetect.py. No real audio, no network.

Run as: python3 test_autodetect.py
Uses stdlib unittest only. Import works whether run from this
directory or from anywhere (sys.path fallback for the sibling module).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autodetect import detect, words_from_segments


def make_words(tokens, start=1.0, step=0.35, dur=0.25):
    """One word dict per token, evenly spaced, no turn gaps."""
    words = []
    t = start
    for token in tokens:
        words.append({"word": token, "start": t, "end": t + dur})
        t += step
    return words


def make_phrases(phrases):
    """phrases: list of (text, start_s). >2s gaps between phrases.

    Returns (words, transcript) with real '?' punctuation preserved
    in the transcript (callers pass the punctuated text explicitly).
    """
    words = []
    for text, start in phrases:
        t = start
        for token in text.replace("?", "").replace(",", "").split():
            words.append({"word": token, "start": t, "end": t + 0.25})
            t += 0.3
    return words


MONOLOGUE_TEXT = (
    "I spent the morning working on the quarterly report and then I "
    "walked through the whole draft again to check every number "
    "against the source spreadsheet before sending it to the team "
    "for review this afternoon."
)


class TestRoutingTable(unittest.TestCase):
    def test_every_label_maps_to_expected_route(self):
        # Exhaustive routing check: build one case per label and
        # assert the fixed table from the contract.
        cases = [
            ("silent", detect("", [], 30.0), "mark_and_skip"),
            ("ambient", detect("yeah uh noise", [
                {"word": "yeah", "start": 5.0, "end": 5.3},
                {"word": "uh", "start": 5.4, "end": 5.6},
                {"word": "noise", "start": 20.0, "end": 20.2},
            ], 30.0), "mark_and_skip"),
            ("monologue", detect(MONOLOGUE_TEXT + ".",
                                 make_words(MONOLOGUE_TEXT.split()),
                                 30.0), "analyze"),
        ]
        dialog_words = make_phrases([
            ("Hey are you coming tomorrow", 1.0),
            ("Yeah I will be there", 6.0),
            ("What time should we meet", 11.0),
            ("Let us say nine in the morning", 16.0),
        ])
        dialog_text = ("Hey, are you coming tomorrow? Yeah, I will be "
                       "there. What time should we meet? Let us say "
                       "nine in the morning.")
        cases.append(("conversation",
                      detect(dialog_text, dialog_words, 30.0), "analyze"))
        for label, result, route in cases:
            with self.subTest(label=label):
                self.assertEqual(result["label"], label)
                self.assertEqual(result["route"], route)

    def test_return_shape_and_confidence_range(self):
        result = detect(MONOLOGUE_TEXT + ".",
                        make_words(MONOLOGUE_TEXT.split()), 30.0)
        self.assertEqual(set(result.keys()),
                         {"label", "confidence", "reasons", "route",
                          "speech_seconds", "word_count", "turn_count"})
        self.assertTrue(0.0 <= result["confidence"] <= 1.0)
        self.assertIsInstance(result["reasons"], list)
        self.assertTrue(all(isinstance(r, str) and r
                            for r in result["reasons"]))
        self.assertIsInstance(result["word_count"], int)
        self.assertIsInstance(result["turn_count"], int)
        self.assertIsInstance(result["speech_seconds"], float)


class TestSilent(unittest.TestCase):
    def test_no_words_empty_transcript(self):
        result = detect("", [], 30.0)
        self.assertEqual(result["label"], "silent")
        self.assertEqual(result["route"], "mark_and_skip")
        self.assertEqual(result["word_count"], 0)
        self.assertEqual(result["speech_seconds"], 0.0)

    def test_whitespace_only_transcript_is_silent(self):
        result = detect("   \n ", [], 30.0)
        self.assertEqual(result["label"], "silent")
        self.assertEqual(result["route"], "mark_and_skip")


class TestAmbient(unittest.TestCase):
    def test_few_words_short_duration(self):
        words = [
            {"word": "yeah", "start": 5.0, "end": 5.3},
            {"word": "uh", "start": 5.4, "end": 5.6},
            {"word": "noise", "start": 20.0, "end": 20.2},
        ]
        result = detect("yeah uh noise", words, 30.0)
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_few_words_no_timestamps(self):
        # Mock-shape words (None timestamps): count alone decides.
        words = [{"word": w, "start": None, "end": None}
                 for w in ["thank", "you", "music"]]
        result = detect("thank you music", words, 30.0)
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_single_word_is_ambient_not_silent(self):
        result = detect("hello", [
            {"word": "hello", "start": 3.0, "end": 3.4}], 30.0)
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_short_but_clear_utterance_is_not_skipped(self):
        # Safety leg of the AND rule: 7 words spoken over ~4s is a
        # possible promise ("I promise to send it tomorrow"), so it
        # must reach analyze even though the count is under 10.
        words = make_words("I promise to send it tomorrow morning".split(),
                           step=0.6, dur=0.5)
        result = detect("I promise to send it tomorrow morning.",
                        words, 30.0)
        self.assertEqual(result["route"], "analyze")


class TestMonologue(unittest.TestCase):
    def test_sustained_speech_one_flow(self):
        result = detect(MONOLOGUE_TEXT + ".",
                        make_words(MONOLOGUE_TEXT.split()), 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertEqual(result["route"], "analyze")
        self.assertGreater(result["word_count"], 10)
        self.assertGreater(result["speech_seconds"], 3.0)

    def test_long_sentences_without_question_stay_monologue(self):
        text = ("The plan for today is to finish the report first and "
                "then review the budget numbers carefully before the "
                "meeting starts in the afternoon with the whole team.")
        result = detect(text, make_words(text.split()), 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertEqual(result["route"], "analyze")


class TestConversation(unittest.TestCase):
    def test_alternating_short_utterances_plus_qa(self):
        words = make_phrases([
            ("Hey are you coming tomorrow", 1.0),
            ("Yeah I will be there", 6.0),
            ("What time should we meet", 11.0),
            ("Let us say nine in the morning", 16.0),
        ])
        text = ("Hey, are you coming tomorrow? Yeah, I will be "
                "there. What time should we meet? Let us say nine "
                "in the morning.")
        result = detect(text, words, 30.0)
        self.assertEqual(result["label"], "conversation")
        self.assertEqual(result["route"], "analyze")
        self.assertGreaterEqual(result["turn_count"], 3)

    def test_qa_pair_alone_signals_conversation(self):
        # One question plus an answer, even without gap turns
        # (timestamps all contiguous), counts as dialogue.
        text = ("Did you finish the slides? Yes, I sent them last "
                "night after fixing the charts and the title slide.")
        result = detect(text, make_words(text.split()), 30.0)
        self.assertEqual(result["label"], "conversation")
        self.assertEqual(result["route"], "analyze")

    def test_gap_turns_without_question_signal_conversation(self):
        # Three short turns separated by >2s gaps, no question mark.
        words = make_phrases([
            ("Hey good morning", 1.0),
            ("Morning ready when you are", 6.0),
            ("Great let us start", 11.0),
            ("Sounds good to me", 16.0),
        ])
        text = ("Hey, good morning. Morning, ready when you are. "
                "Great, let us start. Sounds good to me.")
        result = detect(text, words, 30.0)
        self.assertEqual(result["label"], "conversation")
        self.assertEqual(result["route"], "analyze")


class TestEdgeCases(unittest.TestCase):
    def test_malformed_input_defaults_to_analyze(self):
        for transcript, words, dur in [
            (None, "not-a-list", float("nan")),
            (123, None, -5),
            (None, [{"word": "x", "start": 1.0, "end": 1.3}], 30.0),
            ("", [None, 123], 30.0),
        ]:
            with self.subTest(transcript=transcript, dur=dur):
                result = detect(transcript, words, dur)
                self.assertEqual(result["route"], "analyze")
                self.assertIn(result["label"],
                              ("monologue", "conversation"))

    def test_empty_transcript_with_words_present(self):
        # Words carry the decision; transcript rebuilt from words.
        result = detect("", make_words(MONOLOGUE_TEXT.split()), 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertEqual(result["route"], "analyze")
        self.assertGreater(result["word_count"], 10)

    def test_words_empty_with_transcript_present(self):
        # Transcript carries the decision; no timestamps available.
        result = detect(MONOLOGUE_TEXT + ".", [], 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertEqual(result["route"], "analyze")
        self.assertGreater(result["word_count"], 10)
        self.assertEqual(result["speech_seconds"], 0.0)

    def test_empty_transcript_with_few_words_is_ambient(self):
        result = detect("", [
            {"word": "hey", "start": 2.0, "end": 2.3},
            {"word": "yeah", "start": 2.5, "end": 2.8}], 30.0)
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_unknown_duration_alone_does_not_force_analyze(self):
        # A missing duration falls back to 30s; it is not structural
        # malformation, so a genuinely low-word chunk still skips.
        result = detect("yeah uh", [
            {"word": "yeah", "start": 5.0, "end": 5.3},
            {"word": "uh", "start": 5.4, "end": 5.6}], None)
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_missing_timestamps_never_crash_and_never_skip_speech(self):
        words = [{"word": w, "start": None, "end": None}
                 for w in MONOLOGUE_TEXT.split()]
        result = detect(MONOLOGUE_TEXT + ".", words, 30.0)
        self.assertEqual(result["route"], "analyze")

    def test_negative_and_reversed_timestamps_ignored(self):
        words = make_words(MONOLOGUE_TEXT.split())
        words[0] = {"word": words[0]["word"], "start": -3.0,
                    "end": 1.0}
        words[1] = {"word": words[1]["word"], "start": 5.0,
                    "end": 4.0}
        result = detect(MONOLOGUE_TEXT + ".", words, 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertEqual(result["route"], "analyze")


class TestRealWhisperShape(unittest.TestCase):
    def test_start_ts_end_ts_spelling(self):
        words = [{"word": w["word"], "start_ts": w["start"],
                  "end_ts": w["end"]}
                 for w in make_words(MONOLOGUE_TEXT.split())]
        result = detect(MONOLOGUE_TEXT + ".", words, 30.0)
        self.assertEqual(result["label"], "monologue")
        self.assertGreater(result["speech_seconds"], 3.0)

    def test_words_from_segments_flattens_real_shape(self):
        ts_words = [{"word": w["word"], "start_ts": w["start"],
                     "end_ts": w["end"]}
                    for w in make_words(MONOLOGUE_TEXT.split())]
        segments = [{
            "speaker_label": "Unknown",
            "text": MONOLOGUE_TEXT,
            "start_ts": 1.0,
            "end_ts": 20.0,
            "word_timestamps": ts_words,
        }]
        flat = words_from_segments(segments)
        self.assertEqual(len(flat), len(MONOLOGUE_TEXT.split()))
        self.assertEqual(flat[0]["word"], "I")
        self.assertIn("start", flat[0])
        result = detect(MONOLOGUE_TEXT + ".", flat, 30.0)
        self.assertEqual(result["label"], "monologue")

    def test_words_from_segments_handles_mock_none_timestamps(self):
        segments = [{
            "speaker_label": "Unknown",
            "text": "Live segment (mock transcript).",
            "start_ts": None,
            "end_ts": None,
            "word_timestamps": [
                {"word": w, "start_ts": None, "end_ts": None}
                for w in "Live segment (mock transcript).".split()
            ],
        }]
        flat = words_from_segments(segments)
        self.assertEqual(len(flat), 4)
        result = detect("Live segment (mock transcript).", flat, 30.0)
        # 4 words, no timing: ambient by the count rule (mock only).
        self.assertEqual(result["label"], "ambient")
        self.assertEqual(result["route"], "mark_and_skip")

    def test_words_from_segments_bad_input(self):
        self.assertEqual(words_from_segments(None), [])
        self.assertEqual(words_from_segments("nope"), [])
        self.assertEqual(words_from_segments([None, {"nope": 1}]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
