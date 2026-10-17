import os
import yaml
import json

def load_config():
    config_path = "config.yml"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()

def load_instructions():
    instructions = {}
    instructions_dir = "instructions"
    if os.path.exists(instructions_dir):
        for filename in os.listdir(instructions_dir):
            if filename.endswith(".txt"):
                name = filename[:-4]
                path = os.path.join(instructions_dir, filename)
                with open(path, "r", encoding="utf-8") as f:
                    instructions[name] = f.read().strip()
    return instructions

def load_current_language():
    lang_code = config.get("LANGUAGE", "en")
    lang_path = f"lang/lang.{lang_code}.json"
    if os.path.exists(lang_path):
        with open(lang_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback to English if specified language file is missing
    fallback_path = "lang/lang.en.json"
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_active_channels():
    channels_path = "channels.json"
    if os.path.exists(channels_path):
        try:
            with open(channels_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}
    
