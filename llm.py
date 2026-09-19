"""Thin Ollama client. Swap this file out to use a different backend."""

import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, url, timeout=600):
        self.url = url
        self.timeout = timeout

    def chat(self, model, messages, temperature=0.8, max_tokens=None, on_token=None):
        """Return the model's full reply. If on_token is given, stream tokens to it."""
        options = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        stream = on_token is not None

        payload = json.dumps(
            {"model": model, "messages": messages, "stream": stream, "options": options}
        ).encode()
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if not stream:
                    return json.loads(resp.read())["message"]["content"]

                reply = ""
                for line in resp:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        on_token(token)
                        reply += token
                    if chunk.get("done"):
                        break
                return reply
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise LLMError(f"Ollama returned {e.code} for model '{model}': {body}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Could not reach Ollama at {self.url}: {e.reason}") from e
        except TimeoutError as e:
            raise LLMError(
                f"Model '{model}' gave no response for {self.timeout}s "
                "(usually the machine is short on RAM or running on CPU)"
            ) from e
        except (OSError, ValueError, KeyError) as e:
            raise LLMError(f"Bad or interrupted response from Ollama: {e!r}") from e