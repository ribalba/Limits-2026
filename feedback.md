
# LIMITS 2026 — Response to Reviewers (Submission #5)

## Review #5A — Nils Bonfils

**High-level concerns addressed.**

- *Method vs. case study contribution unclear.*
  **→ Action:** Separated method and case study; made clear the method is the core contribution.
- *Weak ties to LIMITS literature; discussion reads like limitations/conclusion.*
  **→ Action:** Strengthened ties to LIMITS literature and made the "why LIMITS" argument explicit — modern IT systems *appear* limitless (compute bookable by a click or API) when they are not; the impact of usage must be made felt by the consumer.

### Major recommendations

- **Clearer separation of method / implementation (case study)** e.g., endpoint names appear in §4.1 before endpoints are introduced.
  **→ Action:** §§5–6 renamed "Case Study"; endpoint names and GMT references removed from §4; registry-generation moved from §4 to §7.1.
- **Unify and tighten terminology;** terms used before definition (e.g., "GMT" in §4.1, "idle-subtracted energy" in §4.2), inconsistent terms ("benchmark block" / "workload block" / "block"), and under-defined terms ("registry", "[RUNTIME]", the protocol/HTTP/server/system boundaries).
  **→ Action:** Defined registry, idle-subtracted, and boundaries (footnote in §4); rephrased [RUNTIME]; unified "benchmark condition" throughout.
- **Add a dedicated limitations section;** limitations currently scattered (e.g., §4.1 last sentence, first half of §8) beyond those in §4.3.
  **→ Action:** New Limitations section between Evaluation and Discussion; scattered limitations consolidated into four classes.
- **Strengthen and clarify ties with LIMITS literature.**
  **→ Action:** Added Mytton, Pargman & Raghavan, Becker, Raghavan & Ma, De Decker; LIMITS-aligned framing (sufficiency / sobriety / degrowth / solar website) woven through Intro, Related Work, and Discussion.

### Minor recommendations

- **Clarify feature-selection assumptions** (e.g., why "Content-Type" is excluded); qualify or back the §7.2.1 claim that scaling with returned-collection size suffices to approximate workload-dependent behavior.
  **→ Action:** Added feature-selection criteria and explicit Content-Type justification in §5.5.
- **Add graphs** (line/scatter) to present results.
  **→ Action:** Added Figure 1 — /createToDo curve fit (left) and /ai measured-vs-predicted scatter (right).
- **Remove the outline at the start of §4.**
  **→ Action:** Removed.
- **Drop the metric-prefix equivalence description in §4.2** (e.g., g vs. mg).
  **→ Action:** Removed; emission equations no longer carry decorative unit-prefix factors.
- **Threshold question:** at what point does the deployment environment differ enough from the calibration environment to affect prediction errors? Expand on interpretability and modeling-assumption limitations.
  **→ Action:** Covered in Limitations under "Deployment dependence" with a recalibration note.
- **Avoid URL shorteners** (bit rot); consider doubling links with archive.org.
  **→ Action:** All five tinyurl links replaced with full metrics.green-coding.io URLs which we control.

## Review #5B — Kurtis Heimerl


**Main concern.** Length is on the high side; novelty of the modeling section is uncertain given the large existing body of power-consumption modeling work. Building the prototype is a valuable point in the design space.
**→ Action:** reduced the paper length by 1 3/4 while keeping the core messages

### Recommendation

- **Cut down the modeling;** take a well-established modeling tool and run from there.
  **→ Action:** Dialled down the equations in §4; removed the LLM example formula from the method.


## Review #5C — Brian Sutherland

**Comments addressed.** Limited engagement with prior LIMITS scholarship; LIMITS typically does not present detailed equations/calculations/metrics; technical content would benefit from boundary/information-source diagrams; Tables 3 and 4 need units and should stand on their own.
**→ Action:** Strengthened LIMITS engagement across Intro / Related Work / Discussion; simplified equations; Tables 3, 4, and 5 now carry units in column headers with self-contained captions.

### Recommendations

- **Come down harder on the grid-intensity problem;** make the assumptions behind "defined statically, updated periodically, or obtained from an internal service" explicit; consider prototyping a service that supplies grid intensity (e.g., ElectricityMaps live map).
  **→ Action:** Grid intensity reframed as static-vs-dynamic with explicit ElectricityMaps / WattTime references in §4.2, §6.2, §7.1.
- **The AI entanglement is puzzling** — most AI emissions occur at the server level, not the edge/endpoint; a stronger token-to-carbon translation may be needed, or it may be out of scope if the primary aim is client-side consumption plus header-bundling strategies.
  **→ Action:** AI reframed as one example of application-supplied features, with an explicit disclaimer that hosted inference at scale is out of scope.
- **Dial down the equation section** into clear, interdisciplinary-friendly explanation and examples; restructure into method / case study / results; survey existing LIMITS scholarship.
  **→ Action:** Equations dialled down with intuition-first prose; method / case-study / results restructured; LIMITS-adjacent scholarship surveyed in Related Work.
