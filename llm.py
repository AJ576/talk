"""Thin Ollama client. Swap this file out to use a different backend."""

import json
import socket
import urllib.error
import urllib.request
from typing import NamedTuple


class LLMError(Exception):
    """Something went wrong talking to the model.

    retryable=False means trying again can't help (e.g. model not pulled)."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class Reply(NamedTuple):
    text: str
    truncated: bool  # True if the model stopped because it hit the token limit


class OllamaClient:
    def __init__(self, url, timeout=600, num_ctx=None):
        self.url = url
        self.timeout = timeout
        self.num_ctx = num_ctx

    def _timeout_error(self, model):
        return LLMError(
            f"Model '{model}' gave no response for {self.timeout}s "
            "(usually the machine is short on RAM or running on CPU)"
        )

    def chat(self, model, messages, temperature=0.8, max_tokens=None, on_token=None):
        """Return a Reply. If on_token is given, stream tokens to it as they arrive."""
        options = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
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
                    data = json.loads(resp.read())
                    if "error" in data:
                        raise LLMError(f"Ollama error: {data['error']}")
                    return Reply(
                        data["message"]["content"], data.get("done_reason") == "length"
                    )

                reply = ""
                finished = False
                truncated = False
                for line in resp:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    # Ollama can report a failure mid-stream with a 200 status.
                    if "error" in chunk:
                        raise LLMError(f"Ollama error: {chunk['error']}")
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        reply += token
                        if on_token is not None:
                            # Display problems (e.g. a console that can't print a
                            # character) must not be mistaken for model failures.
                            try:
                                on_token(token)
                            except Exception:
                                on_token = None  # stop displaying, keep generating
                    if chunk.get("done"):
                        finished = True
                        truncated = chunk.get("done_reason") == "length"
                        break
                if not finished:
                    raise LLMError("The connection ended before the reply was finished")
                return Reply(reply, truncated)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            hint = f" (try: ollama pull {model})" if e.code == 404 else ""
            # 4xx means our request is wrong; retrying the same thing won't help.
            retryable = e.code >= 500 or e.code in (408, 429)
            raise LLMError(
                f"Ollama returned {e.code} for model '{model}': {body}{hint}",
                retryable=retryable,
            ) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                raise self._timeout_error(model) from e
            raise LLMError(f"Could not reach Ollama at {self.url}: {e.reason}") from e
        except (TimeoutError, socket.timeout) as e:  # separate types before Python 3.10
            raise self._timeout_error(model) from e
        except (OSError, ValueError, KeyError) as e:
            raise LLMError(f"Bad or interrupted response from Ollama: {e!r}") from e