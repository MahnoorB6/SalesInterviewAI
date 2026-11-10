"""Single source of truth for behavioral competencies, weights, and score anchors."""

from dataclasses import dataclass


RUBRIC_VERSION = "sales_questions_1.2"
EVALUATOR_VERSION = "sales_question_rubric_engine_1.2"
EVALUATION_METHOD = "behavioral_rubric_v2"
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
    Competency("communication", "Cold-Call Opening", 15, (
        Criterion("permission_intro", "opens with a concise introduction and reason for calling", (r"\b(?:my name is|this is)\b.{0,100}\b(?:calling|reach(?:ing)? out)\b",)),
        Criterion("relevance_hook", "gives a relevant reason to continue", (r"\b(?:noticed|saw|work with|help|calling because|reaching out because)\b.{0,140}\b(?:company|team|business|sales|customer|challenge|result)\b",)),
        Criterion("permission_based", "asks permission or checks availability", (r"\b(?:is now a bad time|do you have a minute|have I caught you at a good time|can I take|could I briefly)\b",)),
        Criterion("open_question", "starts discovery with an open question", (r"\b(?:how are you|what are you currently|how do you currently|what challenges|how is your team)\b",)),
    ), _anchors("Cold-Call Opening", "does not establish who is calling or why", "introduces the company but gives little reason to engage", "introduces self and a relevant reason for the call", "opens briefly, earns permission, states relevant context, and invites dialogue")),
    Competency("confidence", "Managing Sales Targets", 15, (
        Criterion("reviews_pipeline", "reviews pipeline and target gap", (r"\b(?:review|reviewed|check|checked|analy[sz]e|analysed)\b.{0,100}\b(?:pipeline|target|quota|gap|forecast)\b",)),
        Criterion("prioritizes_activity", "prioritizes high-value sales activity", (r"\b(?:prioriti[sz]e|focus|increase|schedule)\w*\b.{0,120}\b(?:prospect|call|follow-up|meeting|opportunit|pipeline|account)\w*\b",)),
        Criterion("diagnoses_blocker", "identifies why performance is behind", (r"\b(?:identify|understand|find out|diagnos)\w*\b.{0,120}\b(?:why|blocker|bottleneck|conversion|stuck|behind|shortfall)\b",)),
        Criterion("tracks_adjustment", "tracks progress and adjusts the plan", (r"\b(?:track|measure|review)\w*\b.{0,120}\b(?:daily|weekly|progress|conversion|results|target)\b",)),
        Criterion("seeks_coaching", "uses coaching or resources when useful", (r"\b(?:coach|manager|team|training|feedback|support)\b",)),
    ), _anchors("Managing Sales Targets", "does not describe a plan when behind target", "relies on vague effort without diagnosing the gap", "identifies a gap and takes focused corrective action", "diagnoses the pipeline, prioritizes measurable actions, tracks results, and adapts or seeks support")),
    Competency("sales_knowledge", "Price Objection Response", 15, (
        Criterion("acknowledges_price", "acknowledges the price concern without arguing", (r"\b(?:understand|appreciate|hear|recognize|acknowledge)\w*\b.{0,100}\b(?:price|cost|expensive|budget|concern)\b",)),
        Criterion("explores_price", "clarifies what makes the price too high", (r"\b(?:ask|asked|clarif\w*|explor\w*)\b.{0,100}\b(?:price|cost|budget|expensive|concern|compare)\b",)),
        Criterion("ties_to_value", "connects price to relevant customer value", (r"\b(?:value|benefit|return|ROI|save|reduce|result|outcome)\b.{0,120}\b(?:price|cost|investment|need|goal|customer)\b",)),
        Criterion("offers_options", "offers a suitable option or scope adjustment", (r"\b(?:option|alternative|smaller plan|phased|scope|payment|package|pilot|trial)\b",)),
        Criterion("checks_response", "checks whether the response addresses the concern", (r"\b(?:does that|would that|how does that|is price still|address your concern)\b",)),
    ), _anchors("Price Objection Response", "dismisses or ignores the price concern", "responds with a generic discount or feature pitch", "explores the concern and explains relevant value", "diagnoses price context, supports value, considers fit-based options, and checks resolution")),
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
    Competency("objection_handling", "Handling Objections", 15, (
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
    Competency("persuasion", "Competitor Differentiation", 15, (
        Criterion("compares_fit", "compares solutions against the customer's stated needs", (r"\b(?:compare|comparison|compared|versus|competitor|alternative)\b.{0,160}\b(?:need|goal|fit|requirement|priority|customer|solution)\b",)),
        Criterion("differentiates", "explains a relevant, specific difference", (r"\b(?:different|advantage|strength|unique|better fit|stand out)\b.{0,120}\b(?:solution|product|customer|need|competitor|alternative)\b",)),
        Criterion("supports_difference", "supports differentiation with evidence", (r"\b(?:for example|case study|data|proof|result|reference|demonstrat)\w*\b",)),
        Criterion("fair_comparison", "represents competitors fairly and honestly", (r"\b(?:fair|honest|accurate|would not criticize|not assume|acknowledge their strength)\b",)),
        Criterion("checks_fit", "checks which solution best fits the customer", (r"\b(?:what matters most|how does that compare|which is more important|best fit|does that address)\b",)),
    ), _anchors("Competitor Differentiation", "dismisses the competitor or makes unsupported claims", "lists features without linking them to customer priorities", "compares relevant strengths against customer needs", "uses a fair, evidence-based comparison and confirms fit with the customer's priorities")),
    Competency("closing_ability", "Customer Retention", 15, (
        Criterion("onboarding", "supports a smooth handoff or onboarding", (r"\b(?:onboard|implementation|handoff|welcome|setup|training)\w*\b",)),
        Criterion("proactive_checkins", "sets proactive check-ins", (r"\b(?:check in|check-in|follow up|regular review|business review|touch base)\b",)),
        Criterion("measure_outcomes", "tracks satisfaction or customer outcomes", (r"\b(?:satisfaction|success metric|outcome|adoption|usage|goal|results)\b",)),
        Criterion("resolve_issues", "responds promptly to issues and feedback", (r"\b(?:resolve|address|escalate|feedback|issue|problem|concern)\w*\b",)),
        Criterion("grow_relationship", "identifies relevant repeat or expansion opportunities", (r"\b(?:renew|repeat business|renewal|expand|upsell|cross-sell|additional need)\w*\b",)),
        Criterion("personalized_service", "personalizes ongoing support to customer needs", (r"\b(?:personal|tailor|adapt|customer's priorities|their needs)\w*\b",)),
    ), _anchors("Customer Retention", "does not describe post-sale relationship care", "relies on occasional contact without a customer success plan", "describes relevant follow-up and support", "combines onboarding, proactive reviews, outcome tracking, responsive service, and fit-based repeat business")),
)

COMPETENCY_BY_KEY = {competency.key: competency for competency in COMPETENCIES}
COMPETENCY_WEIGHTS = {competency.key: competency.weight for competency in COMPETENCIES}


# These rules classify question intent only; answer text never receives credit from a tag.
QUESTION_TAG_PATTERNS: dict[str, tuple[str, ...]] = {
    "sales_knowledge": (
        r"\b(?:price\s+(?:is\s+)?(?:too\s+)?(?:high|expensive)|too expensive|price objection|costs? too much|pricing)\b",
        r"\b(?:sales process|sales cycle|pipeline|negotiat\w*|sales strategy|selling approach)\b",
    ),
    "objection_handling": (r"\b(?:objection\w*|concern\w*|push(?:ed)? back|rejected|reject)\b",),
    "lead_qualification": (r"\b(?:qualif\w*|discover|discovery|decision maker|stakeholder|budget|timeline|pain point|customer need|fit)\b",),
    "closing_ability": (r"\b(?:after the sale|post.sale|repeat business|customer relationship|retain|retention|renewal|onboarding|customer success)\b",),
    "persuasion": (r"\b(?:competitor|competing|alternative solution|choose our|convinc\w*|compare)\b",),
    "confidence": (r"\b(?:challeng\w*|disagre\w*|uncertain|mistake|failure|difficult feedback|pressure|behind (?:on )?(?:my )?(?:sales )?target|sales target|quota|falling behind)\b",),
}
