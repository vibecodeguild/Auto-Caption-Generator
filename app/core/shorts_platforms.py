"""Dated upload guidance, separate from editorial length and performance."""
from __future__ import annotations

CHECKED_ON = "2026-10-13"
PROFILES = {
    "YouTube": {"minSeconds": 0, "maxSeconds": 180,
                "note": "Shorts duration and vertical format only; upload eligibility has additional checks.",
                "url": "https://support.google.com/youtube/answer/15424877?hl=en"},
    "LinkedIn": {"minSeconds": 3, "maxSeconds": 900,
                 "note": "Member video upload from desktop. Pages and other upload paths may differ.",
                 "url": "https://www.linkedin.com/help/linkedin/answer/a548372"},
    "Facebook": {"note": "Meta announced unrestricted Reels length, but legacy upload guidance differs. Check your account's upload flow.",
                 "url": "https://about.fb.com/news/2025/06/making-it-easier-create-videos-facebook/"},
    "Instagram": {"note": "Check the current Reels upload and recommendation limits in your account; no unverified duration cutoff is applied.",
                  "url": "https://www.facebook.com/help/instagram/225190788256708"},
    "TikTok": {"note": "Duration limits depend on the upload flow. Check your account before posting.",
               "url": "https://support.tiktok.com/en/using-tiktok/creating-videos/camera-tools"},
    "Threads": {"note": "Meta's published introduction lists five-minute videos and 500-character posts; confirm current account limits before posting.",
                "referenceMaxSeconds": 300, "referenceMaxCharacters": 500,
                "url": "https://about.fb.com/news/2023/07/introducing-threads-new-app-text-sharing/"},
}


def guidance(duration: float, fps: float, posting: dict) -> dict:
    result = {}
    for platform, profile in PROFILES.items():
        issues = []
        if "maxSeconds" in profile and duration > profile["maxSeconds"]:
            issues.append(f"Duration exceeds {profile['maxSeconds']} seconds for this upload profile.")
        if duration < profile.get("minSeconds", 0):
            issues.append(f"Duration is below {profile['minSeconds']} seconds for this upload profile.")
        if platform == "LinkedIn" and not 10 <= fps <= 60:
            issues.append("LinkedIn's member upload guidance specifies 10–60 fps.")
        if platform == "Threads":
            if duration > profile["referenceMaxSeconds"]:
                issues.append("Longer than the five-minute duration in Meta's published reference.")
            if len((posting.get(platform) or {}).get("text", "")) > profile["referenceMaxCharacters"]:
                issues.append("Post text exceeds the 500-character ordinary-post reference.")
        result[platform] = {"status": "needs adjustment" if issues else "duration checked" if "maxSeconds" in profile else "check upload limits",
                            "issues": issues, "note": profile["note"], "url": profile["url"], "checkedOn": CHECKED_ON}
    return result
