# AI Tech Radar

AI Tech Radar is a local daily research agent. It collects AI model, framework, tool, and research updates from configured sources, drops duplicates and low-value posts, and writes a short report. Each item keeps its original source link.

Summaries are grounded in the retrieved text. When Ollama is running, a local model drafts each item and a checker removes any numeric claim that does not appear in that source. If Ollama is not running, the report uses an extractive summary made only from the source text and says so.

## What each item includes

- What was introduced
- Who introduced it
- What it does
- Why it matters
- Technology, framework, or model involved
- Factual data that was present in the source, such as GitHub stars, release names, upvotes, or benchmark figures
- Potential real-world use cases stated by the source
- Original source link

The daily email subject is `What's new today`. It is sent at 8:00am IST and includes every collected model, framework, developer tool, research result, and major product update. Tips, digests, and hiring posts stay out. If nothing new was collected, the email says `There are no updates today.` The saved report still marks unsupported fields as `Not stated in source.` The agent does not fill them in from model memory. Leave the computer on or asleep at 8:00am so it can wake and send. A full shutdown skips that day's send instead of sending later.

## Run a sample report

From this folder:

```powershell
python -m ai_tech_radar run --offline --no-email --fresh
```

`--offline` reads `fixtures/sample_items.json` and does not call external sites or Ollama. The report is written to `reports/`.

## Daily live run

1. Install [Ollama](https://ollama.com/) and pull the model named in `config.json` (the default is `llama3.2`):

   ```powershell
   ollama pull llama3.2
   ```

2. Copy `.env.example` to `.env`.
3. Put a Gmail app password in `SMTP_PASSWORD` inside `.env`. Create one at https://myaccount.google.com/apppasswords. The report is addressed to `saisoumya.dolly@gmail.com`.
4. Optional: set `GITHUB_TOKEN` to raise GitHub API rate limits for star counts.
5. Confirm mail settings:

   ```powershell
   python -m ai_tech_radar test-email
   ```

The daily email is sent by GitHub Actions at 8:00am IST, from the workflow `.github/workflows/daily-radar.yml`. That run uses GitHub's computers, so the laptop can be shut down or switched off. The schedule is 02:30 UTC, which is 8:00am IST. GitHub may start the job a few minutes after 8:00. The laptop task is not the sender, because a shutdown laptop cannot run a program. Summaries in that cloud run are copied from the sources. A local Ollama model is not available there.

## Sources

`config.json` holds every feed and API endpoint. A source that fails is logged and skipped. The other sources still produce the report.

Enabled integrations:

- RSS or Atom feeds for OpenAI, Anthropic, Google DeepMind, the Google AI Blog, AI at Meta, Mistral, Hugging Face, BAIR, Simon Willison, Microsoft Research, and the AWS Machine Learning Blog
- Hugging Face Daily Papers API
- arXiv API for `cs.CL`, `cs.AI`, and `cs.LG`
- GitHub releases for a watch list of framework repositories, plus GitHub search for newly created repositories
- Hacker News stories above a configurable point threshold

`xai-news` is present and disabled until a feed URL is set. Add any other feed under `rss_feeds`. Set `enabled` to `false` or leave `url` empty to keep a source as a placeholder.

GitHub star counts are read from the GitHub API during enrichment. They are stored with the source item and passed to the summarizer as data, not guessed.

## Configuration

| Setting | Role |
| --- | --- |
| `lookback_hours` | How far back a live run looks. Default 36 hours. |
| `max_report_items` | Maximum items in one report. |
| `ollama.host` / `ollama.model` | Local model. Overridden by `OLLAMA_HOST` and `OLLAMA_MODEL`. |
| `ollama.fallback_extractive` | When true, a live run still writes a source-copied report if Ollama is down. |
| `filters.low_value_patterns` | Title and excerpt patterns to drop, such as hiring posts. |
| `github.watch_releases` | Repositories whose new releases are collected. |

Seen items are stored in `data/radar.sqlite`, so a later run does not repeat them. Offline sample runs use `data/offline.sqlite` instead. `--fresh` with `--offline` ignores that history for a repeatable sample.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Python 3.11 or newer is required. The agent uses the standard library only.
