import queue
import time
import unittest

from tiered_agent.arms.lookup import LookupArm
from tiered_agent.arms.packs import PackArm
from tiered_agent.arms.qa import QAArm
from tiered_agent.async_bridge import Delivery, SpecialistAgent
from tiered_agent.guard import Guard
from tiered_agent.llm import MockLLM
from tiered_agent.orchestrator import Orchestrator
from tiered_agent.planner import KINDS, keyword_prior, make_plan


class BrokenLLM:
    def complete(self, system, user):
        raise RuntimeError("down")


class GarbageLLM:
    def complete(self, system, user):
        return "no json here"


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g = Guard()

    def test_drops_sensitive_column(self):
        t = "| category | cpm | spend share |\n|---|---|---|\n| Home | 11 | 40% |"
        out, hits = self.g.redact(t)
        self.assertNotIn("share", out.lower())
        self.assertIn("cpm", out)
        self.assertIn("table:columns", hits)

    def test_drops_roster_table(self):
        out, hits = self.g.redact("| advertiser | spend |\n|---|---|\n| X | 5 |")
        self.assertEqual(out, "")
        self.assertIn("table:roster", hits)

    def test_drops_share_sentence_with_long_gap(self):
        out, _ = self.g.redact("Keep this. The market share of the leading vendor is 31%.")
        self.assertEqual(out, "Keep this.")

    def test_fail_closed_when_nothing_left(self):
        out, hits = self.g.process("The market share of the leading vendor is 31%.")
        self.assertEqual(out, self.g.refusal)
        self.assertIn("residual", hits)

    def test_fail_closed_on_error(self):
        out, hits = self.g.process(None)
        self.assertEqual(out, self.g.refusal)
        self.assertEqual(hits, ["error"])

    def test_clean_text_passes(self):
        out, hits = self.g.process("CPM is 12.4 for feed.")
        self.assertEqual(out, "CPM is 12.4 for feed.")
        self.assertEqual(hits, [])


class PlannerTests(unittest.TestCase):
    def test_model_plan_is_used(self):
        p = make_plan(MockLLM(), "What are the CPM benchmarks for Home?")
        self.assertEqual(p.source, "llm")
        self.assertIn("lookup", p.kinds)

    def test_whitelist_and_dedupe(self):
        class L:
            def complete(self, s, u):
                return ('{"intents":[{"kind":"qa"},{"kind":"qa"},{"kind":"shell"},{"kind":"lookup"},'
                        '"junk"]}')
        p = make_plan(L(), "x")
        self.assertEqual(p.kinds, ["qa", "lookup"])
        self.assertTrue(set(p.kinds) <= set(KINDS))

    def test_fallback_on_error_and_garbage(self):
        for llm in (BrokenLLM(), GarbageLLM()):
            p = make_plan(llm, "keyword terms for hiking boots")
            self.assertEqual(p.source, "prior")
            self.assertEqual(p.kinds, keyword_prior("keyword terms for hiking boots"))


class LookupTests(unittest.TestCase):
    def test_l1_exact_category(self):
        r = LookupArm(MockLLM()).run("CPM for Apparel on feed")
        self.assertEqual(r.meta["level"], "L1")
        self.assertIn("Apparel", r.text)
        self.assertNotIn("spend_share", r.text)

    def test_l2_fuzzy_category(self):
        r = LookupArm(MockLLM()).run("CPM for Electronic goods")
        self.assertEqual(r.meta["level"], "L2")
        self.assertIn("Electronics", r.text)

    def test_unknown_lists_categories(self):
        r = LookupArm(BrokenLLM()).run("CPM for Spaceships")
        self.assertEqual(r.meta["level"], "none")


class PackTests(unittest.TestCase):
    def test_l0_exact(self):
        r = PackArm(MockLLM()).run("terms for hiking boots")
        self.assertEqual(r.meta["level"], "L0")

    def test_l2_clarify_when_model_fails(self):
        r = PackArm(BrokenLLM()).run("something vague")
        self.assertEqual(r.meta["level"], "L2-clarify")
        self.assertIn("Footwear/Hiking", r.text)


class QATests(unittest.TestCase):
    def test_hit_has_source(self):
        r = QAArm().run("return policy for unused items")
        self.assertEqual(r.sources, ["returns.md"])

    def test_miss(self):
        self.assertEqual(QAArm().run("zzz qqq").meta["hits"], 0)


class DeliveryTests(unittest.TestCase):
    def make(self, llm=None, clock=time.monotonic):
        return Delivery(llm or MockLLM(), Guard(), 10.0, clock)

    def test_fused_once_then_late_update(self):
        d = self.make()
        d.hold_draft("r", "draft text")
        d.on_external("r", "answer one")
        d.on_external("r", "answer two")
        kinds = [d.outbox.get_nowait().kind, d.outbox.get_nowait().kind]
        self.assertEqual(kinds, ["fused", "late_update"])

    def test_timeout_sends_draft_once(self):
        now = [0.0]
        d = self.make(clock=lambda: now[0])
        d.hold_draft("r", "draft text")
        self.assertEqual(d.flush_expired(), 0)
        now[0] = 11.0
        self.assertEqual(d.flush_expired(), 1)
        self.assertEqual(d.flush_expired(), 0)
        self.assertEqual(d.outbox.get_nowait().kind, "draft_timeout")

    def test_rewriter_output_is_guarded(self):
        class Leaky:
            def complete(self, s, u):
                return "Fine. The spend share of the top vendor is 40%."
        d = self.make(llm=Leaky())
        d.hold_draft("r", "draft")
        d.on_external("r", "ext")
        self.assertEqual(d.outbox.get_nowait().text, "Fine.")

    def test_rewriter_failure_falls_back_to_draft(self):
        d = self.make(llm=BrokenLLM())
        d.hold_draft("r", "draft text")
        d.on_external("r", "ext")
        self.assertEqual(d.outbox.get_nowait().text, "draft text")


class EndToEndTests(unittest.TestCase):
    def test_sync_question(self):
        r = Orchestrator().handle("What is the return policy for unused items?")
        self.assertIsNone(r.ref)
        self.assertIn("returns.md", r.text)
        self.assertEqual(r.trace[-1]["step"], "guard")

    def test_external_question_receipt_then_fused(self):
        o = Orchestrator(specialist=SpecialistAgent(delay_s=0.05))
        r = o.handle("What are the CPM benchmarks for Home and how should we plan the budget?")
        self.assertIsNotNone(r.ref)
        self.assertIn(r.ref, r.text)
        msg = o.delivery.outbox.get(timeout=5)
        self.assertEqual((msg.ref, msg.kind), (r.ref, "fused"))
        self.assertNotIn("31%", msg.text)
        self.assertIn("Recommended plan", msg.text)

    def test_specialist_down_then_draft_timeout(self):
        class Down(SpecialistAgent):
            def run(self, q, c):
                raise RuntimeError("down")
        o = Orchestrator(specialist=Down(), draft_deadline_s=0.0)
        r = o.handle("CPM for Home and how should we plan the budget?")
        time.sleep(0.1)
        self.assertEqual(o.delivery.flush_expired(), 1)
        self.assertEqual(o.delivery.outbox.get(timeout=1).kind, "draft_timeout")
        with self.assertRaises(queue.Empty):
            o.delivery.outbox.get(timeout=0.2)


if __name__ == "__main__":
    unittest.main()
