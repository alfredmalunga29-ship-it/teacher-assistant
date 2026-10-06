import json

import requests


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, api_key):
        self.api_key = api_key

    def create(self, model, messages, temperature=0.2, max_tokens=2000):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _Response(content)


class _Chat:
    def __init__(self, api_key):
        self.completions = _Completions(api_key)


class Groq:
    def __init__(self, api_key):
        self.api_key = api_key
        self.chat = _Chat(api_key)
