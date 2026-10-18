# septic-contractor-crm-texas

A small command-line CRM for septic and excavation contractors. Single Python file. JSON store on disk. No database, no server, no account. Pre-loaded with the 7-county service territory for Out West Septic.

The CRM tracks leads through the sales pipeline: lead, contacted, quoted, hired, done, lost. You can search, filter, update, and export. The whole thing is under 300 lines of Python.

## Install

No install. Stdlib only.

```
git clone https://github.com/TexasSepticEnthusiast/septic-contractor-crm-texas
cd septic-contractor-crm-texas
python crm.py --help
```

## Usage

Add a customer:

```
python crm.py add "Jane Doe" "940-555-0123" \
    --county "Palo Pinto" \
    --service "New conventional install" \
    --notes "3 bed, 2 bath, vacant lot, near Mineral Wells"
```

List everyone:

```
python crm.py list
```

Filter by county and status:

```
python crm.py list --county "Palo Pinto" --status lead
```

Show full details:

```
python crm.py show <id>
```

Update a customer (status, notes, anything):

```
python crm.py update <id> --status quoted --notes "Sent estimate 2026-10-15"
```

Search across name, phone, address, notes:

```
python crm.py search "perc"
```

Export:

```
python crm.py export --format csv --output leads.csv
python crm.py export --format json --output backup.json
```

Stats by status and county:

```
python crm.py stats
```

Delete:

```
python crm.py delete <id>
```

## Python API

`OutWestSepticCustomer`, `OutWestSepticCRMStore`, and `OutWestSepticCRMError` are the public implementation classes. `Customer`, `Store`, and `StoreError` remain exact aliases for existing callers.

This example uses a disposable store and synthetic customer data:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from crm import OutWestSepticCustomer, OutWestSepticCRMStore

with TemporaryDirectory() as directory:
    store = OutWestSepticCRMStore(Path(directory) / "customers.json")
    store.add(OutWestSepticCustomer(id="example", name="Example lead", phone=""))
    store.update("example", status="contacted")
```

## Where the data lives

The default store file is `./crm_store.json` in the current directory. Override with `--store /path/to/file.json` or set the `OWS_CRM_STORE` environment variable.

The store is a human-readable JSON file containing customer information. Keep stores and exports private; do not commit them to a public repository.

Timestamps are UTC ISO 8601 strings with microseconds so edits within the same second retain their recorded time. Existing stores with second-precision timestamps still load. `Store.update()` mutates the stored `Customer` in place; snapshot `updated_at` before an update when comparing values. Timestamps follow the system clock and are not revision identifiers.

Existing empty, malformed, or structurally invalid store files stop the command with exit code `2`; they are not treated as a new store. Back up and repair the file before retrying. A nonexistent store path starts a new store.

Customer commands accept a full ID or a unique prefix. An ambiguous or empty prefix stops with an error rather than choosing a customer. Full IDs are shown by `show` and included in exports.

## Service territory

The CRM is pre-loaded with the 7 counties Out West Septic serves: Palo Pinto, Hood, Erath, Stephens, Young, Jack, Eastland. The `add` and `update` commands accept a `--county` argument and validate against the list. Other counties are accepted as a warning.

To use the CRM for a different territory, edit `VALID_COUNTIES` at the top of `crm.py`.

## Pipeline statuses

| Status | Meaning |
| --- | --- |
| lead | First contact. Hasn't been called back yet. |
| contacted | Called, left message, awaiting reply. |
| quoted | Estimate sent. |
| hired | Contract signed, work scheduled. |
| done | Work complete, paid. |
| lost | Went elsewhere, or no longer needs the work. |

The statuses are simple. No automation. Move customers through the pipeline by running `update --status`.

## Running the tests

```
python -m unittest test_crm.py -v
```

Tests cover the store, the search/filter, and the CLI subcommands.

## What's not here

- No web UI. The CRM is a CLI. If you want a UI, point a simple HTML form at the JSON file or wrap the commands in a web service.
- No multi-user support. The JSON file is the source of truth. Two people editing at once is a problem.
- No reminders. The CRM doesn't email you or send notifications. You have to look at it.
- No quoting. The CRM tracks leads, not estimates. For estimates, use a spreadsheet or the cost-estimator in the texas-septic-toolkit.

## License

MIT. See `LICENSE`.
