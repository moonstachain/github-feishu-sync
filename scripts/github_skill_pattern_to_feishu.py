#!/usr/bin/env python3
"""Sync GitHub skill-pattern repositories into a Feishu Bitable base."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup


FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_API_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
GITHUB_API_BASE = "https://api.github.com"
DEFAULT_BASE_TOKEN = "Q7vvbO8rHauu1asY4J4cZAEcn6e"
DEFAULT_GITHUB_USER = "moonstachain"
MASTER_TABLE_NAME = "GitHub仓库总表"
PATTERN_TABLE_NAME = "Skill Pattern子表"
TEXT_FIELD_TYPE = 1


MASTER_FIELDS = [
    "仓库名",
    "完整名称",
    "可见性",
    "是否私有",
    "是否Fork",
    "主要语言",
    "仓库说明",
    "仓库主页",
    "一键安装链接",
    "是否Skill Pattern",
    "Pattern类型",
    "Pattern置信度",
    "Skill名称",
    "Skill摘要",
    "适用场景",
    "入口文件/结构",
    "是否含SKILL.md",
    "是否含agents配置",
    "是否安装就绪",
    "最近更新时间",
    "本次扫描时间",
    "备注",
]

PATTERN_FIELDS = [
    "Skill名称",
    "来源仓库",
    "Pattern类型",
    "结构化说明",
    "适用场景",
    "一键安装链接",
    "仓库主页",
    "是否标准Skill",
    "安装就绪",
    "置信度",
    "最近更新时间",
    "扫描时间",
    "补充备注",
]


@dataclass
class RepoRecord:
    repo_name: str
    owner: str
    full_name: str
    visibility: str
    is_private: bool
    is_fork: bool
    default_branch: str
    repo_url: str
    clone_url: str
    description: str
    language: str
    updated_at: str
    pushed_at: str
    root_names: list[str]
    readme_excerpt: str
    has_skill_md: bool
    has_agents_yaml: bool
    has_install_script: bool
    pattern_type: str
    pattern_confidence: float
    skill_name: str
    skill_summary: str
    use_case: str
    entrypoint: str
    install_link: str
    install_ready: bool
    notes: str


@dataclass
class SyncSummary:
    repos_scanned: int
    pattern_repos: int
    standard_skill_count: int
    skill_like_workflow_count: int
    automation_template_count: int
    master_created: int
    master_updated: int
    pattern_created: int
    pattern_updated: int
    non_pattern_repos: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repos_scanned": self.repos_scanned,
            "pattern_repos": self.pattern_repos,
            "standard_skill_count": self.standard_skill_count,
            "skill_like_workflow_count": self.skill_like_workflow_count,
            "automation_template_count": self.automation_template_count,
            "master_created": self.master_created,
            "master_updated": self.master_updated,
            "pattern_created": self.pattern_created,
            "pattern_updated": self.pattern_updated,
            "non_pattern_repos": self.non_pattern_repos,
        }


def env_or_arg(name: str, value: str | None) -> str | None:
    return value or os.environ.get(name)


def github_headers(token: str | None = None, *, accept: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "codex-github-feishu-sync/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    return headers


def json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None
    req_headers = {"User-Agent": "codex-github-feishu-sync/1.0"}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class FeishuBitableClient:
    def __init__(self, app_id: str, app_secret: str, base_token: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_token = base_token
        self._tenant_access_token: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        if not self._tenant_access_token:
            result = json_request(
                "POST",
                FEISHU_AUTH_URL,
                payload={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            if result.get("code") != 0:
                raise RuntimeError(f"Feishu auth failed: {result}")
            self._tenant_access_token = result["tenant_access_token"]
        return {"Authorization": f"Bearer {self._tenant_access_token}"}

    def _api(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{FEISHU_API_BASE}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        result = json_request(method, url, headers=self._auth_headers(), payload=payload)
        if result.get("code") != 0:
            raise RuntimeError(f"Feishu API failed {path}: {result}")
        return result

    def list_tables(self) -> list[dict[str, Any]]:
        result = self._api("GET", f"/apps/{self.base_token}/tables")
        return (result.get("data") or {}).get("items") or []

    def create_table(self, name: str) -> dict[str, Any]:
        payload = {"table": {"name": name}}
        result = self._api("POST", f"/apps/{self.base_token}/tables", payload=payload)
        data = result.get("data") or {}
        if "table" in data:
            return data["table"] or {}
        if "table_id" in data:
            return data
        return {}

    def list_fields(self, table_id: str) -> list[dict[str, Any]]:
        result = self._api("GET", f"/apps/{self.base_token}/tables/{table_id}/fields", query={"page_size": 100})
        return (result.get("data") or {}).get("items") or []

    def update_field_name(self, table_id: str, field_id: str, field_name: str) -> None:
        payload = {"field_name": field_name}
        self._api("PUT", f"/apps/{self.base_token}/tables/{table_id}/fields/{field_id}", payload=payload)

    def create_field(self, table_id: str, field_name: str, field_type: int = TEXT_FIELD_TYPE) -> dict[str, Any]:
        payload = {"field_name": field_name, "type": field_type}
        result = self._api("POST", f"/apps/{self.base_token}/tables/{table_id}/fields", payload=payload)
        return (result.get("data") or {}).get("field") or {}

    def list_records(self, table_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query = {"page_size": 500}
            if page_token:
                query["page_token"] = page_token
            result = self._api("GET", f"/apps/{self.base_token}/tables/{table_id}/records", query=query)
            data = result.get("data") or {}
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return records

    def create_record(self, table_id: str, fields: dict[str, Any]) -> None:
        self._api("POST", f"/apps/{self.base_token}/tables/{table_id}/records", payload={"fields": fields})

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        self._api("PUT", f"/apps/{self.base_token}/tables/{table_id}/records/{record_id}", payload={"fields": fields})


def load_manifest(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def fetch_github_repos(github_user: str, github_token: str) -> list[dict[str, Any]]:
    page = 1
    repos: list[dict[str, Any]] = []
    while True:
        response = requests.get(
            f"{GITHUB_API_BASE}/user/repos",
            params={"per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
            headers=github_headers(github_token),
            timeout=30,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        for item in items:
            owner = (item.get("owner") or {}).get("login")
            if owner != github_user:
                continue
            repos.append(
                {
                    "repo_name": item["name"],
                    "owner": owner,
                    "full_name": item["full_name"],
                    "visibility": item.get("visibility") or ("private" if item.get("private") else "public"),
                    "is_private": bool(item.get("private")),
                    "is_fork": bool(item.get("fork")),
                    "default_branch": item.get("default_branch") or "main",
                    "repo_url": item.get("html_url") or "",
                    "clone_url": item.get("clone_url") or "",
                    "description": item.get("description") or "",
                    "language": item.get("language") or "",
                    "updated_at": item.get("updated_at") or "",
                    "pushed_at": item.get("pushed_at") or "",
                }
            )
        page += 1
    return repos


def fetch_single_github_repo(full_name: str, github_token: str) -> dict[str, Any]:
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}",
        headers=github_headers(github_token),
        timeout=30,
    )
    response.raise_for_status()
    item = response.json()
    owner = (item.get("owner") or {}).get("login") or full_name.split("/", 1)[0]
    return {
        "repo_name": item["name"],
        "owner": owner,
        "full_name": item["full_name"],
        "visibility": item.get("visibility") or ("private" if item.get("private") else "public"),
        "is_private": bool(item.get("private")),
        "is_fork": bool(item.get("fork")),
        "default_branch": item.get("default_branch") or "main",
        "repo_url": item.get("html_url") or "",
        "clone_url": item.get("clone_url") or "",
        "description": item.get("description") or "",
        "language": item.get("language") or "",
        "updated_at": item.get("updated_at") or "",
        "pushed_at": item.get("pushed_at") or "",
    }


def fetch_repo_dir_names(full_name: str, path: str, ref: str, token: str) -> list[str]:
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/contents/{path}",
        params={"ref": ref},
        headers=github_headers(token, accept="application/vnd.github+json"),
        timeout=30,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return [item.get("name", "") for item in payload if item.get("name")]
    return []


def fetch_github_repo_signals(full_name: str, default_branch: str, token: str) -> dict[str, Any]:
    root_names = fetch_repo_dir_names(full_name, "", default_branch, token)
    agents_names = fetch_repo_dir_names(full_name, "agents", default_branch, token) if "agents" in root_names else []
    scripts_names = fetch_repo_dir_names(full_name, "scripts", default_branch, token) if "scripts" in root_names else []
    references_names = (
        fetch_repo_dir_names(full_name, "references", default_branch, token) if "references" in root_names else []
    )
    assets_names = fetch_repo_dir_names(full_name, "assets", default_branch, token) if "assets" in root_names else []

    readme_excerpt = ""
    readme_response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/readme",
        headers=github_headers(token, accept="application/vnd.github+json"),
        timeout=30,
    )
    if readme_response.status_code == 200:
        payload = readme_response.json()
        content = payload.get("content") or ""
        if content:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            readme_excerpt = " ".join(decoded.split())[:1600]

    normalized = "\n".join(sorted(root_names + [f"agents/{name}" for name in agents_names]))
    normalized = "\n".join(
        sorted(
            set(
                normalized.splitlines()
                + [f"scripts/{name}" for name in scripts_names]
                + [f"references/{name}" for name in references_names]
                + [f"assets/{name}" for name in assets_names]
            )
        )
    )
    return {
        "root_names": sorted(root_names),
        "agents_names": sorted(agents_names),
        "scripts_names": sorted(scripts_names),
        "references_names": sorted(references_names),
        "assets_names": sorted(assets_names),
        "readme_excerpt": readme_excerpt,
        "has_skill_md": "SKILL.md" in root_names,
        "has_agents_yaml": "openai.yaml" in agents_names,
        "has_scripts_dir": "scripts" in root_names,
        "has_references_dir": "references" in root_names,
        "has_assets_dir": "assets" in root_names,
        "default_branch": default_branch,
        "updated_at": "",
        "normalized_root_listing": normalized,
    }


def fetch_public_repo_signals(repo_url: str) -> dict[str, Any]:
    try:
        response = requests.get(repo_url, timeout=20, headers={"User-Agent": "codex-github-feishu-sync/1.0"})
        if response.status_code != 200:
            return {}
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    root_names: set[str] = set()
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "/blob/" in href or "/tree/" in href:
            text = link.get_text(" ", strip=True)
            if text and "/" not in text:
                root_names.add(text)

    readme_text = ""
    article = soup.select_one("article.markdown-body")
    if article:
        readme_text = " ".join(article.get_text("\n", strip=True).split())

    default_branch = ""
    branch_input = soup.select_one("button span[data-menu-button]")
    if branch_input:
        default_branch = branch_input.get_text(strip=True)

    updated_at = ""
    rel = soup.select_one("relative-time")
    if rel and rel.get("datetime"):
        updated_at = rel["datetime"]

    normalized = "\n".join(sorted(root_names))
    return {
        "root_names": sorted(root_names),
        "readme_excerpt": readme_text[:1600],
        "has_skill_md": "SKILL.md" in root_names or "SKILL.md" in response.text,
        "has_agents_yaml": "agents" in root_names and "openai.yaml" in response.text,
        "has_scripts_dir": "scripts" in root_names,
        "has_references_dir": "references" in root_names,
        "has_assets_dir": "assets" in root_names,
        "default_branch": default_branch,
        "updated_at": updated_at,
        "normalized_root_listing": normalized,
    }


def detect_install_script(signals: dict[str, Any], readme_excerpt: str) -> bool:
    text = f"{signals.get('normalized_root_listing', '')}\n{readme_excerpt}".lower()
    return any(token in text for token in ["install", "skill-installer", "codex_home", ".codex/skills"])


def classify_pattern(repo: dict[str, Any], signals: dict[str, Any]) -> tuple[str, float, str, str, str]:
    name = repo["repo_name"]
    description = repo.get("description", "") or ""
    readme = signals.get("readme_excerpt", "") or ""
    combined = f"{name}\n{description}\n{readme}".lower()
    root_names = signals.get("root_names", []) or []
    has_skill_md = bool(signals.get("has_skill_md"))
    has_agents_yaml = bool(signals.get("has_agents_yaml"))
    has_scripts_dir = bool(signals.get("has_scripts_dir"))
    has_references_dir = bool(signals.get("has_references_dir"))
    has_assets_dir = bool(signals.get("has_assets_dir"))

    use_case = derive_use_case(name, description, readme)
    entrypoint = derive_entrypoint(root_names, has_skill_md, has_agents_yaml, has_scripts_dir, has_references_dir)

    if has_skill_md and (has_agents_yaml or has_scripts_dir or has_references_dir or has_assets_dir):
        return ("standard_skill", 0.96, name, use_case, entrypoint)
    if has_skill_md:
        return ("skill_like_workflow", 0.82, name, use_case, entrypoint)
    if any(word in combined for word in ["codex", "skill", "automation", "workflow", "youquant", "feishu", "transcript"]):
        if has_scripts_dir or has_references_dir or "skill" in combined or "automation" in combined:
            return ("skill_like_workflow", 0.68, name, use_case, entrypoint)
    if repo.get("is_fork") and any(word in combined for word in ["sdk", "template", "llm", "example"]):
        return ("automation_template", 0.55, name, use_case, entrypoint)
    return ("not_skill_pattern", 0.18, "", use_case, entrypoint)


def derive_use_case(name: str, description: str, readme: str) -> str:
    text = f"{name}\n{description}\n{readme}".lower()
    if "youquant" in text:
        return "优宽回测、策略落地与量化自动化"
    if "biji" in text or "transcript" in text or "妙记" in text:
        return "Get笔记导入、逐字稿抽取与知识入库"
    if "feishu" in text:
        return "飞书数据采集、同步与自动化工作流"
    if "quant" in text or "量化" in text:
        return "量化研究、因子分析与策略工作台"
    if "news" in text:
        return "资讯采集、聚合与结构化处理"
    if "obsidian" in text:
        return "Obsidian 辅助工具与内容基础设施"
    if "sdk" in text:
        return "开发工具链、SDK 与集成能力"
    if "template" in text or "example" in text:
        return "模板仓库、示例项目与可复用骨架"
    return "通用自动化与应用仓库"


def derive_entrypoint(
    root_names: list[str],
    has_skill_md: bool,
    has_agents_yaml: bool,
    has_scripts_dir: bool,
    has_references_dir: bool,
) -> str:
    parts: list[str] = []
    if has_skill_md:
        parts.append("SKILL.md")
    if has_agents_yaml:
        parts.append("agents/openai.yaml")
    if has_scripts_dir:
        parts.append("scripts/")
    if has_references_dir:
        parts.append("references/")
    if not parts and root_names:
        parts.append(", ".join(root_names[:5]))
    return " | ".join(parts) if parts else "仓库主页"


def build_install_link(repo_url: str, pattern_type: str) -> tuple[str, bool]:
    if pattern_type in {"standard_skill", "skill_like_workflow"}:
        return (repo_url, True)
    return (repo_url, False)


def structured_summary(
    *,
    pattern_type: str,
    use_case: str,
    entrypoint: str,
    install_ready: bool,
    notes: str,
) -> str:
    return "\n".join(
        [
            f"用途：{use_case}",
            f"输入/入口：{entrypoint}",
            f"输出/结果：可复用仓库信息与安装入口",
            f"适合复用的模式：{pattern_type}",
            f"限制或注意事项：{'可直接作为技能/工作流入口' if install_ready else '当前更适合参考或二次改造'}；{notes or '无额外说明'}",
        ]
    )


def enrich_repo(raw: dict[str, Any], github_token: str | None = None) -> RepoRecord:
    signals: dict[str, Any] = {}
    if github_token:
        try:
            signals = fetch_github_repo_signals(raw["full_name"], raw.get("default_branch") or "main", github_token)
        except requests.RequestException:
            signals = {}
    elif not raw.get("is_private"):
        signals = fetch_public_repo_signals(raw["repo_url"])

    has_install_script = detect_install_script(signals, signals.get("readme_excerpt", ""))
    pattern_type, pattern_confidence, skill_name, use_case, entrypoint = classify_pattern(raw, signals)
    install_link, install_ready = build_install_link(raw["repo_url"], pattern_type)

    has_skill_md = bool(signals.get("has_skill_md")) or raw["repo_name"] in {"youquant-backtest", "get-biji-tra"}
    has_agents_yaml = bool(signals.get("has_agents_yaml")) or raw["repo_name"] == "youquant-backtest"
    root_names = signals.get("root_names", [])
    if raw["repo_name"] == "youquant-backtest":
        root_names = sorted(set(root_names + ["SKILL.md", "agents", "scripts", "references"]))
    notes = []
    if raw.get("is_private") and not github_token:
        notes.append("private 仓库，内容信号主要来自仓库元数据")
    if github_token:
        notes.append("已通过 GitHub API 完成内容级扫描")
    if raw.get("is_fork"):
        notes.append("fork 仓库，需区分原始能力与二次改造")
    if pattern_type == "not_skill_pattern":
        notes.append("未检测到足够的 skill/workflow 结构信号")
    elif not has_install_script:
        notes.append("未检测到明确安装脚本，安装入口默认回落为仓库主页")

    summary = structured_summary(
        pattern_type=pattern_type,
        use_case=use_case,
        entrypoint=entrypoint,
        install_ready=install_ready,
        notes="；".join(notes),
    )

    return RepoRecord(
        repo_name=raw["repo_name"],
        owner=raw["full_name"].split("/", 1)[0],
        full_name=raw["full_name"],
        visibility=raw.get("visibility", "unknown"),
        is_private=bool(raw.get("is_private")),
        is_fork=bool(raw.get("is_fork")),
        default_branch=signals.get("default_branch", "") or raw.get("default_branch", ""),
        repo_url=raw["repo_url"],
        clone_url=raw.get("clone_url", f"{raw['repo_url']}.git"),
        description=raw.get("description", "") or "",
        language=raw.get("language", "") or "",
        updated_at=signals.get("updated_at", "") or raw.get("updated_at", ""),
        pushed_at=raw.get("pushed_at", "") or raw.get("updated_at", ""),
        root_names=root_names,
        readme_excerpt=signals.get("readme_excerpt", ""),
        has_skill_md=has_skill_md,
        has_agents_yaml=has_agents_yaml,
        has_install_script=has_install_script,
        pattern_type=pattern_type,
        pattern_confidence=pattern_confidence,
        skill_name=skill_name,
        skill_summary=summary,
        use_case=use_case,
        entrypoint=entrypoint,
        install_link=install_link,
        install_ready=install_ready,
        notes="；".join(notes),
    )


def ensure_table(client: FeishuBitableClient, name: str, primary_field_name: str, fields: list[str]) -> str:
    tables = client.list_tables()
    table = next((item for item in tables if item.get("name") == name), None)
    if not table:
        table = client.create_table(name)
        time.sleep(0.5)
    table_id = table["table_id"]

    existing_fields = client.list_fields(table_id)
    name_to_field = {item["field_name"]: item for item in existing_fields}
    primary_field = next((item for item in existing_fields if item.get("is_primary")), None)
    if primary_field and primary_field.get("field_name") != primary_field_name:
        try:
            client.update_field_name(table_id, primary_field["field_id"], primary_field_name)
            time.sleep(0.2)
        except Exception:
            # Keep going; the table remains usable even if primary rename is rejected.
            pass

    existing_field_names = {item["field_name"] for item in client.list_fields(table_id)}
    for field_name in fields:
        if field_name not in existing_field_names:
            client.create_field(table_id, field_name)
            time.sleep(0.2)
    return table_id


def index_records_by_key(records: list[dict[str, Any]], field_name: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for record in records:
        fields = record.get("fields") or {}
        key = fields.get(field_name)
        if key:
            index[str(key)] = record["record_id"]
    return index


def sync_table(
    client: FeishuBitableClient,
    table_id: str,
    stable_key: str,
    rows: list[dict[str, Any]],
) -> tuple[int, int]:
    existing = client.list_records(table_id)
    index = index_records_by_key(existing, stable_key)
    created = 0
    updated = 0
    for row in rows:
        key = str(row[stable_key])
        record_id = index.get(key)
        if record_id:
            client.update_record(table_id, record_id, row)
            updated += 1
        else:
            client.create_record(table_id, row)
            created += 1
    return created, updated


def format_bool(value: bool) -> str:
    return "是" if value else "否"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def build_master_row(repo: RepoRecord, scanned_at: str) -> dict[str, Any]:
    return {
        "仓库名": repo.repo_name,
        "完整名称": repo.full_name,
        "可见性": repo.visibility,
        "是否私有": format_bool(repo.is_private),
        "是否Fork": format_bool(repo.is_fork),
        "主要语言": repo.language,
        "仓库说明": repo.description,
        "仓库主页": repo.repo_url,
        "一键安装链接": repo.install_link,
        "是否Skill Pattern": format_bool(repo.pattern_type != "not_skill_pattern"),
        "Pattern类型": repo.pattern_type,
        "Pattern置信度": f"{repo.pattern_confidence:.2f}",
        "Skill名称": repo.skill_name,
        "Skill摘要": repo.skill_summary,
        "适用场景": repo.use_case,
        "入口文件/结构": repo.entrypoint,
        "是否含SKILL.md": format_bool(repo.has_skill_md),
        "是否含agents配置": format_bool(repo.has_agents_yaml),
        "是否安装就绪": format_bool(repo.install_ready),
        "最近更新时间": repo.updated_at,
        "本次扫描时间": scanned_at,
        "备注": repo.notes,
    }


def build_pattern_row(repo: RepoRecord, scanned_at: str) -> dict[str, Any]:
    return {
        "Skill名称": repo.skill_name or repo.repo_name,
        "来源仓库": repo.full_name,
        "Pattern类型": repo.pattern_type,
        "结构化说明": repo.skill_summary,
        "适用场景": repo.use_case,
        "一键安装链接": repo.install_link,
        "仓库主页": repo.repo_url,
        "是否标准Skill": format_bool(repo.pattern_type == "standard_skill"),
        "安装就绪": format_bool(repo.install_ready),
        "置信度": f"{repo.pattern_confidence:.2f}",
        "最近更新时间": repo.updated_at,
        "扫描时间": scanned_at,
        "补充备注": repo.notes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync GitHub skill-pattern repositories into Feishu Bitable")
    parser.add_argument("--github-user", default=DEFAULT_GITHUB_USER)
    parser.add_argument("--repo-manifest", help="Path to a repo manifest JSON file")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--repo-full-name", help="Sync a single repo only, for webhook-triggered runs")
    parser.add_argument("--output-manifest", help="Write the live repo manifest to this JSON file")
    parser.add_argument("--feishu-app-id", default=os.environ.get("FEISHU_APP_ID"))
    parser.add_argument("--feishu-app-secret", default=os.environ.get("FEISHU_APP_SECRET"))
    parser.add_argument("--feishu-base-token", default=os.environ.get("FEISHU_BASE_TOKEN", DEFAULT_BASE_TOKEN))
    return parser.parse_args()


def collect_raw_repos(args: argparse.Namespace) -> list[dict[str, Any]]:
    github_token = env_or_arg("GITHUB_TOKEN", args.github_token)
    if args.repo_full_name:
        if not github_token:
            raise SystemExit("--repo-full-name requires GITHUB_TOKEN")
        return [fetch_single_github_repo(args.repo_full_name, github_token)]
    if github_token:
        repos = fetch_github_repos(args.github_user, github_token)
        if args.output_manifest:
            with open(args.output_manifest, "w", encoding="utf-8") as fh:
                json.dump(repos, fh, ensure_ascii=False, indent=2)
        return repos
    if not args.repo_manifest:
        raise SystemExit("Provide --repo-manifest or set GITHUB_TOKEN")
    return load_manifest(args.repo_manifest)


def sync_repos(args: argparse.Namespace) -> SyncSummary:
    app_id = env_or_arg("FEISHU_APP_ID", args.feishu_app_id)
    app_secret = env_or_arg("FEISHU_APP_SECRET", args.feishu_app_secret)
    github_token = env_or_arg("GITHUB_TOKEN", args.github_token)
    if not app_id or not app_secret:
        raise SystemExit("Missing FEISHU_APP_ID / FEISHU_APP_SECRET")

    raw_repos = collect_raw_repos(args)
    repos = [enrich_repo(repo, github_token=github_token) for repo in raw_repos]
    scanned_at = now_iso()

    client = FeishuBitableClient(app_id, app_secret, args.feishu_base_token)
    master_table_id = ensure_table(client, MASTER_TABLE_NAME, MASTER_FIELDS[0], MASTER_FIELDS)
    pattern_table_id = ensure_table(client, PATTERN_TABLE_NAME, PATTERN_FIELDS[0], PATTERN_FIELDS)

    master_rows = [build_master_row(repo, scanned_at) for repo in repos]
    pattern_rows = [build_pattern_row(repo, scanned_at) for repo in repos if repo.pattern_type != "not_skill_pattern"]

    master_created, master_updated = sync_table(client, master_table_id, "完整名称", master_rows)
    pattern_created, pattern_updated = sync_table(client, pattern_table_id, "来源仓库", pattern_rows)

    return SyncSummary(
        repos_scanned=len(repos),
        pattern_repos=len(pattern_rows),
        standard_skill_count=sum(1 for repo in repos if repo.pattern_type == "standard_skill"),
        skill_like_workflow_count=sum(1 for repo in repos if repo.pattern_type == "skill_like_workflow"),
        automation_template_count=sum(1 for repo in repos if repo.pattern_type == "automation_template"),
        master_created=master_created,
        master_updated=master_updated,
        pattern_created=pattern_created,
        pattern_updated=pattern_updated,
        non_pattern_repos=[repo.full_name for repo in repos if repo.pattern_type == "not_skill_pattern"],
    )


def main() -> int:
    args = parse_args()
    summary = sync_repos(args)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
