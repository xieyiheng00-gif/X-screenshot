# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/x/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import os
from typing import Dict, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    Page,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from tools import utils
from tools.cdp_browser import CDPBrowserManager


class XCrawler(AbstractCrawler):
    """
    x.com manual browser mode.
    No crawling API calls, screenshot shortcut only.
    """

    def __init__(self) -> None:
        self.index_url = "https://x.com"
        self.browser_context: Optional[BrowserContext] = None
        self.cdp_manager: Optional[CDPBrowserManager] = None

    async def start(self) -> None:
        async with async_playwright() as playwright:
            # For x.com login stability, prefer a real local Chrome via CDP first.
            # If CDP launch fails, fall back to regular Playwright launch.
            try:
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy=None,
                    user_agent=None,
                    headless=config.CDP_HEADLESS,
                )
                utils.logger.info("[XCrawler] Running with CDP mode (real local Chrome).")
            except Exception as e:
                utils.logger.warning(f"[XCrawler] CDP mode failed, falling back to standard mode: {e}")
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy=None,
                    user_agent=None,
                    headless=config.HEADLESS,
                )
                utils.logger.info("[XCrawler] Running with standard Playwright mode.")

            page = await self.browser_context.new_page()
            await self.enable_keyboard_screenshot(page)
            await self._try_open_x(page)
            await page.evaluate(
                """
                () => {
                  if (document.getElementById("__mediaCrawlerShotBtn")) return;
                  const btn = document.createElement("button");
                  btn.id = "__mediaCrawlerShotBtn";
                  btn.type = "button";
                  btn.innerText = "Shot";
                  btn.style.position = "fixed";
                  btn.style.right = "12px";
                  btn.style.top = "12px";
                  btn.style.zIndex = "2147483647";
                  btn.style.padding = "6px 10px";
                  btn.style.background = "#111";
                  btn.style.color = "#fff";
                  btn.style.border = "1px solid #555";
                  btn.style.borderRadius = "8px";
                  btn.style.cursor = "pointer";
                  btn.style.fontSize = "12px";
                  btn.style.opacity = "1";
                  btn.style.boxShadow = "0 2px 10px rgba(0,0,0,0.4)";
                  document.documentElement.appendChild(btn);
                }
                """
            )
            await self.capture_page_screenshot(page, trigger="startup-test")

            utils.logger.info(
                "[XCrawler] x.com is ready. Press 's' or Ctrl+Shift+S to take screenshots. Press Ctrl+C to exit."
            )

            # Keep browser alive for manual browsing and screenshot capturing.
            while not page.is_closed():
                await asyncio.sleep(1)

            utils.logger.info("[XCrawler] x.com screenshot mode ended.")

    async def _try_open_x(self, page: Page) -> None:
        """
        Try to open x.com, but keep manual mode alive even if navigation times out.
        """
        try:
            await page.goto(self.index_url, wait_until="commit", timeout=90000)
        except PlaywrightTimeoutError:
            utils.logger.warning(
                "[XCrawler] Opening x.com timed out. Keeping browser open for manual navigation."
            )
            # Try login URL as a fallback, but do not fail the whole run.
            try:
                await page.goto("https://x.com/i/flow/login", wait_until="commit", timeout=60000)
            except Exception as e:
                utils.logger.warning(
                    f"[XCrawler] Fallback login URL open failed: {e}. You can open x.com manually in the browser."
                )
        except Exception as e:
            utils.logger.warning(
                f"[XCrawler] Opening x.com failed: {e}. Keeping browser open for manual navigation."
            )

    async def search(self) -> None:
        # x mode does not perform API-based crawling.
        return

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        utils.logger.info("[XCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(
                os.getcwd(),
                "browser_data",
                config.USER_DATA_DIR % config.PLATFORM,
            )
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore[arg-type]
                viewport={"width": 1440, "height": 900},
                user_agent=user_agent,
                channel="chrome",
            )
            return browser_context

        browser = await chromium.launch(
            headless=headless,
            proxy=playwright_proxy,  # type: ignore[arg-type]
            channel="chrome",
        )
        browser_context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=user_agent,
        )
        return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        self.cdp_manager = CDPBrowserManager()
        return await self.cdp_manager.launch_and_connect(
            playwright=playwright,
            playwright_proxy=playwright_proxy,
            user_agent=user_agent,
            headless=headless,
        )
