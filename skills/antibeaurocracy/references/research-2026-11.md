# What the field knows (as of 2026-11-10)

A common thread in the sources below: approval is valuable where the human's answer changes the outcome, and beyond that point routine gates tend to train people to click yes. The evidence is grouped by question. arXiv entries were checked against their abstracts on 2026-11-10; claims we could not verify against a primary source are marked.

## 1. Approval fatigue is a governance failure, not a safety feature

- **Gate fatigue.** When approvals become routine, people approve without reading, and the gate stops meaning anything. The recommended fix is to gate only actions where a human decision changes the result, and to track approval volume as a governance metric. Sources: fullstack.com, "Gate fatigue: when human approval stops meaning anything"; WorkOS, "Approval fatigue and agent governance".
- **Tiered governance.** Sort actions by reversibility and blast radius, auto-approve the low tiers, and reserve human review for the irreversible tier. This is common practice guidance, and secondary sources attribute it to Gartner (*not verified against the Gartner primary*).
- **An approval is only a boundary if it binds to the action.** "Loopjacking" (arXiv 2609.21081) shows tested agent frameworks where the operation a human approved was later swapped for a different one. The paper is about binding, not fatigue, but it supports the same design point: a few gates that show exactly what will run beat many gates that don't.
- **Industry direction.** Claude Code's auto mode replaces per-action prompts with a classifier that gates only risky actions (anthropic.com/engineering/claude-code-auto-mode). A widely repeated figure says ~93% of permission prompts were approved before auto mode (*secondary sources; not verified*).
- **Human-in-the-loop design.** changkun.de, "Human-in-the-loop agents", and neuraltrust.ai, "Human in the loop AI agents", both argue that the loop should sit at decision points, not at every step.

## 2. Agents over-ask, and late questions are the worst kind

- **HiL-Bench** (arXiv 2604.09408) scores agents on asking only about real blockers (precision) while not missing them (recall), so question spam scores badly. Frontier models show a large gap: some over-ask broadly, others guess silently. **AskBench** (arXiv 2602.11199) evaluates when and what an LLM should ask, without giving up task performance. Neither paper is about agent-to-agent waits; we use them only for the narrower point that good asking is selective.
- The F1-ack check borrows that idea: if the answer wouldn't change what you do, don't wait for it.

## 3. Multi-agent organizations rebuild human bureaucracy

- **MAST**, the multi-agent system failure taxonomy (arXiv 2503.13657), groups multi-agent failures into three families: specification and system design, inter-agent misalignment, and task verification. Its authors argue many failures come from how the system is organised, not only from model limits. Relays, ownership limbo and ceremony are our names for organisational failures of that kind.
- **Coordinator overhead.** Secondary reporting puts orchestrator coordination at 50–100 LLM calls per task (*not verified against a primary*). Practitioner guidance from Shopify engineering (via secondary reporting) is to avoid multi-agent setups early (*secondary*).
- **Singapore Consensus on AI safety research priorities.** Our paraphrase: as agents prove reliable, relax approval requirements rather than accumulate them (*not checked against the primary text*).

## 4. The Hermes-specific angle

Hermes kanban gives agents `kanban_block` and `initial_status=blocked`, but no built-in check that a block is a real wall. The kanban docs and the kanban-empowered plugin docs (hermes-agent.nousresearch.com) describe the blocked, triage and dependency lifecycles. The `pre_tool_call` hook can veto or annotate a block before it lands, which is where this plugin sits.

## Coverage note

This stage used web search. X was covered through search-engine indexing rather than the X API, which catches widely indexed posts but not the long tail.

## X (Twitter) discourse, as of 2026-11-10

These came through search-engine snippets of x.com posts that we could not open (x.com needs a login). They are paraphrased, not quoted, and **unverified**: treat them as practitioner anecdotes, not studies.

- **Agents invent permission they don't need** (unverified). A practitioner running a long-lived agent swarm reported an agent deciding it needed the operator's permission to message other agents, when it did not. That is F1 (an ACK request for in-scope work) in someone else's setup. [x.com/unclebobmartin/status/2056029200633524490](https://x.com/unclebobmartin/status/2056029200633524490)
- **Human-in-the-loop as a volume problem** (unverified). A researcher argued that current agent designs ask people to review more, and more complex, output than they can keep up with, which wears down their attention. [x.com/math_rachel/status/2111238648188584306](https://x.com/math_rachel/status/2111238648188584306)
- **Kanban "Blocked" means nothing runs until a human acts** (unverified). Hermes Kanban explainers describe Blocked as the human-flag state, which is exactly why a fake block is expensive: the card stops dispatching. [x.com/akshay_pachaar/article/2062526843564233040](https://x.com/akshay_pachaar/article/2062526843564233040)
- **The common fix is scoping, not switching gates off** (unverified). Practitioners converge on letting reads and routine messaging run freely, gating writes, deletes and publishing, and allowlisting per job, rather than disabling approvals globally. [x.com/cathrynlavery/status/2039368181475635650](https://x.com/cathrynlavery/status/2039368181475635650)
- **Delegated review** (unverified). A post on agent autonomy levels describes a coding agent mode that hands boundary approvals to a separate reviewer agent. [x.com/addyosmani/article/2072885435312042327](https://x.com/addyosmani/article/2072885435312042327)

A fuller X pass would need paid API access.
