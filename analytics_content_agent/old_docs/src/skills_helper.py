import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from aisuite import Client

client = Client()


def clean_json_block(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip("` \n")






