# What is public

This edition was prepared as a clean-history portfolio repository. It contains the current clinic app, shipping and tracking logic, sanitized native adapter, authored demo fixtures, and isolated tests.

The private deployment and its Git history are not included. Legacy spreadsheet/Graph experiments, one-time setup scripts, internal operating notes, employer logos, live screenshots, recipient directories, and shipment journals are outside this public edition.

## Data boundaries

- Example recipients and names are fictional; notification emails use the reserved `example.test` domain.
- Sender identifiers and workstation paths in the example integration profile are placeholders.
- Demo tracking numbers are simulated. Screenshots show only the demo.
- Live manifests, overrides, queue databases, tracking files, environment files, and private keys are ignored by Git.
- The demo runs locally in a temporary directory and does not call FedEx or a printer.

Before publication, the source tree and new Git history are checked with a secret scanner and a separate review for organization names, personal paths, contact information, account identifiers, and operational artifacts. Automated scans are useful checks, not a guarantee that every future contribution is safe to publish.

When making changes, review the staged diff as well as `.gitignore`. Do not force-add ignored operational data or attach logs containing real recipients or tracking numbers to public issues.
