---
name: Feature request
about: Propose a capability for the instructor station
title: ''
labels: enhancement
assignees: ''
---

## The problem

<!-- What can an instructor not do today? Describe the training situation, not the solution. -->

## Proposed feature

<!--
Which of the 15 managers in docs/feature-spec.md does this belong to — or is it a new one?
Check docs/roadmap.md first: it may already be scheduled in a later phase.
-->

## Simulator support

| | |
|---|---|
| **X-Plane 12** | supported / unknown / impossible |
| **MSFS** | supported / unknown / impossible |

If a simulator cannot do it, that is fine — it becomes a **capability flag** the adapter
declares, and the UI disables the feature instead of failing at runtime. Say which capability
you think it needs (`can_set_position`, `can_set_weather`, `can_inject_failures`,
`can_spawn_traffic`, …), or that it needs a new one.

## Anything that constrains the design

<!-- Does it require navdata? An in-sim bridge plugin? Does it work without one? -->
