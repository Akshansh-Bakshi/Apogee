# SYNTHETIC label rubric

Version: `synthetic-next-topic-rubric-v1`

These labels are explicitly synthetic judgments for fictional scenarios. They do not represent
clicks, ratings, relevance feedback, learning outcomes, expert consensus, or independent human
ground truth. No language model judge is claimed to supply reliable truth.

## Judgment question

For each candidate, ask: **How useful would this broad topic be as one of the next exploration
directions for the fictional goal and context described in the scenario?**

The manually declared family profiles consider:

1. the fictional person's stated intent and immediate constraint;
2. whether consolidation or a new application is more useful in that narrative;
3. whether the topic can unlock a concrete next investigation;
4. signs of sparse evidence, repeated visits, or a deliberate return to foundations;
5. interdisciplinary value and safety concerns; and
6. genuine ambiguity, allowing several strong or potential candidates.

These considerations are qualitative. The generator does not calculate the label from page
counts, visits, recency, prerequisite counts, graph flags, or a weighted feature sum. Profiles are
declared separately from activity generation, and feature perturbations do not change them.

## Grades

| Grade | Synthetic meaning |
|---:|---|
| 0 | The topic does not usefully advance the stated fictional goal now, or would distract from it. |
| 1 | The topic could help, but is secondary, ambiguous, or useful after another step. |
| 2 | The topic directly supports the fictional next step or is one of several defensible strong choices. |

The grades are ordinal usefulness levels, not probabilities. A scenario may have one, two, or
three grade-2 topics. Candidate rankings therefore contain ties and ambiguity by design.

## Relationship to the existing graph

The production rule recommends sparse direct prerequisites of observed topics. Synthetic profiles
may agree with that rule when the narrative calls for foundations, but they may reject it when the
fictional goal calls for deployment, evaluation, a concrete application, privacy work, or escape
from repeated study. The generated statistics count graph-gap candidates labelled 0 as an audit
that labels are not direct copies of graph output.

## Human review protocol

Open only `data/human-review-sample.csv` during initial review. For each scenario, judge all eight
candidates together and enter 0, 1, or 2, a reviewer ID, and a short reason. Leave genuinely
unresolved cases blank and explain why. Open the separate synthetic label key only after the review
is complete. Agreement with the key measures agreement with this rubric's fictional judgments;
it does not validate recommendations for real users.
