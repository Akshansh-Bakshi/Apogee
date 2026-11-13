# Provisional topic assignment, taxonomy v1

The eight broad technical topics in `topic_taxonomy.py` are fixed before inspecting live
assignments. IDs, descriptions, and prerequisite edges are versioned as
`apogee-technical-v1`. This stage does not train or validate a classifier.

For each page, the service reads only embeddings created by the running encoder's model ID.
It individually L2-normalizes every 384-dimensional passage vector, takes their equal-weight
arithmetic mean in stable chunk-ID order, then L2-normalizes the mean. A missing, invalid, or
cancelled-out vector set is unclassified. This intentionally gives each chunk equal weight,
including overlapping chunks.

Topic descriptions are encoded once per application process with the existing encoder's
`role="query"` convention, then cached on the app's assigner. Cosine similarity is the dot
product of normalized page and description vectors. Ties choose the lexicographically first
topic ID. The default minimum cosine similarity of **0.40 is provisional and uncalibrated**;
below it the page is unclassified. A returned similarity is not a probability or a measure
of learning. Human review of page topics is required before reporting classification accuracy.

Each page with valid embeddings also returns a ranked cosine comparison for every topic,
including the top topic, runner-up, and their cosine-similarity margin. The original
top-one topic and 0.40 cutoff still determine `status`, `topic_id`, and `similarity`.
The margin is descriptive evidence only: it does not trigger abstention and is not
confidence or probability. Missing or invalid embeddings return unavailable evidence
with no similarity values.

`GET /api/v1/topics/assignments?user_id=<UUID>` is read-only and returns assignments plus
taxonomy metadata. The supplied ID filters database rows but is not authentication. Keep
the existing Docker ports bound to loopback.

## Stage B: exploration evidence

`GET /api/v1/topics/coverage?user_id=<UUID>` recomputes provisional assignments and
reads the same user's browsing events. Distinct page IDs and event visits are separate.
Latest activity is the maximum `occurred_at` event timestamp for assigned pages.
Sessions are counted for visibility but are not used in the score. Events with no assigned
page are counted as unassigned.

The deterministic **browsing activity index** is:

`0.45 min(log(1+pages)/log(6),1) + 0.25 min(log(1+visits)/log(9),1)
+ 0.20 exp(-max(age_days,0)/30) + 0.10 observed_children/total_children`.

Recency is zero without a recorded visit; the child term is zero if the topic has no
listed subtopics. Components are capped and the result is rounded to four decimals.
This is an observed browsing index, not knowledge, mastery, or percent completion.
The response includes raw counts. Coverage topic cards also expose the mean top-two
cosine margin of their assigned pages. This reuses assignments already computed by the
coverage service and causes no extra per-page API requests. It does not affect activity
scores or recommendations.

For each evidenced topic, the service examines only direct prerequisite edges in the
frozen graph. A prerequisite with fewer than two assigned pages is a suggestion. Each
explanation gives the source and target topics and actual page/visit counts. Duplicate
targets are collapsed to the strongest source; ties are stable by ID. Graph cycles are
rejected. No recommendations are made without captured-page evidence. The two-page
sparse cutoff is an explicit heuristic, not a learned rule.
