"""Minimal Quark cloud drive client for listing folders and creating share links."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://drive-pc.quark.cn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 "
    "Electron/24.1.3.8 Safari/537.36 Channel/pckk_other_ch"
)
DEFAULT_PARAMS = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}


class QuarkError(RuntimeError):
    pass


class QuarkClient:
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie.strip()
        self.headers = {
            "cookie": self.cookie,
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        }

    def _check(self, payload: dict[str, Any], context: str) -> dict[str, Any]:
        if payload.get("code") != 0:
            raise QuarkError(f"{context}: {payload.get('message') or payload}")
        return payload["data"]

    def get_account_info(self) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                "https://pan.quark.cn/account/info",
                params={"fr": "pc", "platform": "pc"},
                headers=self.headers,
            )
        payload = resp.json()
        if not payload.get("data"):
            raise QuarkError(f"账号无效或 Cookie 过期: {payload}")
        return payload["data"]

    def get_fid_by_path(self, file_path: str) -> str | None:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{BASE_URL}/1/clouddrive/file/info/path_list",
                params=DEFAULT_PARAMS,
                headers=self.headers,
                json={"file_path": [file_path], "namespace": "0"},
            )
        payload = resp.json()
        if payload.get("code") != 0:
            raise QuarkError(f"获取路径失败 {file_path}: {payload.get('message')}")
        items = payload.get("data") or []
        if not items:
            return None
        return items[0]["fid"]

    def list_dir(self, pdir_fid: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        total = None
        with httpx.Client(timeout=30.0) as client:
            while True:
                resp = client.get(
                    f"{BASE_URL}/1/clouddrive/file/sort",
                    params={
                        **DEFAULT_PARAMS,
                        "pdir_fid": pdir_fid,
                        "_page": str(page),
                        "_size": "50",
                        "_fetch_total": "1",
                        "_fetch_sub_dirs": "0",
                        "_sort": "file_type:asc,updated_at:desc",
                        "fetch_all_file": "1",
                        "fetch_risk_file_name": "1",
                    },
                    headers=self.headers,
                )
                payload = resp.json()
                if payload.get("code") != 0:
                    raise QuarkError(f"列目录失败: {payload.get('message')}")
                batch = payload["data"]["list"]
                if not batch:
                    break
                items.extend(batch)
                total = payload["metadata"]["_total"]
                if len(items) >= total:
                    break
                page += 1
        return items

    def create_share_link(
        self,
        fid: str,
        title: str,
        *,
        url_type: int = 1,
        expired_type: int = 1,
    ) -> str:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{BASE_URL}/1/clouddrive/share",
                params=DEFAULT_PARAMS,
                headers=self.headers,
                json={
                    "fid_list": [fid],
                    "title": title,
                    "url_type": url_type,
                    "expired_type": expired_type,
                },
            )
            payload = resp.json()
            data = self._check(payload, "创建分享任务失败")
            task_id = data["task_id"]

            share_id = None
            for _ in range(20):
                task_resp = client.get(
                    f"{BASE_URL}/1/clouddrive/task",
                    params={**DEFAULT_PARAMS, "task_id": task_id, "retry_index": "0"},
                    headers=self.headers,
                )
                task_payload = task_resp.json()
                task_data = self._check(task_payload, "查询分享任务失败")
                share_id = task_data.get("share_id")
                if share_id:
                    break
                time.sleep(0.5)
            if not share_id:
                raise QuarkError(f"分享任务超时: {title}")

            pwd_resp = client.post(
                f"{BASE_URL}/1/clouddrive/share/password",
                params=DEFAULT_PARAMS,
                headers=self.headers,
                json={"share_id": share_id},
            )
            pwd_payload = pwd_resp.json()
            pwd_data = self._check(pwd_payload, "获取分享链接失败")
            share_url = pwd_data["share_url"]
            if pwd_data.get("passcode"):
                share_url = f"{share_url}?pwd={pwd_data['passcode']}"
            return share_url.split("?")[0].strip()


def load_cookie_from_qas(config_path: Path) -> str:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    cookie = data.get("cookie", "")
    if isinstance(cookie, list):
        cookie = cookie[0] if cookie else ""
    cookie = str(cookie).strip()
    if not cookie:
        raise QuarkError(f"QAS 配置里没有 Cookie: {config_path}")
    return cookie
