from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any

import requests
import yaml
import streamlit as st


class LLMClient:
    def __init__(self) -> None:
        self._load_dotenv()
        self.config = self._load_config()
        self.provider = self.config.get("llm", {}).get("provider", "groq")
        self.groq_model = self.config.get("llm", {}).get("groq", {}).get("model", "llama-3.1-8b-instant")
        self.groq_api_key = os.getenv("GROQ_API_KEY") or self.config.get("llm", {}).get("groq", {}).get("api_key", "")
        self.ollama_model = self.config.get("llm", {}).get("ollama", {}).get("model", "llama3.2")
        self.ollama_base_url = self.config.get("llm", {}).get("ollama", {}).get("base_url", "http://localhost:11434")

    def _load_dotenv(self) -> None:
        env_path = Path(".env")
        if not env_path.exists():
            return

        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    def _resolve_env_vars(self, value: Any) -> Any:
        if isinstance(value, str):
            return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: os.getenv(match.group(1), ""), value)
        if isinstance(value, dict):
            return {key: self._resolve_env_vars(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._resolve_env_vars(item) for item in value]
        return value

    def _load_config(self) -> dict[str, Any]:
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as handle:
            raw_config = yaml.safe_load(handle) or {}
        return self._resolve_env_vars(raw_config)

    def _load_runtime_settings(self) -> tuple[str, str, str]:
        provider = self.provider
        model = self.groq_model if provider == "groq" else self.ollama_model
        api_key = self.groq_api_key

        try:
            user = getattr(st.session_state, "user", None)
            if user is not None:
                from db.models import Settings
                from db.session import SessionLocal

                session = SessionLocal()
                try:
                    settings = session.query(Settings).filter(Settings.user_id == user.id).first()
                    if settings:
                        provider = settings.provider or provider
                        model = settings.model or model
                        if settings.api_key_encrypted:
                            api_key = self._decrypt_secret(settings.api_key_encrypted)
                finally:
                    session.close()
        except Exception:
            pass

        return provider, model, api_key

    @staticmethod
    def _encrypt_secret(value: str) -> str:
        if not value:
            return ""
        secret = os.getenv("JOBAA_SECRET_KEY", "jobaa-default-secret")
        secret_bytes = secret.encode("utf-8")
        plain_bytes = value.encode("utf-8")
        encoded = bytearray(len(plain_bytes))
        for index, byte in enumerate(plain_bytes):
            encoded[index] = byte ^ secret_bytes[index % len(secret_bytes)]
        return base64.b64encode(bytes(encoded)).decode("ascii")

    @staticmethod
    def _decrypt_secret(value: str) -> str:
        if not value:
            return ""
        secret = os.getenv("JOBAA_SECRET_KEY", "jobaa-default-secret")
        secret_bytes = secret.encode("utf-8")
        decoded = base64.b64decode(value.encode("ascii"))
        plain = bytearray(len(decoded))
        for index, byte in enumerate(decoded):
            plain[index] = byte ^ secret_bytes[index % len(secret_bytes)]
        return bytes(plain).decode("utf-8")

    def get_available_models(self, provider: str) -> list[str]:
        if provider == "ollama":
            return ["llama3.2", "llama3.1", "phi3"]
        return ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"]

    def generate(self, prompt: str) -> str:
        provider, model, api_key = self._load_runtime_settings()
        if provider == "ollama":
            return self._generate_with_ollama(prompt, model)
        return self._generate_with_groq(prompt, model, api_key)

    def _generate_with_groq(self, prompt: str, model: str, api_key: str) -> str:
        if not api_key:
            return "Groq API key is not configured."
        try:
            from groq import Groq
        except ImportError:
            return "groq package is not installed."

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    def _generate_with_ollama(self, prompt: str, model: str) -> str:
        try:
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception:
            return "Ollama service is not available."


llm_client = LLMClient()
