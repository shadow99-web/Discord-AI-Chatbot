
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
from gtts import gTTS
import io
import time
import random
from urllib.parse import quote
import aiohttp
from langdetect import detect
from duckduckgo_search import DDGS
from bot_utilities.config_loader import config

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

# Initialize the official Google GenAI client
client = genai.Client(api_key=api_key)

async def generate_response(instructions, history):
    model_id = config.get("MODEL_ID", "gemini-2.5-flash")
    internet_access = config.get("INTERNET_ACCESS", True)
    max_results = config.get("MAX_SEARCH_RESULTS", 4)
    
    # Format the message history into Gemini content format
    contents = []
    
    # Add system instructions / persona context as the first turns
    formatted_history = []
    if instructions:
        formatted_history.append({"role": "user", "parts": [{"text": f"System Directive / Context: {instructions}"}]})
        formatted_history.append({"role": "model", "parts": [{"text": "Understood. I will adopt this persona and guidelines."}]})

    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    full_contents = formatted_history + contents if instructions else contents

    # Perform DuckDuckGo search lookup if internet access is enabled
    search_context = ""
    if internet_access and history:
        latest_query = history[-1]["content"]
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(latest_query, max_results=max_results))
                if results:
                    search_context = "\n\nRealtime Web Search Results:\n"
                    for r in results:
                        search_context += f"- {r.get('title')}: {r.get('body')} ({r.get('href')})\n"
        except Exception as e:
            print(f"Search error: {e}")

    if search_context and full_contents:
        full_contents[-1]["parts"][0]["text"] += search_context

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=full_contents,
            config=types.GenerateContentConfig(
                temperature=0.7,
            ),
        )
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "I encountered an error while trying to think of a response. Please check my configuration keys!"

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
            'steps': '100',
            'cfg': '9.5',
            'seed': f'{seed}',
            'sampler': sampler,
            'upscale': 'True',
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

async def text_to_speech(text):
    try:
        bytes_obj = io.BytesIO()
        detected_language = detect(text)
        tts = gTTS(text=text, lang=detected_language)
        tts.write_to_fp(bytes_obj)
        bytes_obj.seek(0)
        return bytes_obj
    except Exception as e:
        print(f"TTS Error: {e}")
        return None
