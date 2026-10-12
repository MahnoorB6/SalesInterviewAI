"""Single source of truth for behavioral competencies, weights, and score anchors."""

from dataclasses import dataclass


RUBRIC_VERSION = "sales_behavioral_1.0"
EVALUATOR_VERSION = "behavioral_rubric_engine_1.0"
EVALUATION_METHOD = "behavioral_rubric_v1"
PASS_SCORE = None  # Automated evaluation does not make a hiring decision.
RATING_RATIO_THRESHOLDS = {5: 0.90, 4: 0.65, 3: 0.35}


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    demonstrated: tuple[str, ...]
    partial: tuple[str, ...] = ()


@dataclass(frozen=True)
class Competency:
    key: str
    label: str
    weight: int
    criteria: tuple[Criterion, ...]
    anchors: dict[int, str]


def _anchors(label: str, low: str, emerging: str, effective: str, strong: str) -> dict[int, str]:
    return {
        1: f"{label}: {low}",
        2: f"{label}: {emerging}",
        3: f"{label}: demonstrates a relevant, usable approach; {effective}",
        4: f"{label}: applies a specific, customer-aware approach; {strong}",
        5: f"{label}: consistently demonstrates the full behavior; {strong} and verifies the outcome or next step.",
    }


COMPETENCIES: tuple[Competency, ...] = (
    Competency("communication", "Communication", 15, (
        Criterion("direct_answer", "answers the question directly", (r"\b(?:I|we|my approach|the first thing)\s+(?:would|did|do|start|began|asked|used|handled|focused)\b",)),
        Criterion("organized_ideas", "organizes ideas clearly", (r"\bfirst\b.{0,240}\b(?:then|next|after that|finally)\b",), (r"\b(?:first|second|then|finally)\b",)),
        Criterion("explains_reasoning", "explains reasoning", (r"\b(?:because|so that|the reason (?:I|we)|which meant)\b",)),
        Criterion("relevance", "stays relevant to the situation", (r"\b(?:in that situation|for that customer|in this case|based on what (?:they|the customer) needed)\b",)),
        Criterion("adapts_explanation", "adapts the explanation to context", (r"\b(?:tailor|adapt|adjust|change)\w*\b.{0,100}\b(?:customer|prospect|audience|their needs|situation)\b",)),
        Criterion("listens_and_responds", "responds to what the customer said", (r"\b(?:you mentioned|they told me|the customer said|I listened|I paraphrased|I reflected back|I asked them)\b",)),
        Criterion("professional", "communicates respectfully and transparently", (r"\b(?:I was transparent|I explained the limitation|I acknowledged|I appreciate|I understand why)\b",)),
    ), _anchors("Communication", "does not answer the prompt or provide a relevant response", "responds but ideas are hard to follow or reasoning is absent", "the answer is understandable and stays on topic", "the answer is organized, reasoned, relevant, and adapted to the customer's context")),
    Competency("confidence", "Confidence", 10, (
        Criterion("ownership", "takes ownership of personal actions", (r"\bI\s+(?:personally\s+)?(?:led|owned|decided|asked|recommended|changed|followed up|handled|learned|took responsibility)\b",)),
        Criterion("decision_clarity", "explains decisions clearly", (r"\bI (?:chose|decided|recommended|prioritized)\b.{0,140}\b(?:because|based on|after|when)\b",)),
        Criterion("composure", "responds constructively when challenged", (r"\b(?:when (?:they|the customer) (?:challenged|disagreed|pushed back)|after (?:they|the customer) objected)\b.{0,180}\b(?:I|we)\b",)),
        Criterion("honest_uncertainty", "communicates uncertainty honestly", (r"\b(?:I don't know|I am not sure|I wasn't certain|I would verify|I would check|I would find out)\b",)),
        Criterion("supported_claims", "supports claims with reasoning or outcomes", (r"\b(?:resulted in|increased by|reduced by|we achieved|the outcome was|I measured|for example)\b",)),
    ), _anchors("Confidence", "does not explain personal actions or decisions", "makes claims with little ownership or support", "explains a decision or takes ownership of an action", "takes ownership, gives reasoned decisions, and stays constructive or appropriately candid under challenge")),
    Competency("sales_knowledge", "Sales Knowledge", 15, (
        Criterion("sales_process", "understands stages of the sales process", (r"\b(?:prospect|outreach)\b.{0,180}\b(?:discovery|qualif\w*|proposal|close|follow-up)\b",)),
        Criterion("discovery", "uses discovery to understand the opportunity", (r"\b(?:discovery|explor\w*|understand)\w*\b.{0,100}\b(?:need|challenge|goal|current process|problem)\b",)),
        Criterion("qualification", "qualifies fit and readiness", (r"\b(?:qualif\w*|assess fit|determine fit)\b.{0,160}\b(?:need|fit|budget|timeline|authority|decision|stakeholder)\b",)),
        Criterion("customer_needs", "centers customer needs", (r"\b(?:customer|prospect)\w*\b.{0,100}\b(?:need|goal|problem|priority|challenge)\b",)),
        Criterion("value_proposition", "connects an offer to customer value", (r"\b(?:value proposition|return on investment|ROI|business outcome|benefit)\b.{0,120}\b(?:need|goal|cost|result|customer)\b",)),
        Criterion("negotiation", "negotiates with a reasoned trade-off", (r"\b(?:trade-off|in exchange for|rather than discount|negotiat\w*)\b.{0,140}\b(?:value|term|scope|price|commitment|need)\b",)),
        Criterion("closing", "understands commitment and next steps", (r"\b(?:ask for|secure|confirm)\b.{0,80}\b(?:commitment|decision|next step|agreement)\b",)),
        Criterion("ethical_selling", "describes honest, customer-fit selling", (r"\b(?:not a fit|honest about|transparent about|would not recommend|customer's best interest)\b",)),
    ), _anchors("Sales Knowledge", "does not describe a relevant sales approach", "names sales concepts without explaining how they are applied", "describes at least one relevant sales practice", "connects discovery, qualification, value, negotiation, and ethical advancement where the prompt allows")),
    Competency("lead_qualification", "Lead Qualification", 15, (
        Criterion("needs", "discovers customer needs", (r"\b(?:asked|ask|explor\w*|identify|understand)\w*\b.{0,120}\b(?:need|goal|problem|challenge|priority)\b",)),
        Criterion("follow_up", "asks useful follow-up questions", (r"\b(?:follow-up question|followed up by asking|asked (?:what|why|how|which)|clarif\w* question|probed further)\b",)),
        Criterion("pain_points", "identifies pain points", (r"\b(?:pain point|business problem|current challenge|cost of the problem|what was not working|problem (?:they|the customer) need(?:s)? to solve)\b",)),
        Criterion("fit", "assesses fit between need and solution", (r"\b(?:assess|determine|check|establish)\w*\b.{0,120}\b(?:fit|suitable|match|right solution)\b",)),
        Criterion("stakeholders", "identifies decision makers or stakeholders", (r"\b(?:decision makers?|stakeholders?|who else (?:is involved|needs to approve)|who is involved in (?:the )?approval|people involved in the decision)\b",)),
        Criterion("budget_timing", "considers timing or budget when appropriate", (r"\b(?:budget|price range|timeline|when they need|purchase window|funding)\b",)),
        Criterion("success_criteria", "identifies success criteria", (r"\b(?:success (?:should )?look like|measure success|success criteria|key outcome|how they would measure)\b",)),
        Criterion("next_step", "establishes a relevant next step", (r"\b(?:agreed on|schedule\w*|scheduled|confirmed|set up|next step|follow up)\b.{0,100}\b(?:demo|meeting|date|customer|proposal|decision|call|trial)?\b",)),
    ), _anchors("Lead Qualification", "does not establish customer fit or needs", "mentions qualification topics without investigating the opportunity", "uncovers a need and at least one fit or readiness factor", "systematically explores needs, fit, stakeholders, readiness, success, and a suitable next step")),
    Competency("objection_handling", "Objection Handling", 15, (
        Criterion("acknowledges", "acknowledges the objection", (r"\b(?:I|we) (?:acknowledged|recognized|validated|understood|appreciated)\b.{0,80}\b(?:concern|objection|hesitation|worry|issue)\b",)),
        Criterion("diagnoses", "identifies the underlying concern", (r"\b(?:asked|clarified|explored|probed)\b.{0,100}\b(?:why|what|which|specifically|underlying|concern|reason)\b",)),
        Criterion("clarifies", "asks a clarifying question", (r"\b(?:asked|followed up|clarified)\b.{0,100}\b(?:what|why|how|which|specifically)\b",)),
        Criterion("relevant_response", "responds with relevant reasoning", (r"\b(?:in response|because|based on (?:that|their|what)|given (?:their|the) concern|I explained why)\b.{0,130}\b(?:they|customer|concern|need|solution|price|risk|value)\b",)),
        Criterion("customer_value", "connects the response to customer value", (r"\b(?:connect|tie|relate)\w*\b.{0,100}\b(?:value|benefit|outcome|need|goal)\b|\b(?:because|so that|need to)\b.{0,100}\b(?:save|reduce|improve|goal|need|result|delay|cost)\b",)),
        Criterion("evidence", "provides relevant evidence or an example", (r"\b(?:for example|for instance|in a similar case|the result was|we measured|reference customer)\b",)),
        Criterion("professional", "remains professional and non-defensive", (r"\b(?:I stayed calm|without arguing|I listened first|I did not pressure|I acknowledged their perspective)\b",)),
        Criterion("checks_resolution", "checks whether the concern is resolved", (r"\b(?:does that address|have I answered|does that resolve|would that help|is that still a concern|did that answer)\b",)),
        Criterion("advances", "moves the conversation forward appropriately", (r"\b(?:next step|move forward|follow up|schedule|trial|demo|revisit)\b",)),
    ), _anchors("Objection Handling", "no meaningful response to an objection is demonstrated", "acknowledges an objection but offers a weak or generic response", "identifies the concern and gives a relevant response", "diagnoses the concern, tailors a value-based response, and checks resolution or an appropriate next step")),
    Competency("persuasion", "Persuasion", 15, (
        Criterion("need_benefit", "connects benefits to stated needs", (r"\b(?:because you|based on your|given your|for your)\b.{0,130}\b(?:need|goal|priority|challenge|problem|team)\b",)),
        Criterion("value", "explains value clearly", (r"\b(?:value|benefit|outcome|savings|impact)\b.{0,120}\b(?:customer|team|business|goal|need|result)\b",)),
        Criterion("supports_claims", "supports claims with evidence", (r"\b(?:for example|we measured|the result|data showed|customer achieved|increased by|reduced by)\b",)),
        Criterion("relevant_examples", "uses a relevant example", (r"\b(?:for example|for instance|in a similar situation|one customer|a comparable client)\b",)),
        Criterion("adapts", "adapts the argument to customer context", (r"\b(?:tailored|adapted|adjusted|focused)\b.{0,120}\b(?:their|customer|prospect|specific|priority|situation)\b",)),
        Criterion("tradeoffs", "addresses trade-offs honestly", (r"\b(?:trade-off|limitation|downside|risk|what it would not|not the best fit|costs more)\b",)),
        Criterion("alignment", "checks customer alignment", (r"\b(?:does that align|how does that fit|would that solve|does that match|what do you think about)\b",)),
        Criterion("ethical_claims", "avoids manipulative or misleading claims", (r"\b(?:I was transparent|I did not promise|I explained the limitation|I would not claim|only if it fits)\b",)),
    ), _anchors("Persuasion", "does not connect an offer to the customer's situation", "asserts benefits without support or relevance", "explains a relevant value proposition", "tailors and supports value, addresses trade-offs honestly, and checks alignment")),
    Competency("closing_ability", "Closing Ability", 15, (
        Criterion("buying_signals", "recognizes buying signals", (r"\b(?:when they asked about (?:price|timing|implementation|next steps)|buying signal|showed interest in moving forward|asked about getting started)\b",)),
        Criterion("commitment", "asks for commitment", (r"\b(?:asked for|ask for|requested)\b.{0,90}\b(?:commitment|decision|business|order|agreement|go-ahead)\b",)),
        Criterion("next_step", "proposes a clear next step", (r"\b(?:next step|schedule a|book a|set up a|send the proposal|start a trial|implementation meeting)\b",)),
        Criterion("hesitation", "responds constructively to hesitation", (r"\b(?:when they hesitated|if they were unsure|addressed their hesitation|asked what was holding them back)\b",)),
        Criterion("timing", "confirms timing", (r"\b(?:by (?:when|date)|timeline|start date|this week|next month|when would you like)\b",)),
        Criterion("ownership", "establishes ownership of the next action", (r"\b(?:I will send|I would send|I own|I will coordinate|I will follow up)\b.{0,100}\b(?:proposal|date|meeting|next step|customer|you)\b",)),
        Criterion("follow_up", "confirms follow-up", (r"\b(?:confirmed a follow-up|scheduled a follow-up|follow up on|calendar invite|check back on)\b",)),
        Criterion("advances", "appropriately advances the opportunity", (r"\b(?:advance to|move forward|begin implementation|start the trial|schedule the demo|send the agreement)\b",)),
    ), _anchors("Closing Ability", "does not advance the opportunity or ask for a next step", "mentions follow-up but does not establish clear customer commitment", "proposes a clear, relevant next step", "recognizes a buying signal, seeks commitment, handles hesitation, and confirms ownership and timing")),
)

COMPETENCY_BY_KEY = {competency.key: competency for competency in COMPETENCIES}
COMPETENCY_WEIGHTS = {competency.key: competency.weight for competency in COMPETENCIES}


# These rules classify question intent only; answer text never receives credit from a tag.
QUESTION_TAG_PATTERNS: dict[str, tuple[str, ...]] = {
    "objection_handling": (r"\b(?:objection|concern|push(?:ed)? back|rejected|reject|price objection|competitor)\b",),
    "lead_qualification": (r"\b(?:qualif\w*|discover|discovery|decision maker|stakeholder|budget|timeline|pain point|customer need|fit)\b",),
    "closing_ability": (r"\b(?:clos\w*|commitment|buying signal|purchase|next step|agreement|ask for the sale|hesitat\w*)\b",),
    "persuasion": (r"\b(?:persuad\w*|convinc\w*|influence|value proposition|explain the value|make the case|benefit)\b",),
    "sales_knowledge": (r"\b(?:sales process|sales cycle|pipeline|negotiat\w*|sales strategy|selling approach)\b",),
    "confidence": (r"\b(?:challeng\w*|disagre\w*|uncertain|mistake|failure|difficult feedback|pressure)\b",),
}
