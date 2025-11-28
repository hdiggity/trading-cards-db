"""Minimal utilities for simplified extraction pipeline Original 1275-line
version moved to archive/app_scripts/utils_old.py."""

import os

from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
