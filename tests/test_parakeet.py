import pytest

from app.core.parakeet import words_from_tokens, reconcile_chunks
from app.core.settings import WordTimestamp


def test_token_durations_assemble_words_and_preserve_repeated_speech():
    words = words_from_tokens(["▁go", "▁go", "▁test", "ing", "."],
                              [0., .3, .6, .8, .9], [.2, .2, .2, .1, .1], offset=28., duration=30.)
    assert [word.text for word in words] == ["go", "go", "testing."]
    assert words[0].start == 28.
    assert words[0].end == 28.08
    assert words[-1].end == pytest.approx(28.88)


def test_runtime_space_tokens_and_punctuation_are_preserved():
    words = words_from_tokens([" A", "sk", " not", ","], [0., .2, .4, .6], [.2] * 4)
    assert [word.text for word in words] == ["Ask", "not,"]


@pytest.mark.parametrize("times,lengths", [([0.], []), ([float("nan")], [.1]), ([-.1], [.1]), ([0.], [-.1])])
def test_invalid_timing_is_rejected(times, lengths):
    with pytest.raises(ValueError):
        words_from_tokens([" word"], times, lengths)


def test_default_model_routes_to_shared_parakeet_adapter(monkeypatch, tmp_path):
    from app.core import parakeet, transcriber
    from app.core.settings import MODEL_OPTIONS, DEFAULT_MODEL_LABEL
    calls = []
    monkeypatch.setattr(parakeet, "transcribe_parakeet", lambda *args: calls.append(args) or ["result"])
    assert transcriber.transcribe_audio(tmp_path / "audio.wav", MODEL_OPTIONS[DEFAULT_MODEL_LABEL], "NVIDIA GPU") == ["result"]
    assert len(calls) == 1


def test_overlap_reconciliation_preserves_repeated_words_at_different_times():
    previous = [WordTimestamp("go", 27., 27.2), WordTimestamp("go", 27.3, 27.5),
                WordTimestamp("again", 27.6, 28.), WordTimestamp("now", 28.1, 28.4)]
    incoming = [WordTimestamp("go", 27.3, 27.5), WordTimestamp("again", 27.6, 28.),
                WordTimestamp("now", 28.1, 28.4), WordTimestamp("go", 28.5, 28.7)]
    merged = reconcile_chunks(previous, incoming, 28.)
    assert [word.text for word in merged] == ["go", "go", "again", "now", "go"]
    assert [word.start for word in merged] == [27., 27.3, 27.6, 28.1, 28.5]


def test_uncertain_chunk_seam_fails_instead_of_silently_dropping_speech():
    with pytest.raises(ValueError, match="reconcile"):
        reconcile_chunks([WordTimestamp("different", 27.8, 28.3)], [WordTimestamp("reading", 27.9, 28.4)], 28.)


def test_invalid_gpu_timing_retries_complete_recording_on_cpu(tmp_path, monkeypatch):
    import io
    import json
    import os
    from app.core import parakeet
    python = tmp_path / ".venv-parakeet" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    model = tmp_path / "models" / parakeet.MODEL_NAME
    model.mkdir(parents=True)
    (model / "tokens.txt").touch()
    monkeypatch.setattr(parakeet, "project_root", lambda: tmp_path)
    monkeypatch.delenv("VCG_PARAKEET_MODEL", raising=False)
    calls = []
    class Process:
        def __init__(self, command, **_kwargs):
            provider = command[-1]
            calls.append(provider)
            events = [{"event": "device", "device": provider},
                      {"event": "chunk", "offset": 0., "core_start": 0., "core_end": 190.,
                       "duration": 190., "tokens": [" word"], "timestamps": [0.],
                       "durations": [-.1 if provider == "cuda" else 1.]},
                      {"event": "complete", "decode_seconds": 1.}]
            self.stdout = io.StringIO("\n".join(json.dumps(event) for event in events))
        def wait(self): return 0
        def kill(self): pass
    monkeypatch.setattr(parakeet.subprocess, "Popen", Process)
    words = parakeet.transcribe_parakeet(tmp_path / "audio.wav", "NVIDIA GPU")
    assert calls == ["cuda", "cpu"]
    assert [word.text for word in words] == ["word"]
    assert words.metadata["device"] == "cpu"
    assert "token timing" in words.metadata["fallback_reason"]


def test_estimates_ignore_decoder_silence_advances_and_reject_cotimed_intervals():
    words = words_from_tokens([" first", " next"], [0., 10.], [9.9, .1], duration=11.)
    assert words[0].end == .08
    with pytest.raises(ValueError, match="positive interval"):
        words_from_tokens([" to", " go"], [10., 10.], [0., .1], duration=11.)


def test_delayed_punctuation_preserves_text_without_extending_through_silence():
    words = words_from_tokens([" imag", "es", ".", " Next"], [1., 1.3, 10., 11.], [.3, .3, .1, .2])
    assert words[0].text == "images."
    assert words[0].end == pytest.approx(1.38)


def test_profile_verifier_uses_only_parseable_executed_events(tmp_path):
    from app.core.parakeet_profiling import executed_providers
    damaged = tmp_path / "damaged.json"
    damaged.write_text('[{"args":{"provider":"CUDAExecutionProvider"}}]truncated')
    assert executed_providers([damaged]) == set()
    valid = tmp_path / "valid.json"
    valid.write_text('[{"args":{"provider":"CUDAExecutionProvider"}},{"args":{"provider":"CPUExecutionProvider"}}]')
    assert executed_providers([damaged, valid]) == {"CUDAExecutionProvider", "CPUExecutionProvider"}
