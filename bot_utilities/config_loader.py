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
    fallback_path = "lang/lang.en.json"
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# 🚨 NEW: Memory cache for active channels
_active_channels_cache = None

def load_active_channels():
    global _active_channels_cache
    if _active_channels_cache is not None:
        return _active_channels_cache
        
    channels_path = "channels.json"
    if os.path.exists(channels_path):
        try:
            with open(channels_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    _active_channels_cache = {}
                    return _active_channels_cache
                _active_channels_cache = json.load(f)
                return _active_channels_cache
        except json.JSONDecodeError:
            _active_channels_cache = {}
            return _active_channels_cache
            
    _active_channels_cache = {}
    return _active_channels_cache

def save_active_channels(channels):
    global _active_channels_cache
    _active_channels_cache = channels # Update memory instantly
    with open("channels.json", "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=4)
