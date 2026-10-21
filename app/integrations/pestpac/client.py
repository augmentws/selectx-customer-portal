"""PestPac API client.

Loads credentials from .env, manages OAuth2 password-grant tokens with a
thread-safe singleton, and exposes per-resource API sections with automatic
401 retry.

Required env vars:
    PESTPAC_CLIENT_ID
    PESTPAC_CLIENT_SECRET
    PESTPAC_USERNAME
    PESTPAC_PASSWORD
    PESTPAC_TENANT
    PESTPAC_API_KEY
    PESTPAC_BASE_URL       (optional; defaults to https://api.workwave.com/pestpac/v1)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dotenv import find_dotenv, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_ENV = PROJECT_ROOT / "src" / "scripts" / ".env"
load_dotenv(_SCRIPTS_ENV if _SCRIPTS_ENV.exists() else find_dotenv(usecwd=True))

BASE_URL = os.environ.get("PESTPAC_BASE_URL", "https://api.workwave.com/pestpac/v1")
TOKEN_URL = "https://is.workwave.com/oauth2/token?scope=openid"

log = logging.getLogger(__name__)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


@dataclass
class PestPacCredentials:
    access_token: Optional[str] = None
    tenant_id: Optional[str] = None
    api_key: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class CredentialManager:
    _instance: Optional["CredentialManager"] = None
    _lock: threading.Lock = threading.Lock()
    _token_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CredentialManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._credentials = PestPacCredentials()
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def _load_credentials(self) -> None:
        if self._initialized:
            return
        self._credentials.client_id = _env("PESTPAC_CLIENT_ID")
        self._credentials.client_secret = _env("PESTPAC_CLIENT_SECRET")
        self._credentials.username = _env("PESTPAC_USERNAME")
        self._credentials.password = _env("PESTPAC_PASSWORD")
        self._credentials.tenant_id = _env("PESTPAC_TENANT")
        self._credentials.api_key = _env("PESTPAC_API_KEY")
        self._initialized = True
        log.info("PestPac credentials loaded")

    def _fetch_new_token(self) -> str:
        token64 = base64.b64encode(
            f"{self._credentials.client_id}:{self._credentials.client_secret}".encode()
        ).decode()
        data = urlencode(
            {
                "grant_type": "password",
                "username": self._credentials.username,
                "password": self._credentials.password,
            }
        )
        response = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Bearer {token64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
        if response.status_code != 200:
            log.error("PestPac token fetch failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
        log.info("PestPac token fetched")
        return response.json()["access_token"]

    def get_token(self, force_refresh: bool = False) -> str:
        if not self._initialized:
            with self._lock:
                self._load_credentials()
        if self._credentials.access_token is None or force_refresh:
            with self._token_lock:
                if self._credentials.access_token is None or force_refresh:
                    self._credentials.access_token = self._fetch_new_token()
        return self._credentials.access_token

    def invalidate_token(self) -> None:
        with self._token_lock:
            self._credentials.access_token = None
            log.info("PestPac token invalidated")

    @property
    def tenant_id(self) -> Optional[str]:
        if not self._initialized:
            with self._lock:
                self._load_credentials()
        return self._credentials.tenant_id

    @property
    def api_key(self) -> Optional[str]:
        if not self._initialized:
            with self._lock:
                self._load_credentials()
        return self._credentials.api_key


_credential_manager: Optional[CredentialManager] = None


def get_credential_manager() -> CredentialManager:
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager


class PestPacAPISection:
    def __init__(self, base_url: str, endpoint_path: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint_path = endpoint_path
        self._credential_manager = get_credential_manager()

    def _headers(self, accept: str = "application/json", *, multipart: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._credential_manager.get_token()}",
            "Accept": accept,
            "apiKey": self._credential_manager.api_key,
            "tenant-id": self._credential_manager.tenant_id,
        }
        # For multipart uploads, let requests set Content-Type (with boundary).
        if not multipart:
            headers["Content-Type"] = "application/json"
        return headers

    def _url(self, object_id: Any = None) -> str:
        url = f"{self.base_url}{self.endpoint_path}"
        return f"{url}/{object_id}" if object_id else url

    def _request_with_retry(
        self,
        method: str,
        url: str,
        accept: str = "application/json",
        *,
        multipart: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        self._log_request(method, url, kwargs)
        response = requests.request(method, url, headers=self._headers(accept, multipart=multipart), **kwargs)
        self._log_response(method, url, response)
        if response.status_code == 401:
            log.info("401 on %s %s — refreshing token and retrying", method, url)
            self._credential_manager.invalidate_token()
            self._credential_manager.get_token(force_refresh=True)
            response = requests.request(
                method, url, headers=self._headers(accept, multipart=multipart), **kwargs
            )
            self._log_response(method, url, response, retried=True)
        return response

    @staticmethod
    def _log_request(method: str, url: str, kwargs: dict[str, Any]) -> None:
        # Headers (auth/apiKey/tenant) are intentionally not logged.
        log.info("→ %s %s", method, url)
        if "json" in kwargs and kwargs["json"] is not None:
            try:
                body = json.dumps(kwargs["json"], default=str)
            except (TypeError, ValueError):
                body = repr(kwargs["json"])
            log.info("  request body: %s", body)
        if kwargs.get("params"):
            log.info("  query params: %s", kwargs["params"])
        if kwargs.get("files"):
            log.info("  multipart files: %s", list(kwargs["files"]))

    @staticmethod
    def _log_response(
        method: str, url: str, response: requests.Response, retried: bool = False
    ) -> None:
        tag = " (retry)" if retried else ""
        text = response.text or ""
        if response.ok:
            log.info("← %d %s %s%s (%d bytes)", response.status_code, method, url, tag, len(text))
            log.info("  response body: %s", text[:4000])
        else:
            # Failures: log the full body at ERROR so it's always captured.
            log.error(
                "← %d %s %s%s FAILED\n  response: %s",
                response.status_code, method, url, tag, text[:8000],
            )

    def get(
        self, object_id: Any = None, params: Optional[dict] = None, accept: str = "application/json"
    ) -> requests.Response:
        return self._request_with_retry("GET", self._url(object_id), params=params, accept=accept)

    def post(self, data: Any, params: Optional[dict] = None) -> requests.Response:
        return self._request_with_retry("POST", self._url(), json=data, params=params)

    def post_multipart(
        self, url: str, files: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request_with_retry("POST", url, multipart=True, files=files, params=params)

    def patch(self, object_id: Any, data: Any) -> requests.Response:
        return self._request_with_retry("PATCH", self._url(object_id), json=data)

    def put(self, object_id: Any, data: Any) -> requests.Response:
        return self._request_with_retry("PUT", self._url(object_id), json=data)

    def delete(self, object_id: Any) -> requests.Response:
        return self._request_with_retry("DELETE", self._url(object_id))


def _drop_none(params: dict) -> Optional[dict]:
    """Remove keys whose value is ``None``; return ``None`` if nothing left."""
    cleaned = {k: v for k, v in params.items() if v is not None}
    return cleaned or None


class DevicesResource:
    """Devices: direct /Devices endpoints plus the /Locations/{id}/devices nested list."""

    def __init__(self, base_url: str) -> None:
        self._section = PestPacAPISection(base_url, "/Devices")
        self._base_url = base_url

    def list(
        self,
        *,
        barcode: Optional[str] = None,
        device_type: Optional[str] = None,
        location_id: Any = None,
    ) -> requests.Response:
        params = _drop_none({"barcode": barcode, "deviceType": device_type, "locationId": location_id})
        return self._section.get(params=params)

    def get(self, device_id: Any) -> requests.Response:
        return self._section.get(device_id)

    def create(self, data: Any) -> requests.Response:
        return self._section.post(data)

    def update(self, device_id: Any, data: Any) -> requests.Response:
        return self._section.put(device_id, data)

    def patch(self, device_id: Any, json_patch_ops: list) -> requests.Response:
        return self._section.patch(device_id, json_patch_ops)

    def delete(self, device_id: Any) -> requests.Response:
        return self._section.delete(device_id)

    def report_pest_findings(self, device_id: Any, finding: Any) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/Devices/{device_id}/pestFindings").post(finding)

    def list_for_location(
        self,
        location_id: Any,
        *,
        active: Optional[bool] = None,
        area_id: Any = None,
        include_orphans: Optional[bool] = None,
    ) -> requests.Response:
        params = _drop_none({
            "active": None if active is None else str(active).lower(),
            "areaId": area_id,
            "includeOrphans": None if include_orphans is None else str(include_orphans).lower(),
        })
        return PestPacAPISection(self._base_url, f"/Locations/{location_id}/devices").get(params=params)

    def search(self, barcode: str, location_id: Any) -> requests.Response:
        return self.list(barcode=barcode, location_id=location_id)


class ConditionsResource:
    """Conditions: direct /Conditions, nested /Locations/{id}/conditions, lookups."""

    def __init__(self, base_url: str) -> None:
        self._section = PestPacAPISection(base_url, "/Conditions")
        self._base_url = base_url
        self.lookups = PestPacAPISection(base_url, "/lookups/conditions")
        self.action_lookups = PestPacAPISection(base_url, "/lookups/conditions/actions")
        self.detail_lookups = PestPacAPISection(base_url, "/lookups/conditions/details")
        self.type_lookups = PestPacAPISection(base_url, "/lookups/conditions/types")

    def get(self, condition_id: Any) -> requests.Response:
        return self._section.get(condition_id)

    def get_for_location(
        self,
        location_id: Any,
        *,
        status: Optional[str] = None,
        loc_area_id: Any = None,
    ) -> requests.Response:
        params = _drop_none({"status": status, "locAreaId": loc_area_id})
        return PestPacAPISection(self._base_url, f"/Locations/{location_id}/conditions").get(params=params)

    def create(self, data: Any) -> requests.Response:
        return self._section.post(data)

    def update(self, condition_id: Any, data: Any) -> requests.Response:
        return self._section.put(condition_id, data)

    def add_inspection(self, condition_id: Any, data: Any) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/Conditions/{condition_id}/inspection").post(data)

    def mark_completed(
        self,
        condition_id: Any,
        order_id: Any,
        *,
        status: str = "Resolved",
        **extra: Any,
    ) -> requests.Response:
        """Close a condition by posting an inspection with a resolved status.

        PestPac has no dedicated 'close condition' endpoint; the API convention is to
        post a ConditionInspectionInputModel via /Conditions/{id}/inspection with a
        terminal status. Override ``status`` (or pass extra fields) if your tenant uses
        different terminology (e.g. ``Closed``).
        """
        payload: dict[str, Any] = {"OrderID": order_id, "Status": status, **extra}
        return self.add_inspection(condition_id, payload)


class ServiceOrdersResource:
    """Service orders: direct /ServiceOrders endpoints, nested lookups via
    Location / BillTo, and a bridge from user-facing OrderNumber to OrderID.
    """

    def __init__(self, base_url: str) -> None:
        self._section = PestPacAPISection(base_url, "/ServiceOrders")
        self._base_url = base_url

    def list(
        self,
        *,
        tech_id: Any = None,
        start_work_date: Optional[str] = None,
        end_work_date: Optional[str] = None,
    ) -> requests.Response:
        params = _drop_none(
            {"techId": tech_id, "startWorkDate": start_work_date, "endWorkDate": end_work_date}
        )
        return self._section.get(params=params)

    def get(self, order_id: Any) -> requests.Response:
        return self._section.get(order_id)

    def create(self, data: Any) -> requests.Response:
        return self._section.post(data)

    def update(self, order_id: Any, data: Any) -> requests.Response:
        return self._section.put(order_id, data)

    def patch(self, order_id: Any, json_patch_ops: list) -> requests.Response:
        return self._section.patch(order_id, json_patch_ops)

    def delete(self, order_id: Any) -> requests.Response:
        return self._section.delete(order_id)

    def list_for_location(self, location_id: Any) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/Locations/{location_id}/serviceOrders").get()

    def list_for_bill_to(self, bill_to_id: Any) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/BillTos/{bill_to_id}/serviceOrders").get()

    def order_id_from_number(
        self,
        order_number: Any,
        *,
        location_id: Any = None,
        bill_to_id: Any = None,
    ) -> Optional[int]:
        """Resolve a user-facing OrderNumber to the internal OrderID.

        PestPac has no direct global lookup for ServiceOrder by OrderNumber.
        The only endpoints that return both fields together are
        ``/Locations/{id}/serviceOrders`` and ``/BillTos/{id}/serviceOrders``,
        so one of those anchors is required.

        Returns the integer OrderID, or ``None`` if no match is found.
        """
        if location_id is not None:
            resp = self.list_for_location(location_id)
        elif bill_to_id is not None:
            resp = self.list_for_bill_to(bill_to_id)
        else:
            raise ValueError(
                "order_id_from_number requires either location_id or bill_to_id; "
                "PestPac has no global OrderNumber lookup."
            )
        resp.raise_for_status()
        target = str(order_number)
        for order in resp.json():
            if str(order.get("OrderNumber")) == target:
                return order.get("OrderID")
        return None


class MaterialsResource:
    """Materials: catalog via /lookups, applications via Location + ServiceOrder."""

    def __init__(self, base_url: str) -> None:
        self._lookups = PestPacAPISection(base_url, "/lookups/Materials")
        self._base_url = base_url

    def list_catalog(self, *, active: Optional[bool] = None) -> requests.Response:
        params = _drop_none({"active": None if active is None else str(active).lower()})
        return self._lookups.get(params=params)

    def get_material(self, material_id: Any) -> requests.Response:
        return self._lookups.get(material_id)

    def get_by_code(self, code: str) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/lookups/Materials/code/{code}").get()

    def list_for_location(
        self,
        location_id: Any,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> requests.Response:
        params = _drop_none({"startDate": start_date, "endDate": end_date})
        return PestPacAPISection(
            self._base_url, f"/Locations/{location_id}/materialApplications"
        ).get(params=params)

    def apply_via_service_order(self, service_order_id: Any, data: Any) -> requests.Response:
        return PestPacAPISection(self._base_url, f"/ServiceOrders/{service_order_id}/materials").post(data)

    def update_application(
        self, service_order_id: Any, line_id: Any, data: Any
    ) -> requests.Response:
        return PestPacAPISection(
            self._base_url, f"/ServiceOrders/{service_order_id}/materials"
        ).put(line_id, data)

    def remove_application(self, service_order_id: Any, line_id: Any) -> requests.Response:
        return PestPacAPISection(
            self._base_url, f"/ServiceOrders/{service_order_id}/materials"
        ).delete(line_id)


class DocumentsResource:
    """Documents: create a typed document record, then upload its file.

    For condition photos the flow is (confirmed against the live API):
      1. POST /Documents?type=ConditionDocument  with
         {ConditionID, OrderId, TimeStamp, Comment, Header}  -> returns DocumentID
      2. POST /Documents/{DocumentID}/upload?type=ConditionDocument  (multipart file)
    ConditionID is the condition's IssueID.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._section = PestPacAPISection(base_url, "/Documents")

    def create(self, body: Any, *, doc_type: str = "ConditionDocument") -> requests.Response:
        return self._section.post(body, params={"type": doc_type})

    def create_condition_document(
        self,
        condition_id: Any,
        order_id: Any,
        *,
        timestamp: str,
        comment: Optional[str] = None,
        header: Optional[str] = None,
    ) -> requests.Response:
        body = {
            "ConditionID": condition_id,
            "OrderId": order_id,
            "TimeStamp": timestamp,
            "Comment": comment,
            "Header": header,
            # Where the photo is visible in PestPac (defaults to only Auditor
            # if omitted). The live API honors Portal/MobileApp/Auditor here
            # but forces ServiceOrders back to false on both POST and PUT,
            # with or without an OrderID — likely because the document's
            # OrderID is never persisted for ConditionDocuments.
            "IncludeOn": {
                "ServiceOrders": True,
                "Portal": True,
                "MobileApp": True,
                "AutomatedInspectionReports": False,
                "Auditor": True,
                "Copesan": False,
            },
        }
        return self.create(body, doc_type="ConditionDocument")

    def upload(
        self,
        document_id: Any,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        doc_type: str = "ConditionDocument",
    ) -> requests.Response:
        url = f"{self._base_url}/Documents/{document_id}/upload"
        files = {"file": (filename, file_bytes, content_type)}
        return self._section.post_multipart(url, files=files, params={"type": doc_type})


class PestPacClient:
    def __init__(self) -> None:
        self._credential_manager = get_credential_manager()
        self.base_url = BASE_URL
        self.locations = PestPacAPISection(self.base_url, "/Locations")
        self.contacts = PestPacAPISection(self.base_url, "/Contacts")
        self.bill_tos = PestPacAPISection(self.base_url, "/BillTos")
        self.service_orders = ServiceOrdersResource(self.base_url)
        self.invoices = PestPacAPISection(self.base_url, "/Invoices")
        self.devices = DevicesResource(self.base_url)
        self.conditions = ConditionsResource(self.base_url)
        self.materials = MaterialsResource(self.base_url)
        self.documents = DocumentsResource(self.base_url)

    @property
    def auth_token(self) -> str:
        return self._credential_manager.get_token()

    def lookups(self, path: str) -> PestPacAPISection:
        return PestPacAPISection(self.base_url, f"/lookups/{path}")

    def custom_endpoint(self, path: str) -> PestPacAPISection:
        return PestPacAPISection(self.base_url, path)

    def contact_to_location(self, contact_id: Any, location_id: Any) -> requests.Response:
        path = f"/Contacts/location/{contact_id}/{location_id}"
        response = PestPacAPISection(self.base_url, path).post(None)
        if response.status_code == 400 and "is already attached to Location ID" in response.text:
            success = requests.Response()
            success.status_code = 200
            success._content = b"{}"
            return success
        return response


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    client = PestPacClient()
    try:
        resp = client.locations.get(280374)
        resp.raise_for_status()
        print(resp.json())
    except Exception as e:
        print("Failed:", e)
