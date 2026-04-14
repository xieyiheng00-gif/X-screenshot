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
from io import BytesIO
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from PIL import Image
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
        Hotkeys:
        - `c`: toggle long screenshot range (start / stop and save).
        - `Ctrl+Shift+C` or `Cmd+Shift+C`: instant screenshot.
        """
        if getattr(self, "_manual_screenshot_enabled", False):
            return

        self._long_screenshot_active = False
        self._long_screenshot_start_y = 0.0
        self._screenshot_busy = False

        screenshot_dir = Path(os.getcwd()) / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_root_dir = screenshot_dir
        self._active_screenshot_dir = screenshot_dir

        async def _capture(trigger: str = "manual") -> str:
            if self._screenshot_busy:
                print("[Screenshot] Busy, ignore new capture request.")
                return ""
            self._screenshot_busy = True
            try:
                return await self.capture_page_screenshot(page, trigger=trigger)
            finally:
                self._screenshot_busy = False

        async def _toggle_long_capture(scroll_y: float = 0.0) -> str:
            if self._screenshot_busy:
                print("[Screenshot] Busy, ignore long screenshot toggle.")
                return ""

            current_scroll_y = await self._get_effective_scroll_y(page)

            if not self._long_screenshot_active:
                self._long_screenshot_active = True
                self._long_screenshot_start_y = max(0.0, float(current_scroll_y))
                print(
                    f"[LongShot] Started at Y={int(self._long_screenshot_start_y)}. "
                    "Scroll to target end and press 'c' again."
                )
                return "started"

            self._screenshot_busy = True
            try:
                end_y = max(0.0, float(current_scroll_y))
                start_y = self._long_screenshot_start_y
                self._long_screenshot_active = False
                return await self.capture_long_screenshot(
                    page=page,
                    start_y=start_y,
                    end_y=end_y,
                    trigger="c",
                )
            finally:
                self._screenshot_busy = False

        async def _create_screenshot_folder() -> str:
            root_dir = getattr(self, "_screenshot_root_dir", screenshot_dir)
            folder_path = await self._create_new_screenshot_folder(root_dir)
            self._active_screenshot_dir = folder_path
            message = f"[Screenshot] Active folder: {folder_path.resolve()}"
            print(message)
            return message

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

              const stopEvent = (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (typeof event.stopImmediatePropagation === "function") {
                  event.stopImmediatePropagation();
                }
              };

              const handleHotkey = (event, shouldTrigger) => {
                const key = (event.key || "").toLowerCase();
                const hitSimple = key === "c" && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
                const hitCombo = key === "c" && ((event.ctrlKey && event.shiftKey) || (event.metaKey && event.shiftKey));
                if (!hitSimple && !hitCombo) return;

                // Keep typing behavior for plain "c" in editable fields.
                if (hitSimple && isEditable(event.target)) return;
                stopEvent(event);

                if (!shouldTrigger) return;

                if (hitSimple) {
                  if (typeof window.__mediaCrawlerToggleLongScreenshot === "function") {
                    window.__mediaCrawlerToggleLongScreenshot(window.scrollY || 0).catch((error) => {
                      console.error("[LongShot] toggle failed:", error);
                    });
                  }
                  return;
                }

                if (typeof window.__mediaCrawlerCaptureScreenshot === "function") {
                  window.__mediaCrawlerCaptureScreenshot("Ctrl/Cmd+Shift+C").catch((error) => {
                    console.error("[Screenshot] capture failed:", error);
                  });
                }
              };

              // Intercept all key phases to block x.com keyboard navigation shortcuts.
              window.addEventListener("keydown", (event) => handleHotkey(event, true), true);
              window.addEventListener("keypress", (event) => handleHotkey(event, false), true);
              window.addEventListener("keyup", (event) => handleHotkey(event, false), true);

              const removeShotButton = () => {
                const oldBtn = document.getElementById("__mediaCrawlerShotBtn");
                if (oldBtn) oldBtn.remove();
              };

              const addFolderButton = () => {
                if (document.getElementById("__mediaCrawlerFolderBtn")) return;
                const btn = document.createElement("button");
                btn.id = "__mediaCrawlerFolderBtn";
                btn.type = "button";
                btn.innerText = "New Folder";
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
                btn.title = "Create numbered folder under screenshots and switch save path";
                btn.addEventListener("click", () => {
                  if (typeof window.__mediaCrawlerCreateScreenshotFolder === "function") {
                    window.__mediaCrawlerCreateScreenshotFolder().catch((error) => {
                      console.error("[Screenshot] create folder failed:", error);
                    });
                  }
                });
                document.documentElement.appendChild(btn);
              };

              if (document.readyState === "loading") {
                document.addEventListener("DOMContentLoaded", () => {
                  removeShotButton();
                  addFolderButton();
                }, { once: true });
              } else {
                removeShotButton();
                addFolderButton();
              }
            }
            """

        await context.expose_function("__mediaCrawlerCaptureScreenshot", _capture)
        await context.expose_function("__mediaCrawlerToggleLongScreenshot", _toggle_long_capture)
        await context.expose_function("__mediaCrawlerCreateScreenshotFolder", _create_screenshot_folder)
        # add_init_script needs executable script text (not only a function literal).
        await context.add_init_script(script=f"({install_hotkey_script})();")
        # Also install immediately on the current page (not only on future navigations).
        await page.evaluate(install_hotkey_script)
        self._manual_screenshot_enabled = True

    async def _get_effective_scroll_y(self, page: Page) -> float:
        """
        Read the most likely active vertical scroll position on pages that may use
        either window scrolling or an internal scroll container.
        """
        value = await page.evaluate(
            """
            () => {
              const doc = document.documentElement;
              const body = document.body;
              const scrollingEl = document.scrollingElement;
              let maxScroll = Math.max(
                window.scrollY || 0,
                (doc && doc.scrollTop) || 0,
                (body && body.scrollTop) || 0,
                (scrollingEl && scrollingEl.scrollTop) || 0
              );

              const isScrollable = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const overflowY = style.overflowY || "";
                return (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay")
                  && el.scrollHeight > el.clientHeight + 8;
              };

              const candidates = [];
              const primary = document.querySelector('[data-testid="primaryColumn"]');
              if (primary) {
                let p = primary;
                while (p) {
                  if (isScrollable(p)) candidates.push(p);
                  p = p.parentElement;
                }
              }

              // Also scan visible scrollable containers as fallback.
              const all = document.querySelectorAll("div, main, section");
              for (const el of all) {
                if (!isScrollable(el)) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                if (r.bottom <= 0 || r.top >= (window.innerHeight || 0)) continue;
                candidates.push(el);
              }

              for (const el of candidates) {
                if (!el) continue;
                maxScroll = Math.max(maxScroll, el.scrollTop || 0);
              }

              return maxScroll;
            }
            """
        )
        return float(value or 0.0)

    async def _get_next_screenshot_path(self, screenshot_dir: Optional[Path] = None) -> Path:
        target_dir = screenshot_dir or getattr(self, "_active_screenshot_dir", None) or (Path(os.getcwd()) / "screenshots")
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
        return file_path

    async def _create_new_screenshot_folder(self, root_dir: Optional[Path] = None) -> Path:
        target_root = root_dir or getattr(self, "_screenshot_root_dir", None) or (Path(os.getcwd()) / "screenshots")
        target_root.mkdir(parents=True, exist_ok=True)
        existing_indices = [
            int(folder.name)
            for folder in target_root.iterdir()
            if folder.is_dir() and folder.name.isdigit()
        ]
        next_index = max(existing_indices, default=0) + 1
        folder_path = target_root / str(next_index)
        while folder_path.exists():
            next_index += 1
            folder_path = target_root / str(next_index)
        folder_path.mkdir(parents=True, exist_ok=False)
        return folder_path

    async def _expand_collapsed_content(self, page: Page) -> int:
        """
        Expand collapsed text blocks (including x.com tweet "Show more")
        before taking screenshots.
        """
        return await page.evaluate(
            """
            async () => {
              const labels = [
                "show more",
                "read more",
                "show this thread",
                "view more",
                "展开",
                "显示更多",
                "查看更多",
                "更多"
              ];

              const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") === 0) {
                  return false;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };

              const isSafeExpandableControl = (el) => {
                if (!el) return false;

                // Never click navigational links.
                const link = el.closest("a[href]");
                if (link) return false;

                // Limit expansion to tweet/main content areas.
                const inTweetOrMain =
                  !!el.closest("article") ||
                  !!el.closest("main") ||
                  !!el.closest('[data-testid="primaryColumn"]');
                if (!inTweetOrMain) return false;

                // Favor explicit tweet text expander controls when present.
                if (
                  el.closest('[data-testid="tweet-text-show-more-link"]') ||
                  el.getAttribute("data-testid") === "tweet-text-show-more-link"
                ) {
                  return true;
                }

                // Generic safe fallback: only non-link button-like controls.
                const tag = (el.tagName || "").toLowerCase();
                const role = (el.getAttribute("role") || "").toLowerCase();
                return tag === "button" || role === "button";
              };

              const tryClick = (el) => {
                if (!el || !isVisible(el)) return false;
                if (!isSafeExpandableControl(el)) return false;
                const txt = (el.innerText || el.textContent || "").trim().toLowerCase();
                if (!txt) return false;
                if (!labels.some((label) => txt === label || txt.startsWith(label))) return false;
                if (el.getAttribute("aria-disabled") === "true" || el.disabled) return false;
                el.click();
                return true;
              };

              let clicked = 0;
              for (let round = 0; round < 6; round++) {
                let changedInRound = 0;
                const candidates = document.querySelectorAll(
                  '[data-testid="tweet-text-show-more-link"], article button, article [role="button"], main button, main [role="button"]'
                );
                for (const node of candidates) {
                  if (tryClick(node)) changedInRound++;
                }
                clicked += changedInRound;
                if (changedInRound === 0) break;
                await new Promise((resolve) => setTimeout(resolve, 120));
              }

              return clicked;
            }
            """
        )

    async def _get_primary_column_bounds(self, page: Page) -> Optional[Dict[str, int]]:
        """
        Get X-axis crop bounds for x.com middle feed area.
        """
        return await page.evaluate(
            """
            () => {
              const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
              const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
              const viewportCenterX = viewportWidth / 2;
              const LEFT_EXPAND_PX = 200;

              const applyLeftExpand = (left, right) => {
                const expandedLeft = Math.max(0, left - LEFT_EXPAND_PX);
                const safeLeft = Math.min(right - 1, expandedLeft);
                return { left: safeLeft, right };
              };

              // User-requested center band on high-resolution screens:
              // roughly x=1500..2300 on a 2560px-wide viewport.
              if (viewportWidth >= 2200) {
                const forcedLeft = Math.floor(viewportWidth * 0.58);
                const forcedRight = Math.floor(viewportWidth * 0.90);
                if (forcedRight - forcedLeft >= 220) {
                  return applyLeftExpand(forcedLeft, forcedRight);
                }
              }

              const toBounds = (el) => {
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                const left = Math.max(0, Math.floor(rect.left));
                const right = Math.min(viewportWidth, Math.ceil(rect.right));
                const width = right - left;
                if (width < 220) return null;
                return { left, right, width, center: left + width / 2 };
              };

              // 1) Prefer visible tweet/article bounds nearest to screen center.
              // This is narrower and avoids including left nav.
              const candidates = Array.from(document.querySelectorAll("article"))
                .map((el) => ({ el, b: toBounds(el) }))
                .filter((x) => x.b && x.b.width >= 260 && x.b.width <= Math.max(900, viewportWidth))
                .filter((x) => {
                  const r = x.el.getBoundingClientRect();
                  return r.bottom > 0 && r.top < viewportHeight;
                })
                .map((x) => ({
                  left: x.b.left,
                  right: x.b.right,
                  score: Math.abs(x.b.center - viewportCenterX)
                }))
                .sort((a, b) => a.score - b.score);

              if (candidates.length > 0) {
                const best = candidates[0];
                const pad = 6;
                const left = Math.max(0, best.left - pad);
                const right = Math.min(viewportWidth, best.right + pad);
                return applyLeftExpand(left, right);
              }

              // 2) Fallback: explicit center column selector.
              const explicit = document.querySelector('[data-testid="primaryColumn"]');
              const explicitBounds = toBounds(explicit);
              if (explicitBounds) {
                return applyLeftExpand(explicitBounds.left, explicitBounds.right);
              }

              // 3) If unsure, do not crop.
              return null;
            }
            """
        )

    async def capture_page_screenshot(self, page: Page, screenshot_dir: Optional[Path] = None, trigger: str = "manual") -> str:
        """
        Capture one screenshot for the given page and print saved path.
        """
        expanded = await self._expand_collapsed_content(page)
        if expanded:
            print(f"[Screenshot] Expanded {expanded} collapsed content block(s) before capture.")

        file_path = await self._get_next_screenshot_path(screenshot_dir)
        bounds = await self._get_primary_column_bounds(page)
        raw_png = await page.screenshot(full_page=False)
        img = Image.open(BytesIO(raw_png)).convert("RGB")

        if bounds:
            left = max(0, min(int(bounds["left"]), img.width - 1))
            right = max(left + 1, min(int(bounds["right"]), img.width))
            img = img.crop((left, 0, right, img.height))

        img.save(file_path, format="PNG")
        saved_path = str(file_path.resolve())
        print(f"[Screenshot] ({trigger}) saved: {saved_path}")
        return saved_path

    async def capture_long_screenshot(
        self,
        page: Page,
        screenshot_dir: Optional[Path] = None,
        start_y: float = 0.0,
        end_y: float = 0.0,
        trigger: str = "manual-long",
    ) -> str:
        """
        Capture a long screenshot strictly between start_y and end_y.
        """
        expanded = await self._expand_collapsed_content(page)
        if expanded:
            print(f"[LongShot] Expanded {expanded} collapsed content block(s) before capture.")

        await page.wait_for_timeout(150)
        original_scroll_y = await page.evaluate("() => window.scrollY || 0")
        viewport_height = await page.evaluate("() => window.innerHeight || 0")
        top = min(start_y, end_y)
        bottom = max(start_y, end_y)
        page_scroll_height = await page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )
        viewport_height = max(1, int(viewport_height))
        crop_top = max(0, int(top))
        crop_bottom = max(crop_top + 1, min(int(bottom), int(page_scroll_height)))

        # X.com uses virtualized lists. Capture viewport slices and stitch them to avoid full_page blank areas.
        segment_images = []
        segment_heights = []
        x_left_used = None
        x_right_used = None
        current_y = crop_top
        while current_y < crop_bottom:
            await page.evaluate("(y) => window.scrollTo(0, y)", current_y)
            await page.wait_for_timeout(100)
            bounds = await self._get_primary_column_bounds(page)
            raw_png = await page.screenshot(full_page=False)
            img = Image.open(BytesIO(raw_png)).convert("RGB")
            remaining = crop_bottom - current_y
            keep_height = min(viewport_height, remaining, img.height)
            if keep_height <= 0:
                break
            if bounds:
                left = max(0, min(int(bounds["left"]), img.width - 1))
                right = max(left + 1, min(int(bounds["right"]), img.width))
                top = 0
                bottom = min(keep_height, img.height)
            else:
                left = 0
                right = img.width
                top = 0
                bottom = min(keep_height, img.height)

            if x_left_used is None:
                x_left_used = left
                x_right_used = right
            segment = img.crop((left, top, right, bottom))
            if segment.height <= 0:
                break
            segment_images.append(segment)
            segment_heights.append(segment.height)
            current_y += segment.height

        if not segment_images:
            # Fallback to single viewport screenshot if stitching captured nothing.
            raw_png = await page.screenshot(full_page=False)
            fallback = Image.open(BytesIO(raw_png)).convert("RGB")
            fallback_bounds = await self._get_primary_column_bounds(page)
            if fallback_bounds:
                left = max(0, min(int(fallback_bounds["left"]), fallback.width - 1))
                right = max(left + 1, min(int(fallback_bounds["right"]), fallback.width))
                fallback = fallback.crop((left, 0, right, fallback.height))
            else:
                left = 0
                right = fallback.width
            x_left_used = left
            x_right_used = right
            segment_images = [fallback]
            segment_heights = [segment_images[0].height]

        stitched_width = segment_images[0].width
        stitched_height = sum(segment_heights)
        cropped = Image.new("RGB", (stitched_width, stitched_height), color=(255, 255, 255))
        paste_y = 0
        for img in segment_images:
            cropped.paste(img, (0, paste_y))
            paste_y += img.height

        # Restore viewport near where user stopped.
        restore_y = int(max(0, min(end_y, page_scroll_height)))
        await page.evaluate("(y) => window.scrollTo(0, y)", restore_y if restore_y else int(original_scroll_y))

        file_path = await self._get_next_screenshot_path(screenshot_dir)
        cropped.save(file_path, format="PNG")
        saved_path = str(file_path.resolve())
        x_left_text = int(x_left_used) if x_left_used is not None else 0
        x_right_text = int(x_right_used) if x_right_used is not None else int(stitched_width)
        print(
            f"[LongShot] ({trigger}) saved: {saved_path} "
            f"(from X={x_left_text} to X={x_right_text}, "
            f"from Y={crop_top} to Y={crop_bottom}, "
            f"height={crop_bottom - crop_top}px)"
        )
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
