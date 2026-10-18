import os
import asyncio
import io
import time
import random
from urllib.parse import quote
from typing import Any

import aiohttp
from dotenv import load_dotenv
from google import genai

from bot_utilities.config_loader import config

load_dotenv()

# Groq first: fast, low-latency chat completions that work well for lightweight models.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "60"))
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.3"))
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "512"))

# Gemini fallback config (kept for compatibility if Groq is unavailable)
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


def _build_groq_messages(instructions, history):
    messages = []

    if instructions:
        messages.append({"role": "system", "content": str(instructions)})

    for msg in history:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "user")
        if role not in {"user", "assistant", "system"}:
            continue

        content = msg.get("content", "")
        messages.append({"role": role, "content": str(content)})

    return messages


async def _generate_response_groq(instructions, history):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing from environment variables.")

    messages = _build_groq_messages(instructions, history)
    request_url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": GROQ_TEMPERATURE,
        "max_tokens": GROQ_MAX_TOKENS,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT)) as session:
        async with session.post(request_url, json=payload, headers=headers) as response:
            try:
                data = await response.json(content_type=None)
            except Exception:
                text = await response.text()
                raise RuntimeError(f"Groq returned an invalid response: {text[:200]}")

            if response.status >= 400:
                error_detail = data.get("error") if isinstance(data, dict) else data
                if isinstance(error_detail, dict):
                    message = error_detail.get("message") or str(error_detail)
                else:
                    message = str(error_detail)
                raise RuntimeError(f"Groq API error ({response.status}): {message}")

            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"Groq returned no choices: {data}")

            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content")

            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict):
                        part_text = part.get("text") or part.get("content")
                        if isinstance(part_text, str):
                            text_parts.append(part_text)
                if text_parts:
                    return "".join(text_parts).strip()

            if isinstance(content, str):
                return content.strip()

            if isinstance(message, dict):
                return str(message).strip()

            return str(data).strip()


def _extract_gemini_text(response: Any) -> str:
    if response is None:
        return ""

    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        candidate = (
            response.get("output_text")
            or response.get("text")
            or response.get("content")
            or response.get("output")
        )
        if isinstance(candidate, str) and candidate.strip():
            return candidate

        if isinstance(candidate, dict):
            nested = (
                candidate.get("text")
                or candidate.get("content")
                or candidate.get("value")
            )
            if isinstance(nested, str) and nested.strip():
                return nested

        for key in ("candidates", "responses"):
            items = response.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        text = (
                            item.get("text")
                            or item.get("content")
                            or item.get("output_text")
                        )
                        if isinstance(text, str) and text.strip():
                            return text
                        if isinstance(item.get("parts"), list):
                            joined_parts = []
                            for part in item["parts"]:
                                if isinstance(part, dict):
                                    part_text = part.get("text") or part.get("content")
                                    if isinstance(part_text, str):
                                        joined_parts.append(part_text)
                                elif isinstance(part, str):
                                    joined_parts.append(part)
                            combined = "".join(joined_parts)
                            if combined.strip():
                                return combined

        return str(response)

    for attr in ("output_text", "text", "content"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, list):
        for candidate in candidates:
            if hasattr(candidate, "content"):
                content = getattr(candidate.content, "parts", None)
                if content:
                    texts = []
                    for part in content:
                        part_text = getattr(part, "text", None)
                        if isinstance(part_text, str) and part_text.strip():
                            texts.append(part_text)
                    if texts:
                        return "".join(texts)
            if isinstance(candidate, dict):
                text = candidate.get("text") or candidate.get("content")
                if isinstance(text, str) and text.strip():
                    return text

    parts = getattr(response, "parts", None)
    if isinstance(parts, list):
        texts = []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                texts.append(part_text)
        if texts:
            return "".join(texts)

    return str(response)


def _call_gemini_blocking(model_id: str, prompt_text: str):
    """Fallback pathway for older/newer Gemini SDKs. Try multiple supported client patterns."""
    config_payload = {
        "temperature": GENAI_TEMPERATURE,
        "max_output_tokens": GENAI_MAX_OUTPUT_TOKENS,
    }

    attempts = []

    def try_call(name: str, fn):
        try:
            res = fn()
            return res
        except TypeError as e:
            attempts.append((name, e))
            return None
        except Exception as e:
            attempts.append((name, e))
            return None

    interactions = getattr(client, "interactions", None)
    responses_api = getattr(client, "responses", None)
    models = getattr(client, "models", None)

    if interactions is not None and hasattr(interactions, "create"):
        res = try_call("interactions.create(extra_body)", lambda: interactions.create(
            model=model_id, input=prompt_text, extra_body=config_payload
        ))
        if res is not None:
            return res

        res = try_call("interactions.create(simple)", lambda: interactions.create(
            model=model_id, input=prompt_text
        ))
        if res is not None:
            return res

    if responses_api is not None and hasattr(responses_api, "create"):
        res = try_call("responses.create(extra_body)", lambda: responses_api.create(
            model=model_id, input=prompt_text, extra_body=config_payload
        ))
        if res is not None:
            return res

        res = try_call("responses.create(simple)", lambda: responses_api.create(
            model=model_id, input=prompt_text
        ))
        if res is not None:
            return res

    if hasattr(client, "generate_content"):
        res = try_call("client.generate_content(config)", lambda: client.generate_content(
            model=model_id, contents=prompt_text, config=config_payload
        ))
        if res is not None:
            return res

        res = try_call("client.generate_content(simple)", lambda: client.generate_content(
            model=model_id, contents=prompt_text
        ))
        if res is not None:
            return res

    if models is not None and hasattr(models, "generate_content"):
        res = try_call("models.generate_content(config)", lambda: models.generate_content(
            model=model_id, contents=prompt_text, config=config_payload
        ))
        if res is not None:
            return res

        res = try_call("models.generate_content(simple)", lambda: models.generate_content(
            model=model_id, contents=prompt_text
        ))
        if res is not None:
            return res

    if attempts:
        combined = "; ".join(f"{name}: {type(err).__name__}: {str(err)}" for name, err in attempts)
        raise RuntimeError(f"No supported Gemini API call worked: {combined}")

    raise RuntimeError("No Gemini API method was available on the client instance.")


async def _generate_response_gemini(instructions, history):
    if client is None:
        return "❌ Gemini client is not initialized. Check your API key."

    model_id = config.get("MODEL_ID", "gemini-2.5-flash")

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

    async with genai_semaphore:
        last_error = None

        for attempt in range(GENAI_RETRIES + 1):
            try:
                interaction = await asyncio.wait_for(
                    asyncio.to_thread(_call_gemini_blocking, model_id, prompt_text),
                    timeout=GENAI_TIMEOUT,
                )

                output_text = _extract_gemini_text(interaction)
                if not output_text or not str(output_text).strip():
                    output_text = str(interaction)

                return output_text.strip() or "I generated an empty response."

            except asyncio.TimeoutError as e:
                last_error = e
                await asyncio.sleep(0.6 * (attempt + 1))
            except Exception as e:
                last_error = e
                await asyncio.sleep(0.6 * (attempt + 1))

        print(f"🔥 Gemini API critical error: {last_error}")
        return f"I encountered an error: `{str(last_error)[:100]}`"


async def generate_response(instructions, history):
    """Try Groq first for low-latency replies; fall back to Gemini if Groq is unavailable."""
    try:
        return await _generate_response_groq(instructions, history)
    except Exception as e:
        print(f"⚠️ Groq failed, falling back to Gemini: {e}")
        return await _generate_response_gemini(instructions, history)


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
