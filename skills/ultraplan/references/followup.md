# Continue a review with new evidence

Use this branch for a requested follow-up or a justified additional round within
the main skill's bounded continuation authorization. Check the remaining round
allowance and existing children before preparing another request. A
conversation groups immutable rounds; each child has its own request ID, bundle
hash and single result. The user need not rebuild the handoff from scratch.

1. Resolve the intended parent using its exact ID or `list --project /abs/project`.
   Infer the project and likely parent from the current task; the user need not
   supply an ID or a file list. Inspect status and the complete paginated result,
   including source drift.
   Use `list --conversation <conversation_id>` to see rounds and branches.
   A prepared or waiting task should be resumed; cancelled or corrupt results
   cannot serve as parents. Ask about ambiguous branches instead of guessing.
2. Refresh the current context and effective task rules. The parent report and
   its original plan/question will be carried as historical evidence, not as
   current instructions. Review which current files and new measurements the
   question needs by checking diffs, callers, tests and existing logs. Run relevant
   tests when the original task authorizes them, and distinguish passed, failed
   and unrun checks. By default the CLI refreshes previously selected local files and adds
   explicit `--file` inputs under the parent's current policy. For public mode,
   it revalidates the public baseline and recomputes the overlay, including
   deletions, while preserving explicit supplemental selections.
3. Prepare the next round without editing source files:

   ```sh
   chatgpt-linker --state "$STATE" followup "$PARENT_ID" \
     --goal 'Reassess the revised implementation and remaining questions' \
     --file relative/path/new-evidence.md --draft-stdin <<'FOLLOWUP_CONTEXT'
   # Current review context
   ## Effective task rules
   Describe current applicable rules and their scope.
   ## Changes and questions
   Describe what changed and the precise questions for this round.
   FOLLOWUP_CONTEXT
   ```

   If prior selections are obsolete, add `--replace-files` and supply the current
   complete selection through repeated `--file`. Use `--selection-note` to explain
   which old files were deleted, replaced or no longer relevant, based on your
   investigation. The CLI freezes the omitted paths and explanation; it does not
   infer deletion merely from omission. In public mode this replaces only explicit
   supplements; the current public overlay is still recomputed. Keep any earlier
   evidence still needed by the question in the new selection. An empty selection
   is appropriate only for a context-only question, with an explicit explanation.

   Only add relevant, authorized materials. The command rereads current source,
   rechecks policy, and rescans historical context/report under current sensitive
   rules. Resolve deleted or obsolete inputs by explicitly reselecting evidence;
   do not silently omit still-needed files. Policy exclusions, scan failures and
   size limits remain publication constraints. Reselecting does not widen policy. Check returned files and
   skipped evidence. A context-only question may omit `--file`; agent-driven
   follow-ups should still supply updated context and rules through stdin.
4. Record the prepared child ID against the current delegation's round allowance.
   Publish under the user's explicit follow-up or bounded continuation authorization: `publish <child_id> --approve`. A single command may use
   `followup ... --publish --approve` after its scope has been reviewed. Bare
   `--publish` requires existing policy auto_publish. An approval error retains
   the prepared child ID; publish that same child rather than creating duplicates.
   Prior approval or processing of the parent does not authorize arbitrary new
   evidence. The child stays on the parent's exchange node; resolve errors there.
5. Generate `prompt <child_id>` and present that exact prompt. The user may send
   it in the existing ordinary Chat conversation or a new one with ChatGPT Linker
   selected. ChatGPT reads the evidence and submits the report in that conversation;
   use manual import if write tools are unavailable. Linker neither records
   nor controls a ChatGPT conversation URL. The child includes the immediate
   parent's complete report and plan/question, so it does not require access to
   the parent's expired or subsequently revoked tool grant. It does not carry
   every ancestor's report or the original source snapshots. Summarize older
   decisions relevant to this round in the updated context.
6. Return to the main skill's Hand off, Receive, and Validate steps, always using
   the child ID and hash. Previous report citations refer to the parent round;
   the reviewer must substantiate the new answer against the child's evidence.
   After complete validation, mark only the report actually processed. Keep
   earlier results and branches intact, and continue the original task within
   its existing authorization.
