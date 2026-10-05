# Results and timing evidence

## Current workflow

The implementation was used in a real Windows shipping workflow. Successful labels and their exact-reference tracking matches were observed. Additional requests can be queued while one request is processing; the next label remains subject to printer confirmation.

The public demo reproduces those interactions without making shipments. Its fictional results are not production evidence or benchmarks.

## Earlier prototype observations

Private development logs recorded the following elapsed seconds from runner start to print confirmation. This table is a sanitized transcription: recipient names, request IDs, tracking numbers, printer event IDs, and raw logs are deliberately omitted.

| Shipment type | Earlier runner | After removing foreground tracking work | Observed difference |
| --- | ---: | ---: | ---: |
| Supplies | 26.631 s | 20.452 s | 6.179 s |
| Medication | 31.319 s | 25.065 s | 6.254 s |

The comparison uses the same **print-confirmation milestone** in both versions. It does not mix print time with the later completion of tracking lookup.

### A 28-label day

The operator supplied 28 distinct shipments / 28 separate labels as a busy-day scenario. Applying the observed differences to that volume:

- All supplies: `28 × 6.179 = 173.012 seconds`, or **2.88 minutes**.
- All medication: `28 × 6.254 = 175.112 seconds`, or **2.92 minutes**.
- A mix falls between those values: approximately **2.9 minutes of elapsed runner time**.

These calculations extrapolate the earlier runner observations. They do not establish a daily labor saving or current native-integration speedup.

## Limits

- These are individual before/after observations, with different shipments, rather than repeated controlled trials.
- No timed manual-workflow baseline or current hands-on-time measurement was found in the reviewed research.
- The final implementation uses native folder polling. An earlier native test confirmed a print about 40.2 seconds after publication with a 60-second polling interval; it is a different architecture and cannot be substituted into the earlier speedup comparison.
- Tracking collection does not block the Python shipping worker. Native export overhead has not been independently measured.
- Operational benefits such as fewer repeated entry steps and continued preparation during printing are implemented behaviors, not quantified productivity claims.

To measure labor savings, time the operator's active work per label before and after the app, using comparable shipment types and several repetitions. Then compute `(manual hands-on seconds - app hands-on seconds) × 28`. Keep printer/polling waits separate from active work.
