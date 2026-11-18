"""llm/gemini_rest.py without the network: httpx.post is replaced by a fake that returns chosen
responses. Run from backend/:   python test/test_gemini_rest.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

import llm.gemini_rest as G  # noqa: E402
import llm.retry as retry  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("PASS " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


sent: list = []
replies: list = []


def fake_post(url, headers, json, timeout):
    sent.append({"url": url, "json": json, "timeout": timeout})
    reply = replies.pop(0)
    if isinstance(reply, Exception):
        raise reply
    status, body = reply
    return httpx.Response(status, json=body, request=httpx.Request("POST", url))


G.httpx.post = fake_post
retry.time.sleep = lambda s: None  # no real waiting between retries

client = G.GeminiREST("test-model", temperature=0, max_output_tokens=100, timeout=7)

# a normal answer, with a hidden-reasoning part that must not reach the caller
replies.append((200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
    {"text": "thinking...", "thought": True}, {"text": '{"ok": '}, {"text": "true}"}]}}]}))
r = client.invoke([
    {"role": "system", "content": "Answer in JSON."},
    {"role": "user", "content": [
        {"type": "text", "text": "Read this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]},
])
check("answer text joined, reasoning dropped", r.content == '{"ok": true}')
check("finish reason reported", r.response_metadata["finish_reason"] == "STOP")
body = sent[-1]["json"]
check("timeout passed to the request", sent[-1]["timeout"] == 7)
check("system message sent as systemInstruction", body["systemInstruction"]["parts"] == [{"text": "Answer in JSON."}])
check("image sent inline with its type", body["contents"][0]["parts"][1] == {"inline_data": {"mime_type": "image/png", "data": "QUJD"}})
check("model in the URL", "/models/test-model:generateContent" in sent[-1]["url"])

replies.append((200, {"promptFeedback": {"blockReason": "SAFETY"}}))
r = client.invoke([{"role": "user", "content": "x"}])
check("blocked prompt -> empty text with the reason", r.content == "" and r.response_metadata["finish_reason"] == "SAFETY")


def raises(exc_type, reply):
    replies.append(reply)
    try:
        client.invoke([{"role": "user", "content": "x"}])
    except exc_type:
        return True
    except Exception as e:  # noqa: BLE001
        print("   got", type(e).__name__, e)
    return False


check("503 overloaded -> GeminiUnavailableError", raises(G.GeminiUnavailableError, (503, {"error": {"message": "high demand"}})))
check("429 quota -> GeminiRateLimitError", raises(G.GeminiRateLimitError, (429, {"error": {"message": "quota"}})))
check("timeout -> GeminiUnavailableError", raises(G.GeminiUnavailableError, httpx.ReadTimeout("slow")))
check("400 bad request -> plain error, not retried", raises(RuntimeError, (400, {"error": {"message": "bad"}})))

# retrying: two 503s with attempts=2 gives up with LLMUnavailableError after exactly two requests
before = len(sent)
replies.extend([(503, {}), (503, {})])
try:
    retry.invoke_with_retry(client, [{"role": "user", "content": "x"}], attempts=2)
    check("gives up after the attempts", False)
except retry.LLMUnavailableError:
    check("gives up after the attempts", len(sent) - before == 2)

# a 503 then a success is retried into the answer
replies.extend([(503, {}), (200, {"candidates": [{"content": {"parts": [{"text": "fine"}]}}]})])
check("recovers on the second try", retry.invoke_with_retry(client, [{"role": "user", "content": "x"}], attempts=2).content == "fine")

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
