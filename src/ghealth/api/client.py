import time
from collections.abc import Callable
from typing import Any

import httpx

from ghealth.api import data_points as data_points_api
from ghealth.api import paired_devices as paired_devices_api
from ghealth.api import subscribers as subscribers_api
from ghealth.api import subscriptions as subscriptions_api
from ghealth.api import users as users_api
from ghealth.api.errors import GHealthApiError, parse_api_error
from ghealth.auth.oauth import refresh_access_token
from ghealth.auth.token_store import load_tokens, save_tokens
from ghealth.config import Config, describe_config_problem, get_config_path, load_config

MAX_PAGINATION_PAGES = 100
DEFAULT_BASE_URL = "https://health.googleapis.com"


def create_authenticated_client(
    *,
    client: httpx.Client | None = None,
) -> "GHealthApiClient":
    """Load config/tokens and return an authenticated API client."""
    config = load_config()
    if not config:
        raise GHealthApiError(
            "not_configured",
            f"Could not load Google Health configuration at {get_config_path()}. "
            f"{describe_config_problem()} "
            "If you already signed in, check this agent's credential-folder access. "
            "Otherwise run 'ghealth-mcp setup --credentials <path>'.",
        )

    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        raise GHealthApiError("not_authenticated", "Not logged in. Please run 'ghealth auth login'.")

    _ensure_fresh_tokens(config, tokens)
    return GHealthApiClient(config, tokens, client=client)


def _ensure_fresh_tokens(config: Config, tokens: dict) -> None:
    expires_at = tokens.get("expires_at", 0)
    if int(time.time()) < expires_at:
        return

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise GHealthApiError(
            "not_authenticated",
            "Access token expired and no refresh token is available. Please run 'ghealth auth login'.",
        )

    try:
        new_tokens = refresh_access_token(config, refresh_token)
    except Exception as e:
        raise GHealthApiError("refresh_failed", f"Failed to refresh access token: {e}") from e

    if "scope" not in new_tokens and "scope" in tokens:
        new_tokens["scope"] = tokens["scope"]

    tokens.clear()
    tokens.update(new_tokens)
    save_tokens(new_tokens)


class GHealthApiClient:
    def __init__(
        self,
        config: Config,
        tokens: dict,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._tokens = tokens
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_identity(self) -> dict:
        return self._request("GET", users_api.identity_path())

    def get_profile(self) -> dict:
        return self._request("GET", users_api.profile_path())

    def get_settings(self) -> dict:
        return self._request("GET", users_api.settings_path())

    def list_paired_devices(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        return self._request(
            "GET",
            paired_devices_api.list_path(),
            params=paired_devices_api.list_params(page_size=page_size, page_token=page_token),
        )

    def get_paired_device(self, device: str) -> dict:
        return self._request("GET", paired_devices_api.get_path(device))

    def list_data_points(
        self,
        data_type: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        filter: str | None = None,
    ) -> dict:
        return self._request(
            "GET",
            data_points_api.list_path(data_type),
            params=data_points_api.list_params(page_size=page_size, page_token=page_token, filter=filter),
        )

    def get_data_point(self, data_type: str, data_point: str) -> dict:
        return self._request("GET", data_points_api.get_path(data_type, data_point))

    def create_data_point(self, data_type: str, data_point: dict) -> dict:
        return self._request("POST", data_points_api.create_path(data_type), json_body=data_point)

    def update_data_point(
        self,
        data_type: str,
        data_point: str,
        data_point_body: dict,
        *,
        update_mask: str | None = None,
    ) -> dict:
        return self._request(
            "PATCH",
            data_points_api.update_path(data_type, data_point),
            params=data_points_api.update_params(update_mask=update_mask),
            json_body=data_point_body,
        )

    def batch_delete_data_points(self, data_type: str, names: list[str]) -> dict:
        return self._request(
            "POST",
            data_points_api.batch_delete_path(data_type),
            json_body=data_points_api.batch_delete_body(names),
        )

    def export_exercise_tcx(
        self,
        data_point: str,
        *,
        partial_data: bool | None = None,
    ) -> str:
        return self._request_text(
            "GET",
            data_points_api.export_exercise_tcx_path(data_point),
            params=data_points_api.export_exercise_tcx_params(partial_data=partial_data),
        )

    def list_subscribers(
        self,
        project: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        return self._request(
            "GET",
            subscribers_api.list_path(project),
            params=subscribers_api.list_params(page_size=page_size, page_token=page_token),
        )

    def create_subscriber(
        self,
        project: str,
        subscriber: dict,
        *,
        subscriber_id: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            subscribers_api.create_path(project),
            params=subscribers_api.create_params(subscriber_id=subscriber_id),
            json_body=subscriber,
        )

    def update_subscriber(
        self,
        subscriber_name: str,
        subscriber: dict,
        *,
        update_mask: str | None = None,
    ) -> dict:
        return self._request(
            "PATCH",
            subscribers_api.resource_path(subscriber_name),
            params=subscribers_api.update_params(update_mask=update_mask),
            json_body=subscriber,
        )

    def delete_subscriber(self, subscriber_name: str, *, force: bool = False) -> dict:
        return self._request(
            "DELETE",
            subscribers_api.resource_path(subscriber_name),
            params=subscribers_api.delete_params(force=force),
        )

    def list_subscriptions(
        self,
        subscriber_name: str,
        *,
        filter: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        return self._request(
            "GET",
            subscriptions_api.list_path(subscriber_name),
            params=subscriptions_api.list_params(
                filter=filter,
                page_size=page_size,
                page_token=page_token,
            ),
        )

    def create_subscription(
        self,
        subscriber_name: str,
        subscription: dict,
        *,
        subscription_id: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            subscriptions_api.create_path(subscriber_name),
            params=subscriptions_api.create_params(subscription_id=subscription_id),
            json_body=subscription,
        )

    def update_subscription(
        self,
        subscription_name: str,
        subscription: dict,
        *,
        update_mask: str | None = None,
    ) -> dict:
        return self._request(
            "PATCH",
            subscriptions_api.resource_path(subscription_name),
            params=subscriptions_api.update_params(update_mask=update_mask),
            json_body=subscription,
        )

    def delete_subscription(self, subscription_name: str) -> dict:
        return self._request("DELETE", subscriptions_api.resource_path(subscription_name))

    def reconcile_data_points(
        self,
        data_type: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        filter: str | None = None,
        data_source_family: str | None = None,
    ) -> dict:
        return self._request(
            "GET",
            data_points_api.reconcile_path(data_type),
            params=data_points_api.reconcile_params(
                page_size=page_size,
                page_token=page_token,
                filter=filter,
                data_source_family=data_source_family,
            ),
        )

    def rollup_data_points(
        self,
        data_type: str,
        *,
        start_time: str,
        end_time: str,
        window_size: str,
        page_size: int | None = None,
        page_token: str | None = None,
        data_source_family: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            data_points_api.rollup_path(data_type),
            json_body=data_points_api.rollup_body(
                start_time=start_time,
                end_time=end_time,
                window_size=window_size,
                page_size=page_size,
                page_token=page_token,
                data_source_family=data_source_family,
            ),
        )

    def daily_rollup_data_points(
        self,
        data_type: str,
        *,
        start_date: str,
        end_date: str,
        window_size_days: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        data_source_family: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            data_points_api.daily_rollup_path(data_type),
            json_body=data_points_api.daily_rollup_body(
                start_date=start_date,
                end_date=end_date,
                window_size_days=window_size_days,
                page_size=page_size,
                page_token=page_token,
                data_source_family=data_source_family,
            ),
        )

    def list_all_paired_devices(self, *, page_size: int | None = None, limit: int | None = None) -> dict:
        return self._paginate_all(
            lambda page_token: self.list_paired_devices(page_size=page_size, page_token=page_token),
            "pairedDevices",
            limit=limit,
        )

    def list_all_data_points(
        self,
        data_type: str,
        *,
        page_size: int | None = None,
        filter: str | None = None,
        limit: int | None = None,
    ) -> dict:
        return self._paginate_all(
            lambda page_token: self.list_data_points(
                data_type,
                page_size=page_size,
                page_token=page_token,
                filter=filter,
            ),
            "dataPoints",
            limit=limit,
        )

    def list_all_reconciled_data_points(
        self,
        data_type: str,
        *,
        page_size: int | None = None,
        filter: str | None = None,
        data_source_family: str | None = None,
        limit: int | None = None,
    ) -> dict:
        return self._paginate_all(
            lambda page_token: self.reconcile_data_points(
                data_type,
                page_size=page_size,
                page_token=page_token,
                filter=filter,
                data_source_family=data_source_family,
            ),
            "dataPoints",
            limit=limit,
        )

    def list_all_rollup_data_points(
        self,
        data_type: str,
        *,
        start_time: str,
        end_time: str,
        window_size: str,
        page_size: int | None = None,
        data_source_family: str | None = None,
        limit: int | None = None,
    ) -> dict:
        return self._paginate_all(
            lambda page_token: self.rollup_data_points(
                data_type,
                start_time=start_time,
                end_time=end_time,
                window_size=window_size,
                page_size=page_size,
                page_token=page_token,
                data_source_family=data_source_family,
            ),
            "rollupDataPoints",
            limit=limit,
        )

    def list_all_subscribers(
        self, project: str, *, page_size: int | None = None, limit: int | None = None
    ) -> dict:
        return self._paginate_all(
            lambda page_token: self.list_subscribers(project, page_size=page_size, page_token=page_token),
            "subscribers",
            limit=limit,
        )

    def list_all_subscriptions(
        self,
        subscriber_name: str,
        *,
        filter: str | None = None,
        page_size: int | None = None,
        limit: int | None = None,
    ) -> dict:
        return self._paginate_all(
            lambda page_token: self.list_subscriptions(
                subscriber_name,
                filter=filter,
                page_size=page_size,
                page_token=page_token,
            ),
            "subscriptions",
            limit=limit,
        )

    def _paginate_all(
        self,
        fetch_page: Callable[[str | None], dict],
        list_key: str,
        *,
        limit: int | None = None,
    ) -> dict:
        all_items: list[dict] = []
        page_token: str | None = None

        for _ in range(MAX_PAGINATION_PAGES):
            result = fetch_page(page_token)
            all_items.extend(result.get(list_key, []))
            if limit is not None and len(all_items) >= limit:
                return {list_key: all_items[:limit]}
            page_token = result.get("nextPageToken")
            if not page_token:
                return {list_key: all_items}

        raise GHealthApiError(
            "pagination_limit_exceeded",
            f"Pagination limit of {MAX_PAGINATION_PAGES} pages exceeded.",
            details={"last_page_token": page_token},
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "Accept": "application/json",
        }

    def _refresh_tokens(self) -> None:
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise GHealthApiError(
                "not_authenticated",
                "Access token expired and no refresh token is available. Please run 'ghealth auth login'.",
            )
        try:
            new_tokens = refresh_access_token(self._config, refresh_token)
        except Exception as e:
            raise GHealthApiError(
                "refresh_failed",
                f"Failed to refresh access token: {e}",
            ) from e

        if "scope" not in new_tokens and "scope" in self._tokens:
            new_tokens["scope"] = self._tokens["scope"]

        self._tokens.clear()
        self._tokens.update(new_tokens)
        save_tokens(new_tokens)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        _retry_auth: bool = True,
    ) -> dict:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise GHealthApiError(
                "api_request_failed",
                f"API request failed: {e}",
                details={"path": path},
            ) from e

        if response.status_code == 401 and _retry_auth and self._tokens.get("refresh_token"):
            self._refresh_tokens()
            return self._request(method, path, params=params, json_body=json_body, _retry_auth=False)

        if response.is_success:
            try:
                data = response.json()
            except ValueError as e:
                raise GHealthApiError(
                    "api_invalid_response",
                    "Failed to parse JSON response from API.",
                    status_code=response.status_code,
                    details={"path": path},
                ) from e
            if not isinstance(data, dict):
                raise GHealthApiError(
                    "api_invalid_response",
                    "Expected JSON object response from API.",
                    status_code=response.status_code,
                    details={"path": path},
                )
            return data

        raise parse_api_error(response, path)

    def _request_text(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        _retry_auth: bool = True,
    ) -> str:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise GHealthApiError(
                "api_request_failed",
                f"API request failed: {e}",
                details={"path": path},
            ) from e

        if response.status_code == 401 and _retry_auth and self._tokens.get("refresh_token"):
            self._refresh_tokens()
            return self._request_text(method, path, params=params, _retry_auth=False)

        if response.is_success:
            return response.text

        raise parse_api_error(response, path)
