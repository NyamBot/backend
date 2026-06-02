from app.schemas import ClipIdea, ScriptPack
from app.services.hf_generation import hf_generation


def generate_clip_ideas(source_id: str, title: str, context: list[str], platform: str) -> list[ClipIdea]:
    joined = " ".join(context)
    seed = joined[:180] if joined else title
    return [
        ClipIdea(
            id=f"{source_id}-idea-1",
            title=f"{title}: the strongest 30-second hook",
            hook="Most people miss this part, but it changes the whole story.",
            summary=seed,
            platform=platform,
            duration_seconds=35,
            hook_score=88,
            source_moments=context[:2],
        ),
        ClipIdea(
            id=f"{source_id}-idea-2",
            title=f"{title}: quick lesson format",
            hook="Here is the simplest way to understand this in under a minute.",
            summary="Turn the core explanation into a fast educational short.",
            platform=platform,
            duration_seconds=45,
            hook_score=81,
            source_moments=context[1:3] or context[:1],
        ),
        ClipIdea(
            id=f"{source_id}-idea-3",
            title=f"{title}: mistake and fix",
            hook="If you are doing this, you are making the process harder.",
            summary="Frame the source as a common mistake followed by a practical fix.",
            platform=platform,
            duration_seconds=40,
            hook_score=84,
            source_moments=context[2:4] or context[:1],
        ),
    ]


def generate_script_pack(idea: ClipIdea) -> ScriptPack:
    return ScriptPack(
        title=idea.title,
        hook=idea.hook,
        scene_plan=[
            "0-3s: Open with the hook as large on-screen text.",
            "3-12s: Show the core problem using a fast example.",
            "12-28s: Explain the useful insight in two clear beats.",
            "28-35s: End with one practical takeaway and CTA.",
        ],
        captions=[
            idea.hook,
            "Here is why it matters.",
            "The useful part is simpler than it looks.",
            "Save this before your next edit.",
        ],
        b_roll=[
            "Close-up of editing timeline or notes.",
            "Screen capture of the key moment being highlighted.",
            "Fast zoom on the takeaway sentence.",
        ],
        audio_direction=[
            "Mood: energetic, clean, modern.",
            "BPM: 120-135.",
            "SFX: impact hit at 0s, whoosh at 3s, riser before CTA.",
            "Use only royalty-free or properly licensed tracks.",
        ],
        hashtags=["#shorts", "#contentcreator", "#aitools", "#videoediting"],
        license_checklist=[
            "Do not use copyrighted songs without platform-safe licensing.",
            "Verify commercial-use rights for any music or sound effect.",
            "Check whether attribution is required.",
            "Avoid claiming any generated or suggested audio is copyright-free.",
        ],
    )


def answer_agent_question(message: str, context: list[str]) -> str:
    context_preview = " ".join(context)[:500]
    hf_answer = hf_generation.generate(
        "You are ClipForge AI, a short-form production assistant. "
        "Answer using only the transcript context. "
        f"Context:\n{context_preview}\n\nUser question: {message}"
    )
    if hf_answer:
        return hf_answer.strip()

    return (
        "Based on the stored transcript context, I would turn this into a short-form "
        "piece with a strong first-three-second hook, a single clear takeaway, and "
        f"a caption-first structure. Relevant context: {context_preview}"
    )
