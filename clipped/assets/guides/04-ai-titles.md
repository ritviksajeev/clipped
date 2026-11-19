# Optional: AI titles (Claude, Gemini, OpenRouter, Ollama or your own key)

clipped writes titles, hook text, descriptions and hashtags for free using built-in templates. If you'd like more natural titles, connect an AI under **Settings → Connections → AI titles**. Most options are a single button, with no key to copy.

Whichever generator you use, clipped always adds the streamer credit, the channel link, the original clip link and `#Shorts` itself. A model can't drop them.

## Claude: sign in with Anthropic

1. Install the free Anthropic CLI (`ant`) once. Get it from <https://github.com/anthropics/anthropic-cli/releases> (macOS: `brew install anthropics/tap/ant`).
2. In clipped, click **Sign in with Anthropic**. Your browser opens; sign in to your Anthropic Console account and approve.
3. That's it. clipped switches titles to Claude automatically if you were on the free templates.

The sign-in is saved by the Anthropic CLI on your computer, and the official Anthropic library refreshes it by itself. clipped never sees or stores a key. You pay Anthropic per use (usually a fraction of a cent per clip), so add credit under **Billing** at <https://console.anthropic.com/>. The default model is `claude-opus-5-5`; for the cheapest option set it to `claude-haiku-5-5` in **Settings → Titles & AI**.

> **Claude.ai Pro/Max chat plans can't be used here.** Anthropic doesn't let other apps use a chat subscription. The same goes for ChatGPT Plus. Use the Console sign-in above, OpenRouter, or a free option.

## Google Gemini: a free API key

Google's Gemini API has a free tier that comfortably covers a few titles an hour.

1. Open <https://aistudio.google.com/apikey> and sign in with your Google account.
2. Click **Create API key** (pick or create any Google Cloud project when asked) and copy the key. It starts with `AIza`.
3. In clipped, paste it into the **Gemini** card and click **Save key**. clipped switches titles to Gemini if you were on the free templates.

The key is stored in your OS keychain and only ever sent to Google, in a request header. The default model is `gemini-flash-latest` (Google's current Flash model, on the free tier). For the best titles set `gemini-pro-latest` in **Settings → Titles & AI**; the free tier allows fewer Pro requests per day. If you hit the free-tier limit, clipped uses the templates until it resets.

## OpenRouter: one account, many models

[OpenRouter](https://openrouter.ai) gives one account access to Claude, GPT, Gemini, Llama and several free models.

1. Click **Connect OpenRouter**. Your browser opens openrouter.ai; sign in and approve clipped.
2. OpenRouter sends clipped a key made just for it, which is saved in your OS keychain. You can revoke it any time on openrouter.ai.
3. The model defaults to `openrouter/auto` (OpenRouter picks). To choose one yourself, paste any model id from <https://openrouter.ai/models> in **Settings → Titles & AI**. Ids ending in `:free` cost nothing.

## Ollama: free, on your own computer

1. Install Ollama from <https://ollama.com/download> and pull a model, e.g. `ollama pull llama3.2`.
2. Keep Ollama running. clipped detects it automatically; click **Use for titles**.

No account, no key and no cost. Titles take a little longer on computers without a strong GPU.

## Or paste an API key

Under **…or paste an API key instead** you can still paste an Anthropic key (`sk-ant-…`, from <https://console.anthropic.com/>) or an OpenAI key (from <https://platform.openai.com/api-keys>).

## How variants work

For every clip clipped writes 2-3 title *styles* (hype, question, descriptive, streamer-first). In the review queue you can pick one or edit it. In Auto mode the optimizer tracks which style earns the most views and retention on **your** channel and favours it, while still trying the others occasionally.

If the AI is unreachable, out of credit or signed out, clipped falls back to the free templates and notes it in the log.
