# Awesome README Checklist for an Open-Source Project

Use this checklist when creating or substantially rewriting an open-source `README.md`.

The README should work like a **progressive JPEG**: communicate the essential value immediately, then progressively reveal evidence, usage, and details. Assume that most readers will scan rather than read line by line.

## Before writing

- [ ] Inspect the repository before making claims.
- [ ] Identify:
  - what the project is;
  - what problem it solves;
  - who it is for;
  - its main user-facing benefits;
  - meaningful differences from alternatives;
  - the simplest realistic usage example;
  - any benchmarks, size measurements, supported platforms, or other evidence already available.
- [ ] **Never invent facts.** Do not fabricate benchmarks, adoption numbers, supported platforms, comparisons, performance claims, file sizes, or features.
- [ ] If an important fact cannot be established from the repository or other authoritative project material, omit the claim or mark it for human input.

## 1. Make the opening block excellent

The first screen of the README is the most important part.

- [ ] Start with the project name.
- [ ] Immediately explain **what the project is**.
- [ ] Immediately explain **why it is useful**.
- [ ] State a meaningful **difference from existing alternatives** when one can be supported.
- [ ] Describe the project in normal language that one developer would use when explaining it to another developer.
- [ ] Avoid slogans, clever but ambiguous taglines, marketing jargon, and unnecessary technical terminology.
- [ ] Prefer concrete benefits over adjectives such as "powerful", "modern", "blazing fast", "lightweight", or "easy".
- [ ] Ruthlessly shorten the description while preserving its meaning.

A reader who sees only this block should already understand:

> **What is this? Why might I want it? Why this instead of something else?**

## 2. Make the README scannable

Readers should be able to understand the important points without reading every sentence.

- [ ] Use short sections with descriptive headings.
- [ ] Use bullet lists for groups of benefits or capabilities.
- [ ] Use **bold text** selectively to expose key information during a quick scan.
- [ ] Keep paragraphs reasonably short.
- [ ] Put important information before supporting detail.
- [ ] Remove prose that does not help the reader understand, evaluate, or use the project.

When reviewing the README, skim only:

- headings;
- bold text;
- lists;
- code examples;
- images.

The project's core value should still be understandable.

## 3. Show instead of merely claiming

After explaining the value, demonstrate it.

- [ ] Include a small, realistic code example when code can communicate the value better than prose.
- [ ] If the API or developer experience is a major benefit, **show the API**.
- [ ] Add a useful screenshot, diagram, or other visual when it makes the project substantially easier to understand.
- [ ] Keep the first example focused on the common case rather than demonstrating every option.

Prefer:

```text
claim → evidence
```

over:

```text
claim → more marketing language
```

## 4. Back important claims with real evidence

Claims such as "fast", "small", "simple", or "efficient" should be demonstrable.

- [ ] Use actual measurements when quantitative evidence exists.
- [ ] Link to or explain the benchmark methodology when necessary for interpreting the result.
- [ ] Ensure comparisons use meaningful and reasonably comparable conditions.
- [ ] Prefer concrete numbers over vague superlatives.
- [ ] Do not add numbers merely to make the README look authoritative.
- [ ] If no reliable measurement exists, make a narrower factual statement instead.

Examples of useful evidence include:

- package or binary size;
- benchmark results;
- dependency count;
- API comparison;
- supported environments;
- a concrete reduction in required code or configuration.

## 5. Put the quick start after the value proposition

Do not begin the README with a long installation tutorial.

First establish that the project is relevant. Then explain how to use it.

- [ ] Add a clearly named `Quick Start`, `Getting Started`, or equivalent section.
- [ ] Give specific commands rather than vague instructions.
- [ ] Show the shortest path from installation to a meaningful working result.
- [ ] Make commands and examples copyable.
- [ ] Include prerequisites only when they are actually required.
- [ ] Explain non-obvious steps.
- [ ] Cover important alternate paths when users may reasonably start from different environments.
- [ ] Split instructions by user type or integration path when a single linear tutorial would become confusing.

Aim for:

```text
install → configure if necessary → run → observe useful result
```

## 6. Reveal detail progressively

Order sections from highest-value information to increasingly specialized detail.

A good default structure is:

```markdown
# Project Name

One concise description explaining what it is, why it is useful,
and its meaningful differentiator.

Key benefits / proof

Small code example or visual

## Quick Start

Shortest working path.

## Usage

Common workflows and options.

## How It Works

Only if understanding the design helps users.

## Documentation

Only when deeper documentation exists and readers need a clear
next step beyond the README.
```

Adapt the structure to the project. Do not create sections merely because they are conventional.

In particular:

- [ ] Do not add `Contributing`, `License`, `Code of Conduct`, or similar sections merely to link to repository files that GitHub already exposes through its own UI.
- [ ] Do not turn the README into a directory of repository metadata.
- [ ] Link to another document only when doing so is useful **in the context of what the reader is currently trying to accomplish**.

## 7. Test the README as a new user

The README is not complete merely because the instructions look plausible.

- [ ] Follow the documented quick start from a clean environment when practical.
- [ ] Do not rely on undeclared local configuration, cached dependencies, credentials, files, or knowledge.
- [ ] Verify that commands actually work.
- [ ] Verify that code examples match the current API.
- [ ] Verify that links work.
- [ ] Verify that prerequisites are documented.
- [ ] Check alternate installation paths that the README explicitly promises.
- [ ] Fix the README or the product when the documented experience exposes unnecessary friction.

## 8. Final quality pass

Before considering the README finished:

- [ ] The first paragraph clearly says what the project does.
- [ ] A reader can identify its benefit within a few seconds.
- [ ] Important differentiation is factual rather than promotional.
- [ ] The README is useful when skimmed.
- [ ] Major claims have evidence.
- [ ] Examples are realistic and current.
- [ ] No unsupported numbers or capabilities were invented.
- [ ] The quick start produces a useful result.
- [ ] Detailed instructions come after the high-level explanation.
- [ ] Unnecessary jargon and marketing language have been removed.
- [ ] Repeated information has been consolidated.
- [ ] Repository metadata already exposed by the hosting platform is not redundantly reproduced.
- [ ] Every major section helps a prospective user **understand, evaluate, or use** the project.

## Core rule

When forced to choose between adding more information and making the project's value easier to understand, prefer **clarity, evidence, and scannability**.
