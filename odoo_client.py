import xmlrpc.client
import urllib.parse


def _clean_fault(fault: xmlrpc.client.Fault) -> str:
    """Extract the last meaningful line from an Odoo Fault traceback."""
    msg = str(fault)
    # Last non-empty line usually has the real error (ValueError: ..., AccessError: ...)
    lines = [l.strip() for l in msg.splitlines() if l.strip()]
    for line in reversed(lines):
        if any(line.startswith(p) for p in
               ("ValueError", "AccessError", "UserError", "ValidationError",
                "MissingError", "Warning", "except_orm")):
            return line
    # Fallback: last line
    return lines[-1] if lines else msg


class _TimeoutTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout=15, use_https=True):
        super().__init__()
        self._timeout = timeout
        self._use_https = use_https

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutHTTPTransport(xmlrpc.client.Transport):
    def __init__(self, timeout=15):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _make_proxy(url: str, timeout: int = 15) -> xmlrpc.client.ServerProxy:
    parsed = urllib.parse.urlparse(url)
    transport = _TimeoutTransport(timeout) if parsed.scheme == "https" else _TimeoutHTTPTransport(timeout)
    return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str, timeout: int = 15):
        self.url = url.rstrip("/")
        self.db = db
        self.password = password

        common = _make_proxy(f"{self.url}/xmlrpc/2/common", timeout)
        info = common.version()
        self.server_version = info.get("server_version", "unknown")

        self.uid = common.authenticate(db, username, password, {})
        if not self.uid:
            raise PermissionError("Invalid credentials or database name")

        self.models = _make_proxy(f"{self.url}/xmlrpc/2/object", timeout)

    def _exec(self, model: str, method: str, args=None, kw=None):
        return self.models.execute_kw(
            self.db, self.uid, self.password,
            model, method,
            args or [],
            kw or {},
        )

    # ── READ ─────────────────────────────────────────────────────────────────
    def search_read(self, model: str, domain: list, fields: list,
                    limit: int = 50, order: str = "") -> list:
        kw = {"limit": min(int(limit), 5000)}
        if fields:
            kw["fields"] = fields
        if order:
            kw["order"] = order
        try:
            return self._exec(model, "search_read", [domain], kw)
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None

    def count(self, model: str, domain: list) -> int:
        try:
            return self._exec(model, "search_count", [domain])
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None

    def fields_get(self, model: str) -> dict:
        try:
            raw = self._exec(model, "fields_get", [],
                             {"attributes": ["string", "type", "required", "readonly"]})
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None
        return {k: v for k, v in raw.items()
                if v.get("type") not in ("binary", "many2many")}

    def name_search(self, model: str, name: str, limit: int = 10) -> list:
        try:
            return self._exec(model, "name_search", [name], {"limit": limit})
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None

    # ── CREATE ───────────────────────────────────────────────────────────────
    def create(self, model: str, values: dict) -> int:
        """Create one record, returns new record ID."""
        try:
            return self._exec(model, "create", [values])
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None

    # ── WRITE ────────────────────────────────────────────────────────────────
    def write(self, model: str, ids: list, values: dict) -> bool:
        """Update records by IDs. Returns True on success."""
        try:
            result = self._exec(model, "write", [ids, values])
            return result if result is not None else True
        except xmlrpc.client.Fault as f:
            if "cannot marshal None" in str(f):
                return True
            raise ValueError(_clean_fault(f)) from None

    # ── DELETE ───────────────────────────────────────────────────────────────
    def unlink(self, model: str, ids: list) -> bool:
        """Delete records by IDs. Returns True on success."""
        try:
            return self._exec(model, "unlink", [ids])
        except xmlrpc.client.Fault as f:
            raise ValueError(_clean_fault(f)) from None

    # ── ACTION / METHOD CALL ─────────────────────────────────────────────────
    def call_method(self, model: str, method: str,
                    ids: list, kwargs: dict = None) -> object:
        """
        Call any Odoo method on records.
        Examples:
          action_post          → confirm/post an invoice
          button_confirm       → confirm sale/purchase order
          action_confirm       → confirm sale order (alt)
          action_validate      → validate delivery / payment
          button_validate      → validate stock picking
          action_apply_inventory → apply inventory adjustment
          action_set_quantities_to_reservation → set done qty
        """
        try:
            result = self._exec(model, method, [ids], kwargs or {})
            # Some Odoo actions return None/False — normalise to True (success)
            return result if result not in (None, False) else True
        except xmlrpc.client.Fault as f:
            fault_str = str(f)
            if "cannot marshal None" in fault_str or "NoneType" in fault_str:
                return True
            raise ValueError(_clean_fault(f)) from None
