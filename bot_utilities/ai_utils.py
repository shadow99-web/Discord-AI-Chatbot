import os
import asyncio
import io
import time
import random
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from google import genai

from bot_utilities.config_loader import config

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ ERROR: GEMINI_API_KEY or GOOGLE_API_KEY is missing from environment variables!")

try:
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
except Exception as e:
    print(f"❌ Failed to initialize GenAI Client: {e}")
    client = None

# Tunables
GENAI_TIMEOUT = float(config.get("GENAI_TIMEOUT", 20))
GENAI_RETRIES = int(config.get("GENAI_RETRIES", 2))
GENAI_MAX_OUTPUT_TOKENS = int(config.get("GENAI_MAX_OUTPUT_TOKENS", 512))
GENAI_TEMPERATURE = float(config.get("GENAI_TEMPERATURE", 0.3))
GENAI_PROMPT_TOKEN_BUDGET = int(config.get("GENAI_PROMPT_TOKEN_BUDGET", 2200))
GENAI_CONCURRENCY = int(config.get("GENAI_CONCURRENCY", 4))

PRODIA_API_KEY = os.getenv("PRODIA_API_KEY")
PRODIA_TIMEOUT = float(os.getenv("PRODIA_TIMEOUT", "120"))
PRODIA_POLL_INTERVAL = float(os.getenv("PRODIA_POLL_INTERVAL", "1.5"))
PRODIA_STEPS_DEFAULT = int(os.getenv("PRODIA_STEPS", "18"))
PRODIA_CONCURRENCY = int(os.getenv("PRODIA_CONCURRENCY", "3"))

genai_semaphore = asyncio.Semaphore(GENAI_CONCURRENCY)
prodia_semaphore = asyncio.Semaphore(PRODIA_CONCURRENCY)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


async def generate_response(instructions, history):
    if client is None:
        return "❌ Gemini client is not initialized. Check your API key."

    model_id = config.get("MODEL_ID", "gemini-3.8-flash")

    prompt_parts = []
    if instructions:
        prompt_parts.append(f"System Directive / Context: {instructions}\n\n")

    total_tokens = _estimate_tokens("".join(prompt_parts))
    selected = []

    for msg in reversed(history):
        role = msg.get("role", "user")
        content = str(msg.get("content", ""))
        role_label = "User" if role == "user" else "Assistant"
        chunk = f"{role_label}: {content}\n"
        chunk_tokens = _estimate_tokens(chunk)

        if total_tokens + chunk_tokens > GENAI_PROMPT_TOKEN_BUDGET:
            break

        selected.append(chunk)
        total_tokens += chunk_tokens

    selected.reverse()
    prompt_text = "".join(prompt_parts) + "".join(selected)

    def _call_gemini_blocking():
        return client.interactions.create(
            model=model_id,
            input=prompt_text,
            temperature=GENAI_TEMPERATURE,
            max_output_tokens=GENAI_MAX_OUTPUT_TOKENS,
        )

    async with genai_semaphore:
        last_error = None

        for attempt in range(GENAI_RETRIES + 1):
            try:
                interaction = await asyncio.wait_for(
                    asyncio.to_thread(_call_gemini_blocking),
                    timeout=GENAI_TIMEOUT
                )

                output_text = getattr(interaction, "output_text", None)

                if not output_text and isinstance(interaction, dict):
                    output_text = (
                        interaction.get("output", {}).get("text")
                        or interaction.get("text")
                        or str(interaction)
                    )

                if not output_text:
                    output_text = str(interaction)

                return output_text

            except asyncio.TimeoutError as e:
                last_error = e
                await asyncio.sleep(0.6 * (attempt + 1))

            except Exception as e:
                last_error = e
                await asyncio.sleep(0.6 * (attempt + 1))

        print(f"🔥 INTERACTIONS API CRITICAL ERROR: {last_error}")
        return f"I encountered an error: `{str(last_error)[:100]}`"


async def poly_image_gen(session, prompt):
    seed = random.randint(1, 100000)
    encoded_prompt = quote(prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={seed}"

    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
        response.raise_for_status()
        image_data = await response.read()
        return io.BytesIO(image_data)


async def generate_image_prodia(session, prompt, model="midjourney", sampler="ddim", seed=None, neg=None,
                               steps=None, timeout=None):
    if session is None:
        timeout_obj = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout_obj) as temp_session:
            return await generate_image_prodia(temp_session, prompt, model, sampler, seed, neg, steps, timeout)
        return

    steps = steps or PRODIA_STEPS_DEFAULT
    timeout = timeout or PRODIA_TIMEOUT

    print("\033[1;32m(Prodia) Creating image for :\033[0m", prompt)
    start_time = time.time()

    if neg is None:
        negative = (
            "(nsfw:1.5),verybadimagenegative_v1.3,ng_deepnegative_v1_75t,"
            "(ugly face:0.8),cross-eyed,sketches,(worst quality:2),"
            "(low quality:2),(normal quality:2),lowres"
        )
    else:
        negative = neg

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if PRODIA_API_KEY:
        headers["Authorization"] = f"Bearer {PRODIA_API_KEY}"

    payload = {
        "new": True,
        "prompt": prompt,
        "model": model,
        "negative_prompt": negative,
        "steps": steps,
        "cfg": 7.0,
        "seed": seed if seed is not None else -1,
        "sampler": sampler,
        "upscale": False,
        "aspect_ratio": "square"
    }

    async with prodia_semaphore:
        try:
            async with session.post(
                "https://api.prodia.com/generate",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                response.raise_for_status()
                data = await response.json()

            job_id = data.get("job")
            if not job_id:
                raise RuntimeError(f"Prodia did not return a job id: {data}")

            job_url = f"https://api.prodia.com/job/{job_id}"
            image_url = f"https://images.prodia.xyz/{job_id}.png?download=1"

            deadline = time.time() + timeout

            while time.time() < deadline:
                try:
                    async with session.get(
                        job_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as status_resp:
                        status_resp.raise_for_status()
                        json_data = await status_resp.json()
                except Exception:
                    await asyncio.sleep(PRODIA_POLL_INTERVAL)
                    continue

                status = str(json_data.get("status", "")).lower()

                if status in ("succeeded", "completed"):
                    try:
                        async with session.get(
                            image_url,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=60)
                        ) as img_resp:
                            img_resp.raise_for_status()
                            content = await img_resp.read()
                            img_file_obj = io.BytesIO(content)
                            duration = time.time() - start_time
                            print(
                                f"\033[1;34m(Prodia) Finished image creation\n\033[0mJob id : {job_id}  "
                                f"Prompt : {prompt} in {duration:.2f} seconds."
                            )
                            return img_file_obj
                    except Exception as e:
                        raise RuntimeError(f"Failed to fetch image bytes: {e}")

                if status in ("failed", "error"):
                    raise RuntimeError(f"Prodia job failed: {json_data}")

                await asyncio.sleep(PRODIA_POLL_INTERVAL)

            raise TimeoutError(f"Prodia job {job_id} timed out after {timeout} seconds")

        except Exception as e:
            print(f"🔥 Prodia error: {e}")
            raise
