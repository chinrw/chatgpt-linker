## Summary

Synthetic smoke-test review, not a ChatGPT-generated or model-attested answer.
Preserve the default greeting and add an optional keyword-only prefix.

## Evidence

The draft requires preserving existing callers and avoiding dependencies [d0001:L3-L5].

## Plan

1. Add a keyword-only prefix parameter without changing positional call behavior.
2. Decide the empty-name policy explicitly before implementation.
3. Keep this review artifact outside the source project.

## Validation

Test the unchanged default, the custom prefix, and the chosen empty-name policy.

## Risks

Changing the existing default or raising on previously accepted inputs could
break callers. Roll back the signature change if compatibility tests fail.

## Open Questions

Should an empty name be rejected or given a documented fallback?
