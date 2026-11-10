# Selenite and Check Yourself: where each one stops

TLDR: Check Yourself asks **"is this claim of done true?"** Selenite asks **"does this step, wait or check earn its cost to the person?"** One judges the truth of a result, the other the cost of the process. They meet in one place, the cost of verification itself, and this file draws the line there so the two never rule on the same question.

Compared against Check Yourself's Hermes plugin at `d421e421` (`hermes-plugin/`) and Selenite at `main`.

## The split

| Question | Owner | Not the other's job because |
|---|---|---|
| Is a completion claim backed by executed evidence? | Check Yourself | Selenite never scores evidence or blocks a completion. |
| Is an app ready to ship (findings register, risk score, fix backlog)? | Check Yourself | Selenite ranks friction in the agent stack, not defects in the product. |
| Is a step handed to a person needed, or can it shrink to one command? | Selenite (Gate) | Check Yourself doesn't measure the person's effort. |
| Is an agent parking work on another agent for a reason that isn't real? | Selenite (fake gates) | Check Yourself gates `kanban_complete` only. |
| Can a check change the decision, does it apply to every option, is it priced to the stakes? | Selenite (pedantry) | Check Yourself asks whether its own evidence is present, not whether a check is worth running. |

## Where they touch, and the rule for each

1. **Hooks.** Both register `pre_tool_call`. Check Yourself acts only on `kanban_complete` and fails closed. Selenite acts only on `kanban_block` and fails open. The tool sets are disjoint, so neither hook sees the other's call. A test holds Selenite to `kanban_block` only.
2. **A card blocked because evidence is missing.** When Check Yourself refuses a completion and the agent blocks the card ("tests not run yet, need executed coverage receipt"), the wait is real. Selenite's classifier gives such text the unevidenced F6 fallback at 0.3, below `min_confidence`, so it records but never nudges or asks. A test holds that.
3. **Ceremony around evidence.** "Need a reviewer agent to attest the evidence bundle" is F4 ceremony (0.7) and is nudged. That is the intended line: Check Yourself's executed receipts are the evidence; a second agent's sign-off on them adds a wait, not proof.
4. **Pedantry about Check Yourself's own gate.** Selenite's pedantry facet may ask whether a gate is priced to the stakes. It does not rule on whether Check Yourself's evidence is sufficient; that is Check Yourself's question. Selenite's verdict on a check is advice in a report, never a hook action.
5. **Friction from a refused completion.** A refusal lands on the agent, not the person, so it isn't Selenite's to count. It becomes Selenite's only when the card sits blocked and a person has to untangle the board; then the fake-gate facet and Cleanse see it like any other blocked card.
6. **"Gate".** Selenite's **Gate mode** means a step handed to a person. Check Yourself's **Evidence Gate** means a completion check. In copy and demos, Selenite says "human step" when both products are in view.

## Left for Check Yourself's owner

These sit on Check Yourself's side of the line, so Selenite doesn't change them:

- Its gate covers the `kanban_complete` tool only (its own known issue). A completion through another path skips it. Selenite's pedantry test calls that asymmetric scrutiny (P2): one path pays the full check, another pays none.
- The 25-second hook timeout runs on every completion. Whether that is priced to a reversible, private board move is a proportionality question for its owner, using the evidence of how often it blocks.
- Challenge commands may write files or use the network after an operator opt-in. That opt-in is a step handed to a person; making it one-time per project keeps it a wall without repeating it.
