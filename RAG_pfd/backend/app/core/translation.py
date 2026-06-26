import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def translate_question(
    question: str,
    from_lang: str,
    to_lang: str,
    openai_key: str,
) -> str:
    """Translate *question* using gpt-4o-mini.

    Returns the translated text, or the original question if the call fails.
    """
    try:
        client = AsyncOpenAI(api_key=openai_key, timeout=10.0)
        system = (
            f"Translate the following text from {from_lang} to {to_lang}. "
            "Return ONLY the translation, nothing else."
        )
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            max_tokens=500,
            temperature=0,
        )
        translated = resp.choices[0].message.content.strip()
        logger.info(
            "action=translate | from=%s | to=%s | original=%r | translated=%r",
            from_lang,
            to_lang,
            question[:80],
            translated[:80],
        )
        return translated
    except Exception as exc:
        logger.warning(
            "action=translate_failed | from=%s | to=%s | error=%s | returning_original",
            from_lang,
            to_lang,
            exc,
        )
        return question
