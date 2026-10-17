import os
import asyncio
from google import genai
from dotenv import load_dotenv
import io
import time
import random
from urllib.parse import quote
import aiohttp
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


async def generate_response(instructions, history):
    # Use gemini-3.8-flash from your configuration
    model_id = config.get("MODEL_ID", "gemini-3.8-flash")
    
    prompt_text = ""
    if instructions:
        prompt_text += f"System Directive / Context: {instructions}\n\n"

    # Slice history to the last 4 messages to keep payloads tiny and instantaneous
    recent_history = history[-4:] if len(history) > 4 else history

    for msg in recent_history:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        prompt_text += f"{role_label}: {msg['content']}\n"

    try:
        # Define the blocking SDK call to run safely in a background thread
        def _call_gemini():
            return client.interactions.create(
                model=model_id,
                input=prompt_text,
            )

        # Offload to thread so Discord's event loop stays completely unblocked
        interaction = await asyncio.wait_for(asyncio.to_thread(_call_gemini), timeout=30.0)
        return interaction.output_text
    except asyncio.TimeoutError:
        return "⏱️ The AI took too long to respond. Please try again!"
    except Exception as e:
        print(f"🔥 INTERACTIONS API CRITICAL ERROR: {str(e)}")
        return f"I encountered an error: `{str(e)[:100]}`"


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

    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(url, headers=headers) as response:
                json_data = await response.json()
                if json_data['status'] == 'succeeded':
                    async with session.get(f'https://images.prodia.xyz/{job_id}.png?download=1', headers=headers) as img_resp:
                        content = await img_resp.content.read()
                        img_file_obj = io.BytesIO(content)
                        duration = time.time() - start_time
                        print(f"\033[1;34m(Prodia) Finished image creation\n\033[0mJob id : {job_id}  Prompt : ", prompt, "in", duration, "seconds.")
                        return img_file_obj
                        
