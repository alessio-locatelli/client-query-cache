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

### Requirement: Behavioral overrides are distinguished from project inputs

A behavioral override changes meaningful policy supplied on omission, such as validation, failure handling, isolation, dependency policy, or resource limits. Ordinary declarative inputs, including navigation, paths, themes, enabled functionality/plugins, and content selection, SHALL require a rationale only when they counter inherited configuration or tool policy. Differing from an unset or fallback project input alone SHALL NOT make a setting a behavioral override.

#### Scenario: Ordinary project inputs are retained

- **WHEN** configuration supplies documentation directories, navigation, theme choices, plugin enablement, export sections, or tool input paths without countering inherited configuration or tool policy
- **THEN** those project inputs require no formal default-and-rationale explanation

#### Scenario: A declarative setting counters inherited policy

- **WHEN** a plugin setting re-enables validation disabled by an inherited preset
- **THEN** the setting is a behavioral override requiring a rationale for countering that inherited behavior

### Requirement: Every behavioral override has a specific rationale

Each retained behavioral override SHALL have a concise inline comment, documentation entry, or OpenSpec specification containing `The default is <default_value>. We override it because <concise_rationale>.` The explanation SHALL identify the option and concrete project need. The default description SHALL follow the omitted-behavior requirement below.

#### Scenario: A command enables stricter validation

- **WHEN** an automation command retains a non-default strict-validation flag
- **THEN** an allowed location identifies the flag and explains its default and the required failure behavior using the specified sentence format

### Requirement: Default descriptions express omitted behavior

The default description SHALL state the behavior when the option is omitted in the applicable context. It SHALL use a concrete value when fixed, `unset` or `none` when no value is supplied, or a description of inheritance when context-dependent. Inheritance descriptions SHALL identify the configuration source and relevant context; they SHALL NOT imply a fixed value across environments.

#### Scenario: Git inherits user configuration

- **WHEN** an explicit signing setting protects a disposable repository from inherited Git configuration
- **THEN** its rationale describes the default as inherited from Git configuration, identifies the applicable configuration scope, and explains why signing is disabled

#### Scenario: Permissions depend on platform settings

- **WHEN** an explicit workflow permission setting constrains permissions inherited from repository or organization settings
- **THEN** its rationale describes that inheritance and the workflow context rather than claiming a universal omitted permission value

### Requirement: Default comparisons have authoritative evidence

Default-removal decisions and override explanations SHALL be supported by official documentation, schemas, source, or help for the applicable tool version and execution context. Evidence SHALL remain traceable after delivery from the retained explanation or, for removals, the implementation commit body. A guessed omitted behavior SHALL NOT justify removal or a factual rationale.

#### Scenario: Documentation describes another release

- **WHEN** current upstream documentation disagrees with the repository's selected tool version
- **THEN** the audit uses evidence for the selected version and records the discrepancy before changing the setting

#### Scenario: Omitted behavior cannot be established

- **WHEN** authoritative evidence establishes neither a fixed omitted value nor the applicable inheritance behavior
- **THEN** the audit reports a completion blocker instead of inventing omitted behavior or silently excluding the option

#### Scenario: Removal evidence survives ledger disposal

- **WHEN** implementation removes a redundant setting or flag and its temporary audit ledger is no longer available
- **THEN** the implementation commit body identifies the affected occurrence, supplied value, omitted behavior, authoritative source, tool version, and execution context, grouping occurrences only when their evidence and context agree

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
