# prototype-recovery Specification

## Purpose

This capability replaces the experimental inheritance-based prototype with a construction boundary that can evolve without silently changing caller-owned PyMongo behavior.

## Requirements

### Requirement: The supported API uses composition

The library SHALL expose cached database and collection facades composed around a cache manager and a caller-owned PyMongo client. It SHALL not require an application to subclass or replace its MongoClient to use the supported API.

#### Scenario: An application wraps a collection

- **WHEN** an application constructs a supported cached collection from its PyMongo collection
- **THEN** the collection retains access to the caller-owned raw collection and its client lifecycle remains caller-owned

### Requirement: Prototype migration is explicit

The repository SHALL document which prototype APIs are removed, what replaces them, and how an application can fall back to raw PyMongo while migrating. The library SHALL not advertise unimplemented cache behavior as supported.

#### Scenario: A prototype user migrates incrementally

- **WHEN** an application adopts the supported construction API for one collection
- **THEN** it can leave other collections as raw PyMongo collections without changing their behavior
