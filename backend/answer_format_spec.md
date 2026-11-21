
# Pyrmit Answer Format Specification

Issue: AID-34
Status: Draft — Pending Team Review and AID-24 Scope Confirmation

## 1. Overview

Pyrmit provides preliminary feasibility assessments for proposed construction projects using relevant Swedish planning regulations, municipal documents, and available supporting evidence.

Every answer should:

- Communicate a clear feasibility verdict when sufficient evidence exists.
- Explain applicable rules and restrictions.
- Support factual and legal claims with traceable citations.
- Ask for missing information instead of making unsupported assumptions.
- Explicitly distinguish verified information from unverified information.
- Provide actionable guidance on permits, steps, documents, fees, and contacts.
- Include a disclaimer explaining that Pyrmit does not issue official permit decisions.
- Support Swedish and English responses.

The specification defines the expected answer format and behavior. Implementation of answer generation and citation handling belongs to AID-29.

## 2. Standardized Feasibility Verdicts

Pyrmit should use the following four verdict values:

| Verdict | Meaning |
|---|---|
| `FEASIBLE` | Available verified evidence supports the preliminary feasibility of the proposed project. |
| `FEASIBLE_WITH_CONDITIONS` | The project appears feasible only if identified requirements or restrictions are satisfied. |
| `NOT_FEASIBLE` | Verified applicable rules establish a conflict with the proposed project as described. |
| `UNCLEAR` | Available evidence or project information is insufficient to establish feasibility reliably. |

These verdicts represent preliminary assessments, not official municipal approval decisions.

### 2.1 Verdict Selection Rules

1. A positive verdict must be supported by verified evidence applicable to the specific property and proposed project.
2. If essential property-specific restrictions cannot be verified, the verdict must be `UNCLEAR`, even when general municipal rules appear to allow the project.
3. A project must not receive a positive verdict solely because similar projects have previously been approved.
4. `NOT_FEASIBLE` requires verified evidence of a conflict with an applicable restriction.
5. `FEASIBLE_WITH_CONDITIONS` requires identifiable conditions supported by available evidence.
6. If evidence is missing, conflicting, or insufficient to justify a verdict, use `UNCLEAR`.
7. Verdicts must not be presented as official municipal decisions.

### 2.2 Compatibility With Existing Implementation

The current `Orchestrator` uses:

- `HIGHLY FEASIBLE`
- `FEASIBLE WITH CHALLENGES`
- `NOT FEASIBLE`
- `UNCERTAIN`

These differ from the standardized verdicts proposed in this specification.

AID-29 should reconcile the existing values with the agreed answer format, subject to team approval.

The existing verdict calculation also considers historical approval rates. Historical outcomes may provide context but must not independently establish legal feasibility.

## 3. Required Answer Sections

Each substantive assessment should follow this structure:

1. Verdict and summary — Preliminary feasibility assessment and brief explanation.
2. Applicable rules — Relevant planning regulations, restrictions, and legal sources.
3. Permits — Potentially required permits or approvals.
4. Steps — Recommended next actions and application procedure.
5. Documents — Documentation likely required for the application.
6. Fees — Verified costs, estimates clearly identified as such, or unknown values.
7. Contacts — Relevant municipality, authority, or department.
8. Unverified information — Information that could not be confirmed.
9. Sources — Traceable references supporting the answer.
10. Disclaimer — Statement that the response is preliminary and does not replace an official decision.

Sections must remain distinguishable even when information is unavailable.

Missing values must not be fabricated.

For clarification-only responses, Pyrmit may provide a shorter answer that identifies missing information and asks the necessary question rather than generating unsupported sections.

## 4. Citation Rules

Every material factual or legal claim must be supported by a traceable source.

### 4.1 Required Citation Information

Where available, citations should include:

- Source identifier
- Document title or legal reference
- Issuing authority or municipality
- Relevant section, page, or paragraph
- URL or document reference
- Relevant source passage
- Retrieval or verification date

Each citation must refer to evidence that supports the specific claim being made.

### 4.2 Citation Requirements

1. Legal restrictions and permit requirements must have supporting citations.
2. Claims about municipal planning rules must reference the relevant municipality and planning document.
3. Historical approval decisions must be identified as examples, not guarantees of future approval.
4. A source must never be invented or presented as verified when it has not been retrieved.
5. When the available source does not support a claim, that claim must be marked unverified or omitted.
6. Swedish source passages should be preserved accurately, with an English interpretation when answering in English.
7. The answer should clearly distinguish legal requirements from recommendations and historical observations.
8. Each cited claim must reference a source identifier that exists in the Sources section.
9. A source appearing in the Sources section does not automatically support every statement in the answer.
10. Citations must not imply a level of precision that the retrieved source metadata cannot support.

### 4.3 Current Implementation Limitation

The current `LawAgent` and `DocumentAgent` return source labels through a `sources` list.

This is insufficient for reliable claim-level citations because the returned information does not consistently identify the exact passage supporting each generated claim.

AID-29 should therefore introduce structured evidence references or equivalent claim-to-source mappings before treating generated citations as verified.

## 5. Ask Instead of Guess

Pyrmit must request clarification when missing information could materially change the feasibility verdict.

Examples of essential information include:

- Municipality or project location
- Property identifier when parcel-specific planning rules are required
- Proposed project type
- Number of units or relevant project dimensions
- Whether the proposal concerns new construction, extension, or modification, when relevant

### 5.1 Clarification Behavior

If essential information is missing:

1. Do not invent a location, property identifier, or project specification.
2. Ask a focused question identifying the missing information.
3. Do not issue a definitive feasibility verdict.
4. Use `UNCLEAR` if a provisional verdict must be returned.
5. Explain why the missing information matters.

If several essential details are missing, ask for the minimum set necessary to continue.

### 5.2 Unsupported Municipality or Missing Data

If Pyrmit does not have sufficient information for the requested municipality:

1. State that the required municipal data is unavailable or insufficient.
2. Do not substitute another municipality's planning rules.
3. Do not infer property-specific restrictions from unrelated documents.
4. Return `UNCLEAR` if feasibility cannot be established.
5. Direct the user to the relevant municipality or official source for confirmation.

## 6. Unverified Information

Pyrmit must maintain a separate list of important claims that could not be confirmed from available evidence.

Each unverified item should identify:

- The information that remains uncertain
- Why it could not be verified
- What source or additional information would resolve the uncertainty
- Whether the uncertainty affects the feasibility verdict

Missing information must not be silently converted into a factual statement.

Examples include unknown municipal fees, unconfirmed permit requirements, unavailable planning documents, and unsupported project-density limits.

If an unresolved issue could materially change the verdict, Pyrmit must use `UNCLEAR` rather than presenting a confident conclusion.

## 7. Disclaimer

Every substantive feasibility assessment must include the following disclaimer or an equivalent translation:

"This is a preliminary assessment based on the available information and sources. It is not an official building-permit decision or a substitute for confirmation from the relevant municipality or authority."

The disclaimer must not be used to justify unsupported claims or missing citations.

## 8. Worked Examples

The following examples are fictional and intended to demonstrate the proposed answer format.

All properties, planning rules, source identifiers, and municipalities are illustrative, not verified legal information.

The examples assume hypothetical source documents for demonstration purposes. They must not be used as real legal guidance.

### Example 1: Feasible With Conditions

**User question:** "Can I build four apartments on my property in Municipality A?"

**Example assumptions:**

- The property has been identified.
- The fictional planning document DP-001 has been confirmed as applicable to that property.
- The document permits up to four residential units.
- The document establishes a maximum building height of 8 metres.
- No additional material restrictions remain unresolved for the purpose of this example.

**Verdict:** `FEASIBLE_WITH_CONDITIONS`

**Summary:** Under the hypothetical planning document, the proposed four-apartment building appears feasible if the applicable height and design requirements are satisfied.

**Applicable rules:**

- The fictional planning document DP-001 permits residential buildings containing up to four units [S1].
- The fictional maximum building height is 8 metres [S1].

**Permits:** A building permit is assumed to be required in this fictional scenario [S1].

**Steps:**

1. Confirm that the proposed drawings comply with the applicable planning restrictions.
2. Prepare the required application documents.
3. Contact the municipal building-permit department.
4. Submit the application for official assessment.

**Documents:**

- Site plan
- Floor plans
- Elevation drawings
- Project description

These documents are illustrative; actual submission requirements must be confirmed.

**Fees:** Not verified. Request the current fee schedule from Municipality A.

**Contacts:** Municipality A, Building Permit Department (fictional).

**Unverified information:**

- The current application fee.
- The processing timeline.
- Any administrative requirements not covered by the fictional source.

These unresolved administrative details do not change the hypothetical planning-rule assessment, but must be confirmed before an application is submitted.

**Sources:**

[S1] Fictional Municipality A, Illustrative Planning Document DP-001, Section 3. Example source only; not a real regulation.

**Disclaimer:** This is a preliminary assessment based on fictional assumptions. It is not an official building-permit decision.

---

### Example 2: Missing Essential Information

**User question:** "Can I build six apartments on my land?"

**Verdict:** `UNCLEAR`

**Summary:** The feasibility of the proposed project cannot be determined without knowing where the property is located.

**Clarification question:** "Which municipality is the property in, and do you know its property designation (fastighetsbeteckning)?"

**Applicable rules:** Cannot identify the applicable municipal planning documents without the location.

**Permits:** Permit requirements cannot yet be confirmed.

**Steps:** Provide the municipality and, if available, the property designation.

**Documents:** To be determined after identifying the applicable planning rules.

**Fees:** Unknown.

**Contacts:** Relevant municipality, once identified.

**Unverified information:**

- Applicable planning restrictions.
- Permitted number of residential units.
- Required permits and application fees.

These missing details prevent a reliable feasibility assessment.

**Sources:** No property-specific sources have been identified.

**Disclaimer:** No feasibility determination can be made until essential project information is provided.

---

### Example 3: Not Feasible Under the Stated Plan

**User question:** "Can I build ten apartments on my property in Municipality B?"

**Example assumptions:**

- The property has been identified.
- Fictional planning document DP-002 has been confirmed as applicable.
- The fictional document establishes a maximum of six residential units.
- The proposed project contains ten residential units.
- No applicable exception permitting the proposed ten-unit design has been identified in the hypothetical evidence.

**Verdict:** `NOT_FEASIBLE`

**Summary:** Under the fictional planning document DP-002, the proposed ten-apartment building conflicts with the stated maximum of six residential units.

**Applicable rules:**

- Fictional planning document DP-002 limits the property to six residential units [S2].
- The proposed ten-unit building exceeds the illustrative limit by four units [S2].

**Permits:** The proposed design conflicts with the assumed planning restriction. Any alternative approval procedure must be confirmed with the municipality.

**Steps:**

1. Review the proposed number of residential units.
2. Consider redesigning the project to comply with the assumed limit.
3. Consult the municipal planning department about available alternatives.
4. Confirm whether any different planning procedure could apply.

**Documents:**

- Revised site plan
- Revised building drawings
- Updated project description

These are illustrative requirements for a redesigned proposal.

**Fees:** Not verified.

**Contacts:** Municipality B, Planning Department (fictional).

**Unverified information:**

- Whether an alternative planning procedure is available.
- The cost and timeframe of a revised application.
- Any additional administrative requirements.

The verdict applies only to the ten-unit proposal under the fictional planning restriction described above. It does not establish that every alternative project would be infeasible.

**Sources:**

[S2] Fictional Municipality B, Illustrative Planning Document DP-002, Section 4. Example source only; not a real regulation.

**Disclaimer:** This example demonstrates how Pyrmit should respond to a planning conflict supported by the assumed evidence. It does not describe an actual Swedish property or legal decision.

## 9. Implementation and Scope Notes

This specification defines the proposed answer contract for AID-29.

AID-29 is responsible for implementing answer generation, citation handling, and integration with the existing agent pipeline.

The current implementation does not yet guarantee all requirements described in this specification.

The final supported municipalities, project types, and other scope-dependent assumptions must be confirmed through AID-24 and team/client review.

Until those decisions are confirmed, this document should be treated as a proposed specification rather than an approved implementation contract.
