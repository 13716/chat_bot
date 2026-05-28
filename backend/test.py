"""
Chạy từ thư mục backend:
    python check_keys.py
"""
import asyncio
import httpx
from dotenv import load_dotenv
import os

load_dotenv(override=True)  # Load .env file, override nếu đã có biến môi trường

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def mask(key: str) -> str:
    return f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "(empty)"


async def check_groq():
    if not GROQ_KEY:
        return "SKIP", "No key"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
            )
        if r.status_code == 200:
            return "OK", r.json()["choices"][0]["message"]["content"]
        return "FAIL", r.json()
    except Exception as e:
        return "ERROR", str(e)


async def check_gemini():
    if not GEMINI_KEY:
        return "SKIP", "No key"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": "hi"}]}]},
            )
        if r.status_code == 200:
            return "OK", r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return "FAIL", r.json()
    except Exception as e:
        return "ERROR", str(e)


async def check_openai():
    if not OPENAI_KEY:
        return "SKIP", "No key"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
            )
        if r.status_code == 200:
            return "OK", r.json()["choices"][0]["message"]["content"]
        return "FAIL", r.json()
    except Exception as e:
        return "ERROR", str(e)


async def check_anthropic():
    if not ANTHROPIC_KEY:
        return "SKIP", "No key"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                },
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
            )
        if r.status_code == 200:
            return "OK", r.json()["content"][0]["text"]
        return "FAIL", r.json()
    except Exception as e:
        return "ERROR", str(e)


async def main():
    print("=" * 50)
    print("API KEY CHECKER")
    print("=" * 50)

    checks = [
        ("GROQ", GROQ_KEY, GROQ_MODEL, check_groq),
        ("GEMINI", GEMINI_KEY, "gemini-1.5-flash", check_gemini),
        ("OPENAI", OPENAI_KEY, "gpt-4o-mini", check_openai),
        ("ANTHROPIC", ANTHROPIC_KEY, "claude-haiku-4-5-20251001", check_anthropic),
    ]

    for name, key, model, fn in checks:
        print(f"\n[{name}]")
        print(f"  Key   : {mask(key)}")
        print(f"  Model : {model}")
        status, detail = await fn()
        emoji = "✅" if status == "OK" else "⏭️" if status == "SKIP" else "❌"
        print(f"  Status: {emoji} {status}")
        if status != "OK":
            print(f"  Detail: {detail}")
        else:
            print(f"  Reply : {detail}")

    print("\n" + "=" * 50)

asyncio.run(main())