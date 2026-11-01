import io
import json
import math
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from solrdm_pi.memory import MemoryStore
from solrdm_pi.tools import TOOL_DEFINITIONS, ToolError, execute_tool, fetch_research_json, _NoRedirect


class ToolTests(unittest.TestCase):
    def test_calculator_real_functions_and_precedence(self):
        self.assertAlmostEqual(execute_tool("calculate", {"expression": "sqrt(81) + sin(pi/2) * 2**3"})["data"]["result"], 17)
        self.assertEqual(execute_tool("calculate", {"expression": "-2**2 + abs(-7) % 3"})["data"]["result"], -3)
        self.assertAlmostEqual(execute_tool("calculate", {"expression": "log(e) + log10(100)"})["data"]["result"], 3)

    def test_calculator_rejects_code_and_resource_exhaustion(self):
        rejected = ["__import__('os').system('whoami')", "(1).__class__", "[x for x in range(10)]",
            "True", "'text'", "2**10000000", "9**9**9", "1e999", "1/0", "sqrt(-1)",
            "(-1)**0.5", "log(0)", "exp(10000)", "sin(x=1)", "1<<100000", "max(1,2)", "sin(1,2)",
            "sin(" * 18 + "1" + ")" * 18, "1+" * 60 + "1"]
        for expression in rejected:
            with self.subTest(expression=expression), self.assertRaises(ToolError):
                execute_tool("calculate", {"expression": expression})

    def test_statistics_known_values_singleton_and_large_values(self):
        data = execute_tool("describe_statistics", {"numbers": [1, 2, 3, 4]})["data"]
        self.assertEqual(data["mean"], 2.5)
        self.assertEqual(data["median"], 2.5)
        self.assertAlmostEqual(data["populationStandardDeviation"], math.sqrt(1.25))
        self.assertAlmostEqual(data["sampleStandardDeviation"], math.sqrt(5 / 3))
        self.assertIsNone(execute_tool("describe_statistics", {"numbers": [8]})["data"]["sampleStandardDeviation"])
        self.assertTrue(math.isfinite(execute_tool("describe_statistics", {"numbers": [-1e100, 1e100]})["data"]["sampleStandardDeviation"]))

    def test_projectile_matches_closed_form_and_edge_cases(self):
        result = execute_tool("simulate_projectile", {"speed": 10, "angle": 45, "gravity": 10})
        self.assertAlmostEqual(result["data"]["range"], 10)
        self.assertAlmostEqual(result["data"]["maxHeight"], 2.5)
        self.assertEqual(len(result["data"]["points"]), 200)
        self.assertEqual(result["data"]["points"][-1]["y"], 0)
        vertical = execute_tool("simulate_projectile", {"speed": 10, "angle": 90, "gravity": 10})
        self.assertEqual(vertical["data"]["range"], 0)
        zero = execute_tool("simulate_projectile", {"speed": 0, "angle": 45, "gravity": 10})
        self.assertEqual(zero["data"]["points"], [{"t": 0, "x": 0, "y": 0}])

    def test_oscillator_initial_conditions_energy_and_damping_regimes(self):
        for damping, regime in ((0, "undamped"), (1, "underdamped"), (2, "critically damped"), (3, "overdamped")):
            with self.subTest(regime=regime):
                data = execute_tool("simulate_oscillator", {"mass": 1, "spring": 1, "damping": damping, "x0": 2, "v0": 0.5, "duration": 10})["data"]
                self.assertEqual(data["regime"], regime)
                self.assertEqual(data["points"][0]["x"], 2)
                self.assertEqual(data["points"][0]["v"], 0.5)
                self.assertEqual(len(data["points"]), 501)
                if damping == 0:
                    self.assertTrue(all(abs(p["energy"] - data["initialEnergy"]) < 1e-10 for p in data["points"]))
                else:
                    self.assertLess(data["finalEnergy"], data["initialEnergy"])
                    self.assertTrue(all(b["energy"] <= a["energy"] + 1e-10 for a, b in zip(data["points"], data["points"][1:])))

    def test_oscillator_strong_damping_stays_finite_and_warns_sampling(self):
        data = execute_tool("simulate_oscillator", {"mass": 0.001, "spring": 0.001, "damping": 1000000, "x0": 1, "v0": 1, "duration": 3600})["data"]
        self.assertTrue(all(math.isfinite(p["x"]) and math.isfinite(p["energy"]) for p in data["points"]))
        sampled = execute_tool("simulate_oscillator", {"mass": 1, "spring": 1000000, "damping": 0, "x0": 1, "v0": 0, "duration": 3600})["data"]
        self.assertIsNotNone(sampled["resolutionWarning"])

    def test_arguments_are_strict_and_finite(self):
        bad = [("unknown", {}), ("calculate", {"expression": "1+1", "path": "/tmp"}),
            ("describe_statistics", {"numbers": []}), ("describe_statistics", {"numbers": [True]}),
            ("describe_statistics", {"numbers": [float("nan")]}), ("describe_statistics", {"numbers": [1] * 1001}),
            ("simulate_projectile", {"speed": 1, "angle": 45, "gravity": 0}),
            ("simulate_projectile", {"speed": True, "angle": 45, "gravity": 10}),
            ("research_papers", {"query": "\nnot allowed"})]
        for name, args in bad:
            with self.subTest(name=name, args=str(args)[:60]), self.assertRaises(ToolError):
                execute_tool(name, args)

    def test_paper_search_encodes_query_and_preserves_evidence_limits(self):
        urls = []
        def fetch(url):
            urls.append(url)
            return {"message": {"items": [{"DOI": "10.1234/example", "title": ["<b>Test &amp; study</b>"],
                "author": [{"given": "Ada", "family": "Lovelace"}], "published": {"date-parts": [[2024]]},
                "abstract": "<jats:p>Evidence</jats:p>"}, {"DOI": "javascript:alert(1)", "title": []}]}}
        receipt = execute_tool("research_papers", {"query": "x & rows=1000"}, fetch_json=fetch)
        query = parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(query["query.bibliographic"], ["x & rows=1000"])
        self.assertEqual(query["rows"], ["5"])
        self.assertEqual(receipt["data"]["papers"][0]["title"], "Test & study")
        self.assertEqual(receipt["data"]["papers"][0]["abstract"], "Evidence")
        self.assertIsNone(receipt["data"]["papers"][1]["url"])
        self.assertIn("Full papers have not been read", receipt["summary"])
        self.assertEqual(receipt["sources"][1]["url"], "https://doi.org/10.1234/example")

    def test_wikipedia_search_bounded_and_links_only_valid_page_ids(self):
        items = [{"title": "<b>Physics</b>", "pageid": 42, "snippet": "Some <span>physics</span>."},
            {"title": "Bad", "pageid": True, "snippet": "No"}]
        receipt = execute_tool("search_encyclopedia", {"query": "physics"}, fetch_json=lambda url: {"query": {"search": items}})
        self.assertEqual(len(receipt["data"]["articles"]), 1)
        self.assertEqual(receipt["sources"], [{"title": "Physics", "url": "https://en.wikipedia.org/?curid=42"}])
        self.assertEqual(receipt["data"]["articles"][0]["snippet"], "Some physics .")
        for name in ("research_papers", "search_encyclopedia"):
            for response in ([], {}, {"message": None}, {"query": {"search": "bad"}}):
                with self.subTest(name=name, response=response), self.assertRaises(ToolError):
                    execute_tool(name, {"query": "x"}, fetch_json=lambda url, r=response: r)

    def test_model_memory_cannot_approve_and_status_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = MemoryStore(directory)
            result = execute_tool("remember_observation", {"text": "Sample is warm", "source": "conversation"}, memory=memory)
            self.assertEqual(result["data"]["status"], "unreviewed")
            self.assertEqual(result["data"]["origin"], "model")
            found = execute_tool("recall_observations", {"query": "warm"}, memory=memory)
            self.assertEqual(found["data"]["observations"][0]["status"], "unreviewed")
            with self.assertRaises(ToolError):
                execute_tool("remember_observation", {"text": "x", "source": "x", "approved": True}, memory=memory)
            with self.assertRaises(ToolError):
                execute_tool("review_observation", {"id": 1, "approved": True}, memory=memory)

    def test_schemas_have_unique_names_and_explicit_required_fields(self):
        names = []
        for definition in TOOL_DEFINITIONS:
            schema = definition["function"]
            names.append(schema["name"])
            self.assertEqual(set(schema["parameters"]["required"]), set(schema["parameters"]["properties"]))
            self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(len(names), len(set(names)))

    def test_network_fetch_rejects_user_urls_redirects_and_large_bodies(self):
        for url in ("http://api.crossref.org/works", "https://localhost/works", "https://api.crossref.org@127.0.0.1/works", "https://api.crossref.org/other"):
            with self.subTest(url=url), self.assertRaises(ToolError):
                fetch_research_json(url)
        with self.assertRaises(ToolError):
            _NoRedirect().redirect_request(None, None, 302, "", {}, "https://127.0.0.1")
        class Response(io.BytesIO):
            headers = {}
        class Opener:
            def __init__(self, body): self.body = body
            def open(self, request, timeout): return Response(self.body)
        with patch("solrdm_pi.tools.build_opener", return_value=Opener(b"x" * (256 * 1024 + 1))):
            with self.assertRaisesRegex(ToolError, "too much"):
                fetch_research_json("https://api.crossref.org/works")
        with patch("solrdm_pi.tools.build_opener", return_value=Opener(b'{"ok":true}')):
            self.assertEqual(fetch_research_json("https://api.crossref.org/works"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
