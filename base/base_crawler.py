# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/base/base_crawler.py
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

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from playwright.async_api import BrowserContext, BrowserType, Page, Playwright


class AbstractCrawler(ABC):

    @abstractmethod
    async def start(self):
        """
        start crawler
        """
        pass

    @abstractmethod
    async def search(self):
        """
        search
        """
        pass

    @abstractmethod
    async def launch_browser(self, chromium: BrowserType, playwright_proxy: Optional[Dict], user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        """
        launch browser
        :param chromium: chromium browser
        :param playwright_proxy: playwright proxy
        :param user_agent: user agent
        :param headless: headless mode
        :return: browser context
        """
        pass

    async def launch_browser_with_cdp(self, playwright: Playwright, playwright_proxy: Optional[Dict], user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        """
        Launch browser using CDP mode (optional implementation)
        :param playwright: playwright instance
        :param playwright_proxy: playwright proxy configuration
        :param user_agent: user agent
        :param headless: headless mode
        :return: browser context
        """
        # Default implementation: fallback to standard mode
        return await self.launch_browser(playwright.chromium, playwright_proxy, user_agent, headless)

    async def enable_keyboard_screenshot(self, page: Page) -> None:
        """
        Enable a manual screenshot shortcut on the current Playwright page.
        Hotkeys: `s` or `Ctrl+Shift+S`.
        """
        if getattr(self, "_manual_screenshot_enabled", False):
            return

        screenshot_dir = Path(os.getcwd()) / "screenshots"

        async def _capture(trigger: str = "s") -> str:
            return await self.capture_page_screenshot(page, screenshot_dir, trigger)

        context = page.context

        install_hotkey_script = """
            () => {
              if (window.__mediaCrawlerScreenshotHookInstalled) return;
              window.__mediaCrawlerScreenshotHookInstalled = true;

              const isEditable = (target) => {
                if (!target) return false;
                if (target.isContentEditable) return true;
                const tag = target.tagName ? target.tagName.toLowerCase() : "";
                return tag === "input" || tag === "textarea" || tag === "select";
              };

              window.addEventListener("keydown", (event) => {
                const key = (event.key || "").toLowerCase();
                const hitSimple = key === "s" && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
                const hitCombo = key === "s" && ((event.ctrlKey && event.shiftKey) || (event.metaKey && event.shiftKey));
                if (!hitSimple && !hitCombo) return;

                // Keep typing behavior for plain "s" in editable fields.
                if (hitSimple && isEditable(event.target)) return;

                const trigger = hitCombo ? "Ctrl/Cmd+Shift+S" : "s";
                if (typeof window.__mediaCrawlerCaptureScreenshot === "function") {
                  window.__mediaCrawlerCaptureScreenshot(trigger).catch((error) => {
                    console.error("[Screenshot] capture failed:", error);
                  });
                }
              }, true);

              // Fallback debug button: verifies screenshot binding even if keyboard shortcuts are blocked.
              const addShotButton = () => {
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
                btn.style.pointerEvents = "auto";
                btn.addEventListener("click", () => {
                  if (typeof window.__mediaCrawlerCaptureScreenshot === "function") {
                    window.__mediaCrawlerCaptureScreenshot("button").catch((error) => {
                      console.error("[Screenshot] button capture failed:", error);
                    });
                  }
                });
                document.documentElement.appendChild(btn);
              };

              if (document.readyState === "loading") {
                document.addEventListener("DOMContentLoaded", addShotButton, { once: true });
              } else {
                addShotButton();
              }
            }
            """

        await context.expose_function("__mediaCrawlerCaptureScreenshot", _capture)
        # add_init_script needs executable script text (not only a function literal).
        await context.add_init_script(script=f"({install_hotkey_script})();")
        # Also install immediately on the current page (not only on future navigations).
        await page.evaluate(install_hotkey_script)
        self._manual_screenshot_enabled = True

    async def capture_page_screenshot(self, page: Page, screenshot_dir: Optional[Path] = None, trigger: str = "manual") -> str:
        """
        Capture one screenshot for the given page and print saved path.
        """
        target_dir = screenshot_dir or (Path(os.getcwd()) / "screenshots")
        target_dir.mkdir(parents=True, exist_ok=True)

        # Save screenshots as sequential numbers: 1.png, 2.png, 3.png, ...
        existing_indices = [
            int(file.stem)
            for file in target_dir.glob("*.png")
            if file.stem.isdigit()
        ]
        next_index = max(existing_indices, default=0) + 1
        file_path = target_dir / f"{next_index}.png"
        while file_path.exists():
            next_index += 1
            file_path = target_dir / f"{next_index}.png"

        await page.screenshot(path=str(file_path))
        saved_path = str(file_path.resolve())
        print(f"[Screenshot] ({trigger}) saved: {saved_path}")
        return saved_path


class AbstractLogin(ABC):

    @abstractmethod
    async def begin(self):
        pass

    @abstractmethod
    async def login_by_qrcode(self):
        pass

    @abstractmethod
    async def login_by_mobile(self):
        pass

    @abstractmethod
    async def login_by_cookies(self):
        pass


class AbstractStore(ABC):

    @abstractmethod
    async def store_content(self, content_item: Dict):
        pass

    @abstractmethod
    async def store_comment(self, comment_item: Dict):
        pass

    # TODO support all platform
    # only xhs is supported, so @abstractmethod is commented
    @abstractmethod
    async def store_creator(self, creator: Dict):
        pass


class AbstractStoreImage(ABC):
    # TODO: support all platform
    # only weibo is supported
    # @abstractmethod
    async def store_image(self, image_content_item: Dict):
        pass


class AbstractStoreVideo(ABC):
    # TODO: support all platform
    # only weibo is supported
    # @abstractmethod
    async def store_video(self, video_content_item: Dict):
        pass


class AbstractApiClient(ABC):

    @abstractmethod
    async def request(self, method, url, **kwargs):
        pass

    @abstractmethod
    async def update_cookies(self, browser_context: BrowserContext):
        pass
