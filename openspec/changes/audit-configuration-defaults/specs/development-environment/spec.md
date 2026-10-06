# Spec Delta

## ADDED Requirements

### Requirement: Tool configuration omits redundant defaults

Repository-owned tool configuration and automation SHALL omit optional settings and command flags whose removal preserves effective behavior in every supported invocation context. Comparisons SHALL account for presets, wrappers, environment variables, and tool versions. Required fields, positional operands, and syntax delimiters are not optional overrides.

#### Scenario: A validation setting repeats a tool default

- **WHEN** an explicit link-validation setting equals the verified default and no inherited setting changes it
- **THEN** the setting is omitted and link validation remains enabled

#### Scenario: A preset changes the built-in default

- **WHEN** a local setting matches the built-in default but removing it activates a different inherited preset value
- **THEN** it is retained as an override of the inherited value

#### Scenario: A wrapper already supplies the behavior

- **WHEN** a command flag duplicates behavior supplied by its wrapper in every supported invocation
- **THEN** the redundant flag is omitted without changing standalone invocations that lack that wrapper

### Requirement: Every tool override has a specific rationale

Each retained non-default option or flag SHALL have a concise inline comment, documentation entry, or OpenSpec specification containing `The default is <default_value>. We override it because <concise_rationale>.` The explanation SHALL identify the option, applicable default, and concrete project need. Optional settings without a configured value SHALL use `unset` or `none`, with its meaning explained.

#### Scenario: A command enables stricter validation

- **WHEN** an automation command retains a non-default strict-validation flag
- **THEN** an allowed location identifies the flag and explains its default and the required failure behavior using the specified sentence format

#### Scenario: An optional setting has no configured default

- **WHEN** a retained optional setting supplies a project-specific value where the tool supplies none
- **THEN** its explanation states that the default is unset or none and explains why the value is supplied

### Requirement: Default comparisons have authoritative evidence

Default-removal decisions and override explanations SHALL be supported by official documentation, schemas, source, or help for the applicable tool version and execution context. Evidence SHALL be traceable from the explanation or audit record. A guessed default SHALL NOT justify removal or a factual rationale.

#### Scenario: Documentation describes another release

- **WHEN** current upstream documentation disagrees with the repository's selected tool version
- **THEN** the audit uses evidence for the selected version and records the discrepancy before changing the setting

#### Scenario: A default cannot be established

- **WHEN** authoritative evidence does not establish the applicable default
- **THEN** the audit reports a completion blocker instead of inventing a default or silently excluding the option

### Requirement: Override explanations remain traceable and current

An explanation SHALL map unambiguously to every option or flag it covers. Shared explanations SHALL enumerate covered occurrences and apply only when default, context, and rationale agree. Relevant tool upgrades and configuration edits SHALL recheck affected defaults and remove explanations for deleted overrides.

#### Scenario: Several commands share a justified flag

- **WHEN** one documentation entry explains the same override across multiple commands
- **THEN** it identifies those commands and covers each occurrence without duplicating the rationale

#### Scenario: An upgrade makes an override redundant

- **WHEN** an applicable tool upgrade makes a retained override equal to the effective default
- **THEN** the redundant setting and its obsolete explanation are removed

### Requirement: Default cleanup preserves repository contracts

Default cleanup SHALL preserve existing validation coverage, failure propagation, dependency-update ownership and policy, reproducibility, credential isolation, and supported invocation contexts. It SHALL NOT weaken a contract to make a setting removable.

#### Scenario: An apparent default has execution consequences

- **WHEN** removing a shell selection, action input, or inherited override changes error handling, trust boundaries, or supported environment behavior
- **THEN** the necessary setting remains and receives its override rationale
