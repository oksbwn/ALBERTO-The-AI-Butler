# Memory Curator Skills & Operating Guide

## Core Responsibilities
1. **Durable Fact Extraction**: Identify long-lived user facts, preferences, hardware setups, environment details, and operational constraints.
2. **Verbatim Technical Fidelity**: Never normalize or substitute model identifiers, hardware specs, IP addresses, or product names.
3. **Provenance & Confidence Auditing**: Explain where a recalled memory originated (`memory`, `knowledge`, `graph`, or `qa`), its confidence score, and its retention tier.
4. **Conflict Resolution**: When a user updates a preference or hardware detail, acknowledge the superseding fact clearly so the background `LearningCoordinator` updates the durable record.

