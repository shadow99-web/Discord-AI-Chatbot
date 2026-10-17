import os
import asyncio
import time
import random
import io
from urllib.parse import quote
import aiohttp
from dotenv import load_dotenv
from google import genai
from bot_utilities.config_loader import config

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ ERROR: GEMINI_API_KEY or GOOGLE_API_KEY is missing from environment variables!")

# Initialize the official Google GenAI client natively
try:
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
except Exception as e:
    print(f"❌ Failed to initialize GenAI Client: {e}")

# Performance & Concurrency Controls
GENAI_CALL_TIMEOUT = float(config.get("GENAI_CALL_TIMEOUT", 25.0))
GENAI_RETRIES = int(config.get("GENAI_RETRIES", 2))
_genai_semaphore = asyncio.Semaphore(int(config.get("GENAI_CONCURRENCY", 4)))


def _estimate_tokens(text: str) -> int:
    # Fast character-to-token heuristic (approx 4 chars per token)
    return max(1, int(len(text) / 4))


async def generate_response(instructions, history):
    model_id = config.get("MODEL_ID", "gemini-3.8-flash")
    
    prompt_parts = []
    if instructions:
        prompt_parts.append(f"System Directive / Context: {instructions}\n\n")

    # Token-budget-aware history trimming (defaults to ~2400 token ceiling)
    max_prompt_tokens = int(config.get("MODEL_PROMPT_TOKEN_BUDGET", 2400))
    total_tokens = _estimate_tokens("".join(prompt_parts))
    
    selected = []
    for msg in reversed(history):
        role_label = "User" if msg.get("role") == "user" else "Assistant"
        piece = f"{role_label}: {msg.get('content', '')}\n"
        piece_tokens = _estimate_tokens(piece)
        if total_tokens + piece_tokens > max_prompt_tokens:
            break
        selected.append(piece)
        total_tokens += piece_tokens
    
    selected.reverse()
    prompt_text = "".join(prompt_parts) + "".join(selected)

    def _call_gemini_blocking():
        return client.interactions.create(
            model=model_id,
            input=prompt_text,
        )

    # Execute with semaphore protection, timeout, and simple retries
    async with _genai_semaphore:
        last_exc = None
        for attempt in range(GENAI_RETRIES + 1):
            try:
                task = asyncio.to_thread(_call_gemini_blocking)
                interaction = await asyncio.wait_for(task, timeout=GENAI_CALL_TIMEOUT)
                return interaction.output_text
            except asyncio.TimeoutError as te:
                last_exc = te
                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as e:
                last_exc = e
                await asyncio.sleep(0.5 * (attempt + 1))

        print(f"🔥 INTERACTIONS API CRITICAL ERROR: {last_exc}")
        return f"I encountered an error: `{str(last_exc)[:100]}`"


async def poly_image_gen(session, prompt):
    seed = random.randint(1, 100000)
    image_url = f"https://image.pollinations.ai/prompt/{prompt}?seed={seed}"
    async with session.get(image_url) as response:
        image_data = await response.read()
        return io.BytesIO(image_data)


async def generate_image_prodia(prompt, model, sampler, seed, neg):
    print("\033[1;32m(Prodia) Creating image for :\033[0m", prompt)
    start_time = time.time()
    
    async def create_job(prompt, model, sampler, seed, neg):
        if neg is None:
            negative = "(nsfw:1.5),verybadimagenegative_v1.3, ng_deepnegative_v1_75t, (ugly face:0.8),cross-eyed,sketches, (worst quality:2), (low quality:2), (normal quality:2), lowres, normal quality, ((monochrome)), ((grayscale)), skin spots, acnes, skin blemishes, bad anatomy, DeepNegative, facing away, tilted head, {Multiple people}, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worstquality, low quality, normal quality, jpegartifacts, signature, watermark, username, blurry, bad feet, cropped, poorly drawn hands, poorly drawn face, mutation, deformed, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, extra fingers, fewer digits, extra limbs, extra arms,extra legs, malformed limbs, fused fingers, too many fingers, long neck, cross-eyed,mutated hands, polar lowres, bad body, bad proportions, gross proportions, text, error, missing fingers, missing arms, missing legs, extra digit, extra arms, extra leg, extra foot, repeating hair, nsfw, [[[[[bad-artist-anime, sketch by bad-artist]]]]], [[[mutation, lowres, bad hands, [text, signature, watermark, username], blurry, monochrome, grayscale, realistic, simple background, limited palette]]], close-up, (swimsuit, cleavage, armpits, ass, navel, cleavage cutout), (forehead jewel:1.2), (forehead mark:1.5), (bad and mutated hands:1.3), (worst quality:2.0), (low quality:2.0), (blurry:2.0), multiple limbs, bad anatomy, (interlocked fingers:1.2),(interlocked leg:1.2), Ugly Fingers, (extra digit and hands and fingers and legs and arms:1.4), crown braid, (deformed fingers:1.2), (long fingers:1.2)"
        else:
            negative = neg
            
        url = 'https://api.prodia.com/generate'
        params = {
            'new': 'true',
            'prompt': f'{quote(prompt)}',
            'model': model,
            'negative_prompt': f"{negative}",
            'steps': '25',
            'cfg': '7.0',
            'seed': f'{seed}',
            'sampler': sampler,
            'upscale': 'False',
            'aspect_ratio': 'square'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
                return data['job']
            
    job_id = await create_job(prompt, model, sampler, seed, neg)
    url = f'https://api.prodia.com/job/{job_id}'
    headers = {
        'authority': 'api.prodia.com',
        'accept': '*/*',
    }

    # Use a persistent session with timeout and a non-blocking poll loop (`await asyncio.sleep(1)`)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        while True:
            async with session.get(url, headers=headers) as response:
                json_data = await response.json()
                if json_data.get('status') == 'succeeded':
                    async with session.get(f'https://images.prodia.xyz/{job_id}.png?download=1', headers=headers) as img_resp:
                        content = await img_resp.content.read()
                        img_file_obj = io.BytesIO(content)
                        duration = time.time() - start_time
                        print(f"\033[1;34m(Prodia) Finished image creation\n\033[0mJob id : {job_id}  Prompt : {prompt} in {duration} seconds.")
                        return img_file_obj
                elif json_data.get('status') in ('failed', 'error'):
                    raise RuntimeError(f"Prodia job failed: {json_data}")
            
            # Prevent CPU burn and rate limits with a polite 1-second delay between checks
            await asyncio.sleep(1.0)
    
