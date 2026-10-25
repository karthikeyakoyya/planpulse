# Automation and AI ideas

What PlanPulse already does, and what I would try next. Nothing in the "next" list is built, and the model-driven parts (summary draft, `ask`) have not been run against the live API. All data here is simulated, so none of this has been tried on real planning data.

## Already in the repo
- Weekly run on a schedule (`.github/workflows/weekly.yml`, written but not yet run on GitHub).
- Isolation Forest flags SKUs that no rule catches (decision D12).
- One-week-ahead baseline forecast scored against the system forecast, a 4-week moving average and a naive forecast (D11, D21).
- `ask` command: a model can call only the saved read-only queries (a tool-use loop), its numbers are checked against the rows it saw, and a keyword router answers when there is no API key (D22).
- Drafted weekly summary: facts come from SQL, a model (or a template when there is no API key) writes the text, a number check compares it to the facts, and a person approves it before it reaches the Word note or deck (D13).

## Ideas to try next
1. **Meeting notes to actions.** Let a model read free-form notes and propose `- ACTION:` lines for a person to accept. The current import only reads lines already in that format.
2. **Supplier chase drafts.** For each late PO, draft a short follow-up note for Procurement to edit and send. Needs a rule for who owns the send.
3. **Wider assistant tools.** `ask` only reads the saved queries. It could also read the glossary and decision log so it can explain a threshold, still without any write access.
4. **Exception triage.** Rank P2 and P3 exceptions by value at risk so the first review hour goes to the biggest ones. Needs unit cost and demand value per SKU, which the simulated data has but real extracts may not.
5. **Owner matching.** Map roles to named people once the team agrees who they are (D14).

## What would stop me
- No real data access, so thresholds (D05, D09, D10) are generic.
- Anything that sends a message to a supplier or a market should stay behind a person's approval, the same as the weekly summary.
