import os
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from server_manager import log_exception

MODRINTH_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "MinecraftServerManager/1.0.0 (admin@local-server.manager)"


class ModrinthAPI:
    """Modrinth v2 API client supporting dependency resolution and update checking."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _request(self, endpoint: str, params: Optional[dict] = None, retries: int = 3) -> dict:
        url = f"{MODRINTH_BASE}{endpoint}" if endpoint.startswith("/") else f"{MODRINTH_BASE}/{endpoint}"
        for attempt in range(retries):
            try:
                res = self.session.get(url, params=params, timeout=12)
                if res.status_code == 429:
                    retry_after = int(res.headers.get("Retry-After", 2 ** attempt))
                    logging.warning(f"Modrinth Rate Limit reached. Backing off for {retry_after}s.")
                    time.sleep(retry_after)
                    continue
                res.raise_for_status()
                return res.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    log_exception(e, f"ModrinthAPI._request({endpoint})")
                    raise
                time.sleep(1 + attempt)
        raise RuntimeError("Exceeded maximum retries for Modrinth API.")

    def search_projects(self, query: str, loader: str, project_type: str = "mod", limit: int = 20) -> List[dict]:
        """Searches projects. Skips loader category filters for datapacks & resourcepacks."""
        facets = [
            [f"project_type:{project_type}"]
        ]
        if loader.lower() != "vanilla" and project_type in ["mod", "plugin"]:
            facets.append([f"categories:{loader.lower()}"])

        params = {
            "query": query,
            "limit": limit,
            "facets": str(facets).replace("'", '"')
        }
        data = self._request("/search", params=params)
        return data.get("hits", [])

    def get_project_versions(self, project_id: str) -> List[dict]:
        return self._request(f"/project/{project_id}/version")

    def resolve_best_version(self, project_id: str, mc_version: str, loader: str) -> Optional[dict]:
        """
        Auto-selection priority:
        1. Exact game_version match + loader match
        2. Fallback: loader-only match
        3. Fallback: newest available version
        """
        try:
            versions = self.get_project_versions(project_id)
            if not versions:
                return None

            loader = loader.lower()

            # Priority 1: Exact game_version + loader match
            for v in versions:
                if mc_version in v.get("game_versions", []) and loader in v.get("loaders", []):
                    return v

            # Priority 2: Loader match
            for v in versions:
                if loader in v.get("loaders", []):
                    return v

            # Priority 3: First available release
            return versions[0]
        except Exception as e:
            log_exception(e, f"resolve_best_version for {project_id}")
            return None

    def resolve_dependencies(self, version_data: dict, mc_version: str, loader: str) -> List[dict]:
        """Recursively resolves required dependencies for a chosen project version."""
        required_deps = []
        deps = version_data.get("dependencies", [])
        for dep in deps:
            if dep.get("dependency_type") == "required":
                dep_project_id = dep.get("project_id")
                if not dep_project_id:
                    continue
                dep_ver = self.resolve_best_version(dep_project_id, mc_version, loader)
                if dep_ver:
                    required_deps.append({
                        "project_id": dep_project_id,
                        "version_data": dep_ver
                    })
                    sub_deps = self.resolve_dependencies(dep_ver, mc_version, loader)
                    required_deps.extend(sub_deps)
        return required_deps

    def download_version_file(self, version_data: dict, target_dir: str) -> Tuple[bool, str]:
        """Downloads the primary file from a version payload into target_dir."""
        files = version_data.get("files", [])
        primary = next((f for f in files if f.get("primary")), None) or (files[0] if files else None)
        if not primary:
            return False, "No downloadable files found in version metadata."

        file_url = primary["url"]
        filename = primary["filename"]
        target_path = os.path.join(target_dir, filename)

        if os.path.exists(target_path):
            return False, f"Duplicate detected: File '{filename}' already exists."

        os.makedirs(target_dir, exist_ok=True)
        try:
            res = self.session.get(file_url, stream=True, timeout=20)
            res.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return True, filename
        except Exception as e:
            log_exception(e, f"download_version_file ({filename})")
            return False, str(e)

    def scan_installed(self, target_dir: str) -> List[dict]:
        """Lists jars in target folder with modification times and file sizes."""
        if not os.path.exists(target_dir):
            return []
        installed = []
        for item in os.listdir(target_dir):
            if item.endswith(".jar") or item.endswith(".zip"):
                p = os.path.join(target_dir, item)
                installed.append({
                    "filename": item,
                    "path": p,
                    "size_kb": round(os.path.getsize(p) / 1024, 1),
                    "modified": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                })
        return installed

    def check_update_for_file(self, filename: str, mc_version: str, loader: str) -> Optional[dict]:
        """
        Attempts to resolve an update by cleaning filename suffixes and matching Modrinth project slug.
        """
        slug_guess = filename.lower().replace(".jar", "").replace(".zip", "").split("-")[0].split("_")[0]
        try:
            hits = self.search_projects(slug_guess, loader, limit=1)
            if not hits:
                return None
            best_match = hits[0]
            latest_version = self.resolve_best_version(best_match["project_id"], mc_version, loader)
            if not latest_version:
                return None

            files = latest_version.get("files", [])
            primary = next((f for f in files if f.get("primary")), None) or (files[0] if files else None)
            if primary and primary["filename"] != filename:
                return {
                    "project_title": best_match["title"],
                    "current_filename": filename,
                    "new_filename": primary["filename"],
                    "version_data": latest_version
                }
        except Exception as e:
            log_exception(e, f"check_update_for_file for {filename}")
        return None