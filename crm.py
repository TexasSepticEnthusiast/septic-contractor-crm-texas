"""
crm.py
A small CRM for septic and excavation contractors.

Single-file Python CLI. JSON storage. No external dependencies. Pre-loaded
with the 7-county service territory for Out West Septic.

Usage:
    python crm.py add "Jane Doe" "940-555-0123" --county "Palo Pinto" --service "New install"
    python crm.py list
    python crm.py list --county "Palo Pinto" --status lead
    python crm.py show 3
    python crm.py update 3 --status quoted --notes "Sent estimate 2026-10-15"
    python crm.py search "Doe"
    python crm.py delete 3
    python crm.py export --csv leads.csv
    python crm.py stats
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STORE = Path(os.environ.get("OWS_CRM_STORE", "./crm_store.json"))

VALID_COUNTIES = [
    "Palo Pinto", "Hood", "Erath", "Stephens",
    "Young", "Jack", "Eastland",
]

VALID_STATUSES = ["lead", "contacted", "quoted", "hired", "done", "lost"]


@dataclass
class OutWestSepticCustomer:
    id: str
    name: str
    phone: str
    email: str = ""
    address: str = ""
    county: str = ""
    service: str = ""
    status: str = "lead"
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"))
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"))


# ---------- store ----------

class OutWestSepticCRMError(ValueError):
    """A store or identifier problem that must not silently change customer data."""


class OutWestSepticCRMStore:
    def __init__(self, path: Path):
        self.path = path
        self.customers: list[OutWestSepticCustomer] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("customers"), list):
                raise ValueError("expected an object containing a customers list")
            loaded = []
            ids = set()
            for row in data["customers"]:
                if not isinstance(row, dict):
                    raise ValueError("each customer must be an object")
                customer = OutWestSepticCustomer(**row)
                if not all(isinstance(value, str) for value in asdict(customer).values()):
                    raise ValueError("customer fields must be strings")
                if not customer.id or customer.id in ids:
                    raise ValueError("customer IDs must be nonempty and unique")
                ids.add(customer.id)
                loaded.append(customer)
        except (ValueError, TypeError, UnicodeError) as exc:
            # Do not expose customer contents or pretend an unreadable store is empty.
            raise OutWestSepticCRMError("cannot load CRM store: invalid JSON or customer structure; no changes written") from exc
        self.customers = loaded

    def save(self) -> None:
        data = {"customers": [asdict(c) for c in self.customers], "saved_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, c: OutWestSepticCustomer) -> OutWestSepticCustomer:
        self.customers.append(c)
        self.save()
        return c

    def find(self, id_or_prefix: str) -> OutWestSepticCustomer | None:
        if not id_or_prefix:
            raise OutWestSepticCRMError("customer ID or prefix must not be empty")
        exact = next((c for c in self.customers if c.id == id_or_prefix), None)
        if exact is not None:
            return exact
        matches = [c for c in self.customers if c.id.startswith(id_or_prefix)]
        if len(matches) > 1:
            raise OutWestSepticCRMError("ambiguous customer ID prefix; use the full ID")
        return matches[0] if matches else None

    def update(self, id_or_prefix: str, **fields: Any) -> OutWestSepticCustomer | None:
        c = self.find(id_or_prefix)
        if not c:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        c.updated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        self.save()
        return c

    def delete(self, id_or_prefix: str) -> bool:
        c = self.find(id_or_prefix)
        if not c:
            return False
        self.customers.remove(c)
        self.save()
        return True

    def search(self, q: str) -> list[OutWestSepticCustomer]:
        ql = q.lower()
        out = []
        for c in self.customers:
            hay = " ".join([c.name, c.phone, c.email, c.address, c.county, c.service, c.notes]).lower()
            if ql in hay:
                out.append(c)
        return out

    def filter(self, county: str | None = None, status: str | None = None) -> list[OutWestSepticCustomer]:
        out = []
        for c in self.customers:
            if county and c.county.lower() != county.lower():
                continue
            if status and c.status.lower() != status.lower():
                continue
            out.append(c)
        return out


# Backward-compatible public names refer to the same implementation classes.
Customer = OutWestSepticCustomer
StoreError = OutWestSepticCRMError
Store = OutWestSepticCRMStore


# ---------- output formatting ----------

def short_id(c: OutWestSepticCustomer) -> str:
    return c.id[:8]


def fmt_table(rows: list[OutWestSepticCustomer]) -> str:
    if not rows:
        return "(no customers)"
    headers = ["ID", "Name", "Phone", "County", "Service", "Status", "Updated"]
    data = [[
        short_id(c),
        c.name,
        c.phone,
        c.county,
        c.service[:24],
        c.status,
        c.updated_at[:10],
    ] for c in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *data)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "  ".join("-" * w for w in widths)
    body = "\n".join("  ".join(str(cell).ljust(w) for cell, w in zip(row, widths)) for row in data)
    return f"{line}\n{sep}\n{body}"


# ---------- subcommands ----------

def cmd_add(args, store: OutWestSepticCRMStore) -> int:
    county = args.county or ""
    if county and county not in VALID_COUNTIES:
        print(f"warning: '{county}' is not in the service territory", file=sys.stderr)
    c = OutWestSepticCustomer(
        id=str(uuid.uuid4()),
        name=args.name,
        phone=args.phone,
        email=args.email or "",
        address=args.address or "",
        county=county,
        service=args.service or "",
        status="lead",
        notes=args.notes or "",
    )
    store.add(c)
    print(f"added {c.name} ({short_id(c)})")
    return 0


def cmd_list(args, store: OutWestSepticCRMStore) -> int:
    rows = store.filter(county=args.county, status=args.status)
    print(fmt_table(rows))
    return 0


def cmd_show(args, store: OutWestSepticCRMStore) -> int:
    c = store.find(args.id)
    if not c:
        print(f"no customer with id {args.id}", file=sys.stderr)
        return 1
    for k, v in asdict(c).items():
        print(f"{k:12} {v}")
    return 0


def cmd_update(args, store: OutWestSepticCRMStore) -> int:
    fields: dict[str, Any] = {
        "name": args.name,
        "phone": args.phone,
        "email": args.email,
        "address": args.address,
        "county": args.county,
        "service": args.service,
        "status": args.status,
        "notes": args.notes,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    c = store.update(args.id, **fields)
    if not c:
        print(f"no customer with id {args.id}", file=sys.stderr)
        return 1
    print(f"updated {c.name} ({short_id(c)})")
    return 0


def cmd_delete(args, store: OutWestSepticCRMStore) -> int:
    if not store.delete(args.id):
        print(f"no customer with id {args.id}", file=sys.stderr)
        return 1
    print(f"deleted {args.id}")
    return 0


def cmd_search(args, store: OutWestSepticCRMStore) -> int:
    rows = store.search(args.query)
    print(fmt_table(rows))
    return 0


def cmd_export(args, store: OutWestSepticCRMStore) -> int:
    rows = [asdict(c) for c in store.customers]
    if args.format == "csv":
        if not rows:
            print("(no customers)", file=sys.stderr)
            return 0
        keys = list(rows[0].keys())
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"wrote {len(rows)} customers to {args.output}")
    else:
        Path(args.output).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"wrote {len(rows)} customers to {args.output}")
    return 0


def cmd_stats(_args, store: OutWestSepticCRMStore) -> int:
    by_status: dict[str, int] = {}
    by_county: dict[str, int] = {}
    for c in store.customers:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        if c.county:
            by_county[c.county] = by_county.get(c.county, 0) + 1
    print(f"Total customers: {len(store.customers)}")
    print()
    print("By status:")
    for s in VALID_STATUSES:
        print(f"  {s:12} {by_status.get(s, 0)}")
    print()
    print("By county:")
    for county in VALID_COUNTIES:
        if county in by_county:
            print(f"  {county:12} {by_county[county]}")
    return 0


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lightweight CRM for septic and excavation contractors.")
    p.add_argument("--store", default=str(DEFAULT_STORE), help="path to the JSON store file")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="add a customer")
    pa.add_argument("name")
    pa.add_argument("phone")
    pa.add_argument("--email")
    pa.add_argument("--address")
    pa.add_argument("--county", choices=VALID_COUNTIES)
    pa.add_argument("--service", help="new install, perc test, drainfield, repair, etc.")
    pa.add_argument("--notes")

    pl = sub.add_parser("list", help="list customers")
    pl.add_argument("--county", choices=VALID_COUNTIES)
    pl.add_argument("--status", choices=VALID_STATUSES)

    ps = sub.add_parser("show", help="show one customer")
    ps.add_argument("id")

    pu = sub.add_parser("update", help="update a customer")
    pu.add_argument("id")
    pu.add_argument("--name")
    pu.add_argument("--phone")
    pu.add_argument("--email")
    pu.add_argument("--address")
    pu.add_argument("--county", choices=VALID_COUNTIES)
    pu.add_argument("--service")
    pu.add_argument("--status", choices=VALID_STATUSES)
    pu.add_argument("--notes")

    pd = sub.add_parser("delete", help="delete a customer")
    pd.add_argument("id")

    psearch = sub.add_parser("search", help="search by name, phone, notes, etc.")
    psearch.add_argument("query")

    pe = sub.add_parser("export", help="export to JSON or CSV")
    pe.add_argument("--format", choices=["json", "csv"], default="json")
    pe.add_argument("--output", required=True)

    sub.add_parser("stats", help="summary stats")

    args = p.parse_args(argv)
    handlers = {
        "add": cmd_add, "list": cmd_list, "show": cmd_show,
        "update": cmd_update, "delete": cmd_delete, "search": cmd_search,
        "export": cmd_export, "stats": cmd_stats,
    }
    try:
        store = OutWestSepticCRMStore(Path(args.store))
        return handlers[args.cmd](args, store)
    except OutWestSepticCRMError as exc:
        print(f"CRM error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
