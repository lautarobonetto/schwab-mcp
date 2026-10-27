# Feature Specification: MCP Release Packaging

**Feature Branch**: `009-mcp-release-packaging`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "quiero agregar una forma simple de empaquetar este MCP y podes distribuirlo. Que incluya manuales y lo justo y necesario para que funcione de forma completa. El paquete donde se distribuye no debe contener nada de lo que estrictamente para desarrollar, para no facilitar que otro lo continue."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintainer builds a distribution package with one command (Priority: P1)

The maintainer of the project wants to produce a distributable package of the MCP server by running a single command from the repository. The command produces a self-contained package that a recipient can install and run without access to the development repository, the maintainer, or any development tooling. The build either succeeds completely, producing a package that is verifiably whole, or fails with a clear message — never producing a package that looks complete but is missing pieces.

**Why this priority**: Without a reliable, simple build step there is no distribution at all. Every other story depends on the package existing.

**Independent Test**: Can be fully tested by running the build command in a clean checkout and inspecting the resulting package for completeness (server, authentication flow, token renewal, CLI entry point, manuals) and for absence of development material.

**Acceptance Scenarios**:

1. **Given** a clean checkout of the repository at a released version, **When** the maintainer runs the single build command, **Then** a distribution package is produced in a predictable location, identifiable by the project version, within one minute.
2. **Given** the produced package, **When** its contents are inspected, **Then** it contains everything required for full operation (the server, the first-run authentication flow, automatic token renewal, the command-line entry point, and the user manuals) and nothing exclusively dedicated to development.
3. **Given** the build runs in a checkout where a required piece is missing or inconsistent, **When** the maintainer runs the build command, **Then** the build fails with an explicit error naming the problem, and no incomplete package is emitted as a valid result.
4. **Given** two consecutive builds from the same version and same inputs, **When** the produced packages are compared, **Then** they are equivalent in content (reproducible output for the same version).

---

### User Story 2 - Recipient installs and runs the MCP from the package (Priority: P2)

A person who receives the package — with no prior knowledge of the project internals — installs it on their machine by following the included installation manual, performs the first-run authentication with their own Schwab credentials, connects the MCP server to their AI client application, and successfully invokes at least one tool. The manuals walk them through every step: prerequisites, installation, first-run authentication, connecting the AI client, daily use, and what to do when something goes wrong.

**Why this priority**: The purpose of the package is to be usable by someone else without the maintainer's help; this is the value the feature delivers.

**Independent Test**: Can be fully tested by handing the package plus its manuals to a fresh machine and having a user follow only the manuals end to end (install → authenticate → connect AI client → invoke a tool successfully).

**Acceptance Scenarios**:

1. **Given** a machine that meets the documented prerequisites but has no other trace of this project, **When** the recipient follows the installation manual, **Then** the server is installed and runnable without contacting the maintainer.
2. **Given** a fresh installation with no stored credentials, **When** the recipient follows the first-run authentication manual with their own Schwab account, **Then** authentication completes and their credentials are stored only in their own local secure storage — never in the package, logs, or outputs.
3. **Given** an authenticated installation, **When** the recipient connects their AI client application following the manual and invokes a read-only tool, **Then** the tool responds with correct data.
4. **Given** an installation in daily use, **When** the access token expires, **Then** the server renews it automatically, as documented in the usage manual, without manual intervention.
5. **Given** a problem (missing prerequisite, authentication failure, connection failure), **When** the recipient consults the troubleshooting manual, **Then** they find the symptom described and a resolution path they can follow on their own.

---

### User Story 3 - The package is free of development material and secrets (Priority: P3)

The recipient of the package receives only what is necessary to install, run, and operate the server. The package contains no source code in editable form, no tests, no specifications, no plans, no development configuration, and no credentials or secrets of any kind. As a result, the recipient can use the product fully but is not handed a continuation of the development project.

**Why this priority**: It is a hard constraint on the package's content rather than an additional capability, but it must be independently verifiable before any distribution happens.

**Independent Test**: Can be fully tested by inspecting the produced package (file listing and content scans) and confirming: zero development artifacts, zero credentials/secrets, and zero editable source files.

**Acceptance Scenarios**:

1. **Given** the produced package, **When** its full file listing is reviewed, **Then** no development-only material is present (tests, specifications, plans, development scripts, development configuration, editable source).
2. **Given** the produced package, **When** its contents are scanned for secrets, **Then** no API keys, tokens, credentials, or environment files containing secrets are found.
3. **Given** the produced package, **When** the maintainer distributes it to a recipient, **Then** the recipient cannot rebuild, modify, or extend the server beyond what operation and configuration (as documented in the manuals) allow.

---

### Edge Cases

- What happens when the recipient's machine does not meet a documented prerequisite? The installation manual must describe how to detect the missing prerequisite and how to install it, and the installer/setup steps must fail with a clear, actionable message rather than a cryptic error.
- What happens when the package is built from a working copy with uncommitted changes or untagged version? The build must stamp the package with an explicit, non-ambiguous version marker so a recipient can report exactly what they run; building an unidentifiable package must require a deliberate override or fail.
- What happens when the recipient attempts the first-run authentication and their Schwab application credentials are missing or wrong? The manuals must cover this symptom and the server must reject it without ever echoing the secret material.
- What happens when the package is transferred through a channel that corrupts it? The package must include a way for the recipient to verify integrity before installing (documented in the installation manual).
- What happens when the build is run on a machine lacking the packaging prerequisites themselves? The build must fail fast with instructions, not produce a partial package.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single build command that produces a complete distribution package of the MCP server from a clean checkout of the repository.
- **FR-002**: The package MUST contain everything required for full operation: the runnable server, the first-run authentication flow, automatic token renewal, the command-line entry point, and all user manuals.
- **FR-003**: The package MUST NOT contain anything exclusively dedicated to development, including: editable source code, tests, specifications, plans, development scripts, development-only configuration, and scratch artifacts.
- **FR-004**: The package MUST NOT contain any Schwab API credentials, OAuth tokens, refresh tokens, API keys, or secret-bearing environment files (credential safety).
- **FR-005**: The package MUST be identifiable by the project version it was built from, and the version MUST be discoverable by the recipient after installation (for support and reporting).
- **FR-006**: The package MUST include user manuals covering, at minimum: prerequisites, installation, first-run authentication, connecting an AI client application, daily use and configuration, token renewal behavior, and troubleshooting of the most common failure symptoms.
- **FR-007**: The manuals MUST be written for a recipient who has no knowledge of the project's development history or internals, and MUST be written in English.
- **FR-008**: The build MUST verify completeness before declaring success: if any mandatory component (per FR-002) is missing from the produced package, the build MUST fail with an error naming the missing piece, and MUST NOT emit an incomplete package as a success.
- **FR-009**: The build MUST perform the exclusion check before declaring success: if any development-only material (per FR-003) or any secret (per FR-004) is detected inside the produced package, the build MUST fail naming the offending item.
- **FR-010**: The package MUST include an integrity verification mechanism (such as a published checksum) that a recipient can use, following the installation manual, to confirm the package was not corrupted in transit.
- **FR-011**: The build MUST be repeatable: building twice from the same version and inputs MUST produce byte-equivalent packages (byte-identical archives).
- **FR-012**: The manuals MUST document the exact prerequisites a recipient machine needs, and the installation steps MUST verify these prerequisites and fail with actionable messages when they are unmet.
- **FR-013**: The packaged server MUST preserve, in full, the runtime guarantees of the development version: local-only transport, credential safety, and read/write discipline as already implemented and documented.
- **FR-014**: The manuals MUST instruct recipients to store their own credentials only in their own local secure storage, consistent with existing credential-safety behavior.
- **FR-015**: Installing a newer package version over an existing installation MUST upgrade it in place, preserving the recipient's locally stored credentials, and the manuals MUST document this upgrade procedure.

### Key Entities *(include if feature involves data)*

- **Distribution Package**: The artifact handed to recipients. Attributes: version identifier, contents manifest, integrity verification value, the runnable server, the CLI entry point, and the manuals. Excludes, by definition, development material and secrets.
- **Build Command**: The single maintainer-facing action that produces a Distribution Package. Attributes: deterministic outcome (complete package or explicit failure), built-in completeness and exclusion checks, reproducibility for the same version.
- **User Manual**: A recipient-facing document included in every package. Kinds: installation, first-run authentication, usage/configuration, troubleshooting. Attributes: audience (non-developer recipient), completeness against FR-006.
- **Recipient Installation**: A recipient's local installation of the package. Attributes: package version, prerequisite status, locally stored credentials (owned solely by the recipient).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A recipient who meets the documented prerequisites completes installation, first-run authentication, AI-client connection, and one successful read-only tool invocation in under 15 minutes, following only the included manuals.
- **SC-002**: The maintainer produces a valid distribution package with a single command in under 1 minute from a clean checkout.
- **SC-003**: An inspection of any produced package finds zero development artifacts (tests, specs, plans, editable source, development configuration) and zero credentials or secrets — 100% compliance across builds.
- **SC-004**: Every capability available in the development environment's running server (all tools, authentication flow, automatic token renewal) is fully available in an installation created from the package.
- **SC-005**: 90% of recipient-reported issues are resolvable by the recipient alone using the troubleshooting manual, without contacting the maintainer.
- **SC-006**: Two builds from the same version and inputs produce equivalent packages in 100% of attempts (reproducibility).

## Clarifications

### Session 2026-10-26

- Q: In what physical form should the recipient receive the package — self-contained bundle, archive plus documented prerequisites, or platform installer? → A: Archive plus documented prerequisites: the package contains server, CLI, and manuals; the recipient installs the documented runtime prerequisites first.
- Q: When a recipient already has an older version installed and receives a newer package, how should the upgrade work? → A: In-place replace: install the new package over the existing installation; stored credentials remain untouched.
- Q: In which language should the recipient-facing manuals be written? → A: English only.
- Q: What exactly must FR-011 reproducibility guarantee — equivalent content or byte-identical output? → A: Byte-equivalent: two builds from the same version and inputs produce byte-identical archives.

## Assumptions

- Distribution is manual and private (the maintainer hands the package to specific recipients, e.g., via file transfer or a private release location); publishing to a public package registry is out of scope for this feature.
- The recipient audience is a single technical-but-non-developer user (the owner of the Schwab account being connected), not an anonymous public audience.
- The package targets the same operating-system family used in development, with prerequisites clearly documented in the installation manual; cross-platform packaging is out of scope for v1.
- The package is an archive that does not bundle the recipient's runtime environment itself: the runtime needed to operate the packaged server is a documented prerequisite that the recipient installs separately (per the manual), and installation from the manual must succeed on a clean machine that meets the prerequisites.
- Existing credential-safety behavior (credentials in local user-controlled secure storage only, never in logs/outputs/git) is reused as-is and documented, not redesigned.
- Development continues to happen in this repository as it does today; the packaging step adds a build-and-distribute capability without changing the development workflow.

## Dependencies

- The existing, fully functional MCP server (tools, authentication flow, token renewal, CLI) as already delivered by prior features.
- Existing credential-safety mechanisms and secure local storage behavior.
- Existing project documentation that must be adapted or excerpted into recipient-facing manuals (development docs are not shipped; recipient manuals are authored for the package).

## Out of Scope

- Publishing to any public registry or app store.
- Automatic update/upgrade mechanism for installed packages.
- Cross-platform packaging beyond the documented target environment.
- Code obfuscation or anti-reverse-engineering measures beyond excluding development material (the goal is "not facilitating continuation", not active protection).