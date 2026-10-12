from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ai_tech_radar.analyze import analysis_from_payload, extractive_analysis, parse_model_json
from ai_tech_radar.config import PROJECT_ROOT, load_config
from ai_tech_radar.filter import classify, prepare_items, select_balanced
from ai_tech_radar.grounding import ground_analysis
from ai_tech_radar.mailer import can_send
from ai_tech_radar.models import Analysis, ReportEntry, SourceItem
from ai_tech_radar.pipeline import run_pipeline
from ai_tech_radar.report import email_subject, render_email_text
from ai_tech_radar.schedule import IST, next_run
from ai_tech_radar.sources.arxiv import build_arxiv_url
from ai_tech_radar.sources.github import build_repo_search_url, repos_from_search
from ai_tech_radar.sources.hackernews import stories_from_payload
from ai_tech_radar.sources.huggingface import papers_from_payload
from ai_tech_radar.sources.rss import parse_feed
from ai_tech_radar.store import Store
from ai_tech_radar.textutil import canonical_url, title_key


NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def sample_item(**overrides) -> SourceItem:
    data = {
        "source_id": "lab",
        "source_name": "Sample Lab Blog",
        "title": "Sample Lab releases SampleForge 2",
        "url": "https://example.com/blog/sampleforge-2",
        "published_at": "2026-10-05T08:00:00+00:00",
        "excerpt": "Sample Lab introduced SampleForge 2, a 7B open-weight language model.",
        "authors": ["A. Example"],
        "metadata": {"priority": 80},
    }
    data.update(overrides)
    return SourceItem(**data)


class TextTests(unittest.TestCase):
    def test_canonical_url_strips_tracking_and_arxiv_version(self):
        self.assertEqual(
            canonical_url("https://www.Example.com/blog/post/?utm_source=newsletter"),
            "https://example.com/blog/post",
        )
        self.assertEqual(
            canonical_url("http://arxiv.org/pdf/2401.01234v2.pdf"),
            "https://arxiv.org/abs/2401.01234",
        )

    def test_title_key_collapses_punctuation(self):
        self.assertEqual(title_key("SampleForge 2: A Release!"), "sampleforge 2 a release")


class FeedTests(unittest.TestCase):
    def test_parse_rss_and_atom(self):
        rss = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>Model release</title>
            <link>https://example.com/model</link>
            <pubDate>Sun, 05 Oct 2026 08:00:00 GMT</pubDate>
            <description>A &amp; B released a model.</description>
            <author>Lab</author>
          </item>
        </channel></rss>"""
        atom = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Paper title</title>
            <link href="https://arxiv.org/abs/2401.00001v1"/>
            <published>2026-10-05T08:00:00Z</published>
            <summary>We present a framework.</summary>
            <author><name>B. Example</name></author>
          </entry>
        </feed>"""
        rss_items = parse_feed(rss)
        atom_items = parse_feed(atom)
        self.assertEqual(rss_items[0]["title"], "Model release")
        self.assertEqual(rss_items[0]["excerpt"], "A & B released a model.")
        self.assertEqual(atom_items[0]["authors"], ["B. Example"])
        self.assertEqual(atom_items[0]["url"], "https://arxiv.org/abs/2401.00001v1")


class SourceShapeTests(unittest.TestCase):
    def test_huggingface_payload(self):
        payload = [
            {
                "publishedAt": "2026-10-05T00:00:00Z",
                "paper": {
                    "id": "sample",
                    "title": "Router",
                    "summary": "We present a model.",
                    "authors": [{"name": "B. Example"}],
                },
                "upvotes": 12,
            }
        ]
        items = papers_from_payload(payload, min_upvotes=5)
        self.assertEqual(items[0].url, "https://huggingface.co/papers/sample")
        self.assertEqual(items[0].metadata["upvotes"], 12)
        self.assertEqual(papers_from_payload(payload, min_upvotes=20), [])

    def test_github_and_hn_shapes(self):
        config = {"github": {"api_base": "https://api.github.com", "search_query": "llm", "min_stars": 50, "search_per_page": 5}}
        url = build_repo_search_url(config, "2026-10-04")
        self.assertIn("search/repositories", url)
        self.assertIn("stars%3A%3E%3D50", url)
        repos = repos_from_search(
            {"items": [{"full_name": "acme/forge", "html_url": "https://github.com/acme/forge", "description": "An agent framework", "stargazers_count": 80, "created_at": "2026-10-05T00:00:00Z"}]}
        )
        self.assertEqual(repos[0].metadata["stars"], 80)
        stories = stories_from_payload(
            {"hits": [{"title": "New model", "url": "https://example.com/m", "points": 90, "objectID": "5", "author": "ada", "created_at": "2026-10-05T00:00:00Z"}]}
        )
        self.assertIn("Hacker News points: 90", stories[0].excerpt)
        arxiv = build_arxiv_url({"url": "https://export.arxiv.org/api/query", "search_query": "cat:cs.AI", "max_results": 3})
        self.assertIn("search_query=cat%3Acs.AI", arxiv)


class FilterTests(unittest.TestCase):
    def test_drops_duplicates_and_low_value_items(self):
        config = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        items = [
            sample_item(),
            sample_item(url="https://example.com/blog/sampleforge-2?utm_source=newsletter"),
            sample_item(title="Sample Lab is hiring", url="https://example.com/jobs", excerpt="We are hiring engineers."),
            sample_item(
                source_id="hackernews",
                source_name="Hacker News",
                title="Lunch menus",
                url="https://example.com/lunch",
                excerpt="A long note about lunch menus at the office cafeteria today.",
                metadata={"priority": 10, "require_ai_terms": True},
            ),
        ]
        outcome = prepare_items(items, config, now=NOW, apply_window=True)
        self.assertEqual(len(outcome.kept), 1)
        self.assertEqual(outcome.duplicates, 1)
        self.assertEqual(outcome.low_value, 2)

    def test_drops_tips_and_keeps_a_real_release(self):
        config = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        items = [
            sample_item(title="How to prompt a chatbot", url="https://example.com/howto", excerpt="How to write better prompts for everyday email."),
            sample_item(
                source_id="openai",
                source_name="OpenAI News",
                title="A note on policy trends",
                url="https://example.com/policy",
                excerpt="A general essay about the policy conversation around AI this year.",
            ),
            sample_item(),
        ]
        outcome = prepare_items(items, config, now=NOW, apply_window=True)
        self.assertEqual([item.title for item in outcome.kept], ["Sample Lab releases SampleForge 2"])

    def test_email_covers_each_technology_area(self):
        model = sample_item(title="Lab releases Sample Model", url="https://example.com/model", metadata={"priority": 90})
        framework = sample_item(
            source_id="github-releases",
            source_name="GitHub Releases",
            title="transformers 5.0.0",
            url="https://example.com/transformers",
            excerpt="The transformers 5.0.0 release adds a training framework.",
            metadata={"priority": 40, "release": "v5.0.0", "repo": "huggingface/transformers"},
        )
        second_model = sample_item(title="Lab releases Sample Model Two", url="https://example.com/model-2", excerpt="The lab introduced another language model.", metadata={"priority": 80})
        selected = select_balanced([model, second_model, framework], 2)
        self.assertEqual(classify(model), "model")
        self.assertEqual(classify(framework), "framework")
        self.assertEqual({classify(item) for item in selected}, {"model", "framework"})


class EmailTests(unittest.TestCase):
    def test_subject_and_body_skip_empty_fields(self):
        self.assertEqual(email_subject(), "What's new today")
        item = sample_item()
        analysis = Analysis(
            relevant=True,
            what_was_introduced="SampleForge 2",
            who_introduced_it="A. Example",
            what_it_does="It is a 7B language model.",
            why_it_matters="Not stated in source.",
            technology="PyTorch",
            factual_data="Not stated in source.",
            use_cases=[],
            method="extractive",
        )
        item.metadata["category"] = "model"
        text = render_email_text([ReportEntry(item, analysis)], generated_at=NOW)
        self.assertIn("What's new today", text)
        self.assertIn("Model: Sample Lab releases SampleForge 2", text)
        self.assertIn("https://example.com/blog/sampleforge-2", text)
        self.assertNotIn("Not stated in source.", text)
        self.assertNotIn("Summary method", text)
        self.assertNotIn("Run notes", text)
        empty = render_email_text([], generated_at=NOW)
        self.assertIn("There are no updates today.", empty)


class GroundingTests(unittest.TestCase):
    def test_unknown_numbers_are_removed(self):
        item = sample_item()
        analysis = Analysis(
            relevant=True,
            what_was_introduced="SampleForge 2",
            who_introduced_it="A. Example",
            what_it_does="It is a 7B model. It has 999 made-up scores.",
            why_it_matters="Not stated in source.",
            technology="PyTorch",
            factual_data="The hidden benchmark is 999.",
            use_cases=["Summarize 4000 documents."],
            method="ollama:test",
        )
        grounded = ground_analysis(analysis, item)
        self.assertEqual(grounded.what_it_does, "It is a 7B model.")
        self.assertEqual(grounded.factual_data, "Not stated in source.")
        self.assertEqual(grounded.use_cases, [])
        self.assertNotIn("999", grounded.what_was_introduced)

    def test_extractive_summary_stays_inside_source(self):
        item = sample_item(
            excerpt="Sample Lab introduced SampleForge 2, a 7B open-weight language model. It runs locally with Ollama and PyTorch. Developers can use it for document summarization."
        )
        analysis = extractive_analysis(item)
        self.assertEqual(analysis.who_introduced_it, "A. Example")
        self.assertIn("Ollama", analysis.technology)
        self.assertIn("document summarization", " ".join(analysis.use_cases))
        self.assertNotIn("999", analysis.factual_data)

    def test_model_json_parser(self):
        payload = parse_model_json('```json\n{"relevant": false, "what_was_introduced": "X"}\n```')
        analysis = analysis_from_payload(payload, "ollama:llama3.2")
        self.assertFalse(analysis.relevant)
        self.assertEqual(analysis.what_was_introduced, "X")


class DeliveryTests(unittest.TestCase):
    def test_daily_slot_is_eight_am_ist(self):
        before = datetime(2026, 10, 5, 7, 30, tzinfo=IST)
        after = datetime(2026, 10, 5, 8, 5, tzinfo=IST)
        self.assertEqual(next_run(before).strftime("%Y-%m-%d %H:%M %z"), "2026-10-05 08:00 +0530")
        self.assertEqual(next_run(after).strftime("%Y-%m-%d %H:%M %z"), "2026-10-06 08:00 +0530")
        utc = next_run(before).astimezone(timezone.utc)
        self.assertEqual(utc.strftime("%H:%M"), "02:30")

    def test_cloud_run_can_skip_ollama(self):
        previous = os.environ.get("OLLAMA_ENABLED")
        os.environ["OLLAMA_ENABLED"] = "false"
        try:
            config = load_config(PROJECT_ROOT / "config.json")
            self.assertFalse(config["ollama"]["enabled"])
        finally:
            if previous is None:
                os.environ.pop("OLLAMA_ENABLED", None)
            else:
                os.environ["OLLAMA_ENABLED"] = previous

    def test_recipient_is_configured(self):
        config = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["email"]["to"], "saisoumya.dolly@gmail.com")
        self.assertEqual(config["email"]["smtp_from"], "saisoumya.dolly@gmail.com")
        self.assertEqual(config["schedule_time"], "08:00")
        self.assertEqual(config["schedule_timezone"], "Asia/Kolkata")
        self.assertTrue(config["email"]["enabled"])

    def test_send_requires_app_password(self):
        previous = os.environ.pop("SMTP_PASSWORD", None)
        try:
            config = {
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp.gmail.com",
                    "smtp_user": "saisoumya.dolly@gmail.com",
                    "to": "saisoumya.dolly@gmail.com",
                }
            }
            ready, reason = can_send(config)
            self.assertFalse(ready)
            self.assertIn("SMTP_PASSWORD", reason)
            self.assertIn("saisoumya.dolly@gmail.com", reason)
        finally:
            if previous is not None:
                os.environ["SMTP_PASSWORD"] = previous

    def test_gmail_app_password_must_be_sixteen_characters(self):
        previous = os.environ.get("SMTP_PASSWORD")
        os.environ["SMTP_PASSWORD"] = "short"
        try:
            config = {
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp.gmail.com",
                    "smtp_user": "saisoumya.dolly@gmail.com",
                    "to": "saisoumya.dolly@gmail.com",
                }
            }
            ready, reason = can_send(config)
            self.assertFalse(ready)
            self.assertIn("16 letters", reason)
        finally:
            if previous is None:
                os.environ.pop("SMTP_PASSWORD", None)
            else:
                os.environ["SMTP_PASSWORD"] = previous


class StoreTests(unittest.TestCase):
    def test_seen_round_trip(self):
        store = Store(":memory:")
        self.assertFalse(store.is_seen("https://example.com/a", "title"))
        store.mark("https://example.com/a", "title", "https://example.com/a", "Title", "reported")
        self.assertTrue(store.is_seen("https://example.com/other", "title"))
        store.close()


class PipelineTests(unittest.TestCase):
    def test_offline_run_writes_a_grounded_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(PROJECT_ROOT / "config.json")
            config["_root"] = str(root)
            config["email"]["enabled"] = False
            result = run_pipeline(config, offline=True, send_email=False, fresh=True, now=NOW)
            self.assertTrue(result.ok, result.message)
            self.assertIsNotNone(result.markdown_path)
            text = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("Sample Lab releases SampleForge 2", text)
            self.assertIn("Routing Agents with Small Verifiers", text)
            self.assertIn("vllm 0.9.0", text)
            self.assertIn("https://example.com/blog/sampleforge-2", text)
            self.assertIn("https://github.com/vllm-project/vllm/releases/tag/v0.9.0", text)
            self.assertNotIn("hiring research engineers", text)
            self.assertNotIn("My thoughts on AGI", text)
            self.assertNotIn("utm_source", text)
            for label in (
                "What was introduced",
                "Who introduced it",
                "What it does",
                "Why it matters",
                "Technology / framework / model",
                "Factual data",
                "Potential real-world use cases",
                "Original source",
            ):
                self.assertIn(label, text)
            self.assertEqual(result.stats.reported, 3)
            self.assertTrue(result.html_path.exists())


if __name__ == "__main__":
    unittest.main()
