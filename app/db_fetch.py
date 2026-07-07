# -*- coding: utf-8 -*-
"""從 GitHub Release 下載資料庫並快取到本地暫存。"""
import os
import tempfile

import requests


def ensure_db(repo: str, tag: str = "data", asset: str = "tw_stock_v2.db",
              cache_dir: str | None = None) -> str:
    """回傳本地 DB 路徑；不存在時從 GitHub Release 下載。

    repo: 例如 "username/stock-box-system"（公開 repo 免 token）。
    """
    cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "stock-box-system")
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, asset)

    url = f"https://github.com/{repo}/releases/download/{tag}/{asset}"

    # 以 release 的 ETag/長度判斷是否需要重抓（每日更新後檔案長度幾乎必變）
    head = requests.head(url, allow_redirects=True, timeout=30)
    head.raise_for_status()
    remote_size = int(head.headers.get("Content-Length", 0))

    if os.path.exists(local_path) and os.path.getsize(local_path) == remote_size:
        return local_path

    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        tmp = local_path + ".tmp"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        os.replace(tmp, local_path)
    return local_path
