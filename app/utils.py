"""Minimal utilities for simplified extraction pipeline Original 1275-line
version moved to archive/app_scripts/utils_old.py."""

import os

import anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
