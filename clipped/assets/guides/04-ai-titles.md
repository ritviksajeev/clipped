# Optional: AI titles with your own Anthropic or OpenAI key

clipped writes titles, hook text, descriptions and hashtags for free using built-in templates. If you'd like more natural titles, add your own API key. You pay the provider directly for what you use, usually a fraction of a cent per clip.

Whichever generator you use, clipped always adds the streamer credit, the channel link, the original clip link and `#Shorts` itself. A model can't drop them.

## Anthropic (Claude)

1. Create an account at <https://console.anthropic.com/> and add credit under **Billing**.
2. Open **API Keys** → **Create Key**, name it `clipped`, and copy the key (it starts with `sk-ant-`).
3. In clipped: **Settings → Titles & AI**, paste it under **Anthropic API key**, set **Title generator** to **Anthropic**, and save.
4. The default model is `claude-opus-5-5`. For the cheapest option, set the model to `claude-haiku-5-5`.

## OpenAI

1. Create a key at <https://platform.openai.com/api-keys>.
2. In clipped paste it under **OpenAI API key**, set **Title generator** to **OpenAI**, and enter a model name your account can use.

## How variants work

For every clip clipped writes 2-3 title *styles* (hype, question, descriptive, streamer-first). In the review queue you can pick one or edit it. In Auto mode the optimizer tracks which style earns the most views and retention on **your** channel and favours it, while still trying the others occasionally.

If the provider is unreachable or the key is wrong, clipped falls back to the free templates and notes it in the log.
