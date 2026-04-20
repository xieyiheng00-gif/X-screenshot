import asyncio
import json
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
        - `c`: scroll down ~1000px and capture automatically.
        - `Ctrl+Shift+C` or `Cmd+Shift+C`: instant screenshot.
        """
        if getattr(self, "_manual_screenshot_enabled", False):
            return

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

        async def _scroll_and_capture(_scroll_y: float = 0.0) -> str:
            if self._screenshot_busy:
                print("[Screenshot] Busy, ignore auto capture request.")
                return ""

            self._screenshot_busy = True
            try:
                current_scroll_y = await self._get_effective_scroll_y(page)
                viewport_h = float(await page.evaluate("() => window.innerHeight || 768"))
                scroll_step = viewport_h * (4 / 5)
                target_scroll_y = max(0.0, float(current_scroll_y) + scroll_step)
                await page.evaluate("(y) => window.scrollTo(0, y)", target_scroll_y)
                await page.wait_for_timeout(180)
                return await self.capture_page_screenshot(page, trigger="c-auto")
            finally:
                self._screenshot_busy = False

        import urllib.parse as _urlparse
        import datetime as _dt
        import config as _cfg_early

        # ── Weekly ranges: newest → oldest ───────────────────────────────────
        def _compute_week_ranges() -> list:
            try:
                newer = _dt.date.fromisoformat(_cfg_early.START_DATE)
                older = _dt.date.fromisoformat(_cfg_early.STOP_DATE)
            except (ValueError, AttributeError):
                return []
            if newer <= older:
                return []
            ranges = []
            until = newer
            while until > older:
                since = max(until - _dt.timedelta(days=7), older)
                ranges.append((since.isoformat(), until.isoformat()))
                until = since
            return ranges  # each entry: (since/older_end, until/newer_end)

        _week_ranges: list = _compute_week_ranges()
        # State: which week within the current account folder we're on.
        # -1 means "need a new account folder on next advance".
        if not hasattr(self, "_week_idx"):
            self._week_idx = -1          # next week index to use
            self._account_folder: Optional[Path] = None

        def _search_url_for_week(account: str, since: str, until: str) -> str:
            if not account:
                return ""
            query = f"from:{account} -filter:replies -is:retweet since:{since} until:{until}"
            return "https://x.com/search?q=" + _urlparse.quote(query) + "&src=typed_query&f=live"

        async def _advance() -> tuple:
            """
            Advance to the next week (or new account when weeks exhausted).
            Returns (account, search_url, week_label).
            """
            root_dir = getattr(self, "_screenshot_root_dir", screenshot_dir)

            if _week_ranges:
                # Need a new account folder?
                if self._week_idx < 0 or self._account_folder is None:
                    self._account_folder = await self._create_new_screenshot_folder(root_dir)
                    self._week_idx = 0

                # Wrap around to new account when all weeks done
                if self._week_idx >= len(_week_ranges):
                    self._account_folder = await self._create_new_screenshot_folder(root_dir)
                    self._week_idx = 0

                since, until = _week_ranges[self._week_idx]
                self._week_idx += 1

                week_label = f"{since} to {until}"
                week_folder = self._account_folder / week_label
                week_folder.mkdir(parents=True, exist_ok=True)
                self._active_screenshot_dir = week_folder

                parts = self._account_folder.name.split("_", 1)
                account = parts[1] if len(parts) > 1 else ""
                search_url = _search_url_for_week(account, since, until)

                print(f"[Screenshot] Week folder : {week_folder.resolve()}")
                if search_url:
                    print(f"[Screenshot] Search URL  : {search_url}")
                return account, search_url, week_label

            else:
                # No weekly ranges configured – fall back to plain account folder
                folder_path = await self._create_new_screenshot_folder(root_dir)
                self._active_screenshot_dir = folder_path
                parts = folder_path.name.split("_", 1)
                account = parts[1] if len(parts) > 1 else ""
                search_url = ""
                if account:
                    start = getattr(_cfg_early, "START_DATE", "")
                    stop = getattr(_cfg_early, "STOP_DATE", "")
                    query = f"from:{account} -filter:replies -is:retweet"
                    if stop:
                        query += f" since:{stop}"
                    if start:
                        query += f" until:{start}"
                    search_url = "https://x.com/search?q=" + _urlparse.quote(query) + "&src=typed_query&f=live"
                return account, search_url, ""

        async def _create_screenshot_folder() -> str:
            account, search_url, week_label = await _advance()
            active = str(self._active_screenshot_dir.resolve()) if self._active_screenshot_dir else ""
            message = f"[Screenshot] Active folder: {active}"
            return json.dumps({"message": message, "account": account, "search_url": search_url})

        async def _auto_next_account() -> None:
            # Detect whether the next advance crosses an account boundary
            # (either weeks are exhausted, or we have no account folder yet).
            is_new_account = (
                not _week_ranges
                or self._week_idx < 0
                or self._account_folder is None
                or self._week_idx >= len(_week_ranges)
            )
            pre_nav_sleep = 180 if is_new_account else 60
            boundary = "account" if is_new_account else "week"
            print(f"[Screenshot] End of {boundary}. Pausing {pre_nav_sleep}s before next batch.")

            account, search_url, _week_label = await _advance()

            async def _navigate_and_restart() -> None:
                await asyncio.sleep(pre_nav_sleep)
                dest = search_url or (f"https://x.com/{account}" if account else "")
                if dest:
                    await page.goto(dest, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                await page.evaluate(
                    "() => { const b = document.getElementById('__mediaCrawlerAutoBtn');"
                    " if (b && b.dataset.state !== 'on') b.click(); }"
                )

            asyncio.create_task(_navigate_and_restart())

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
                      console.error("[Screenshot] auto capture failed:", error);
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
                btn.innerText = "New Folder/Next Week";
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
                btn.title = "Advance to next week folder and navigate to its date-filtered search";
                btn.addEventListener("click", () => {
                  if (typeof window.__mediaCrawlerCreateScreenshotFolder === "function") {
                    window.__mediaCrawlerCreateScreenshotFolder().then((result) => {
                      try {
                        const data = JSON.parse(result);
                        if (data.search_url) {
                          window.location.href = data.search_url;
                        } else if (data.account) {
                          window.location.href = "https://x.com/" + data.account;
                        }
                      } catch (e) {}
                    }).catch((error) => {
                      console.error("[Screenshot] create folder failed:", error);
                    });
                  }
                });
                document.documentElement.appendChild(btn);
              };

              const addAutoButton = () => {
                if (document.getElementById("__mediaCrawlerAutoBtn")) return;
                const btn = document.createElement("button");
                btn.id = "__mediaCrawlerAutoBtn";
                btn.type = "button";
                btn.innerText = "Auto: OFF";
                btn.dataset.state = "off";
                btn.style.position = "fixed";
                btn.style.right = "210px";
                btn.style.top = "12px";
                btn.style.zIndex = "2147483647";
                btn.style.padding = "6px 10px";
                btn.style.background = "#2b2b2b";
                btn.style.color = "#fff";
                btn.style.border = "1px solid #555";
                btn.style.borderRadius = "8px";
                btn.style.cursor = "pointer";
                btn.style.fontSize = "12px";
                btn.style.opacity = "1";
                btn.style.boxShadow = "0 2px 10px rgba(0,0,0,0.4)";
                btn.style.pointerEvents = "auto";
                btn.style.minWidth = "84px";
                btn.title = "Toggle auto capture (interval: 2 + N(0,1) seconds)";

                btn.addEventListener("click", () => {
                  const currentState = btn.dataset.state || "off";
                  if (currentState === "off") {
                    btn.dataset.state = "on";
                    btn.innerText = "Auto: ON";
                    btn.style.background = "#0d7a2b";
                    if (window.__mediaCrawlerAutoTimer) {
                      clearTimeout(window.__mediaCrawlerAutoTimer);
                    }

                    // Detect end-of-week by scroll stall: 3 consecutive captures
                    // already at the bottom means no new tweets are loading.
                    if (typeof window.__mediaCrawlerBottomCount === "undefined") {
                      window.__mediaCrawlerBottomCount = 0;
                    }
                    const checkDoneWithWeek = () => {
                      const scrollY = window.scrollY || 0;
                      const innerH = window.innerHeight || 0;
                      const scrollH = Math.max(
                        document.body.scrollHeight,
                        document.documentElement.scrollHeight
                      );
                      if (scrollH - scrollY - innerH < innerH * 0.15) {
                        window.__mediaCrawlerBottomCount = (window.__mediaCrawlerBottomCount || 0) + 1;
                      } else {
                        window.__mediaCrawlerBottomCount = 0;
                      }
                      return window.__mediaCrawlerBottomCount >= 3;
                    };

                    const randn = () => {
                      const u = 1 - Math.random();
                      const v = Math.random();
                      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
                    };
                    const scheduleNext = () => {
                      const delayMs = Math.max(500, (2 + randn()) * 1000);
                      window.__mediaCrawlerAutoTimer = setTimeout(() => {
                        if (btn.dataset.state !== "on") return;
                        if (checkDoneWithWeek()) {
                          btn.dataset.state = "off";
                          btn.innerText = "Auto: OFF";
                          btn.style.background = "#2b2b2b";
                          window.__mediaCrawlerAutoTimer = null;
                          // Hand off to Python: advance week → navigate → 5s → turn Auto ON.
                          window.__mediaCrawlerAutoNextAccount().catch(console.error);
                          return;
                        }
                        if (typeof window.__mediaCrawlerToggleLongScreenshot === "function") {
                          window.__mediaCrawlerToggleLongScreenshot(window.scrollY || 0).catch((error) => {
                            console.error("[Screenshot] auto timer capture failed:", error);
                          });
                        }
                        scheduleNext();
                      }, delayMs);
                    };
                    scheduleNext();
                    return;
                  }

                  btn.dataset.state = "off";
                  btn.innerText = "Auto: OFF";
                  btn.style.background = "#2b2b2b";
                  if (window.__mediaCrawlerAutoTimer) {
                    clearTimeout(window.__mediaCrawlerAutoTimer);
                    window.__mediaCrawlerAutoTimer = null;
                  }
                });

                document.documentElement.appendChild(btn);
              };

              const expandShowMore = () => {
                const labels = ["show more", "read more", "show this thread", "view more"];
                const candidates = document.querySelectorAll(
                  '[data-testid="tweet-text-show-more-link"], article [role="button"], article button'
                );
                candidates.forEach((el) => {
                  const txt = (el.innerText || el.textContent || "").trim().toLowerCase();
                  if (!txt) return;
                  if (!labels.some((l) => txt === l || txt.startsWith(l))) return;
                  if (el.getAttribute("aria-disabled") === "true" || el.disabled) return;
                  const rect = el.getBoundingClientRect();
                  if (rect.width === 0 && rect.height === 0) return;
                  el.click();
                });
              };

              let expandTimer = null;
              const scheduleExpand = () => {
                if (expandTimer) return;
                expandTimer = setTimeout(() => {
                  expandTimer = null;
                  expandShowMore();
                }, 300);
              };

              const startAutoExpand = () => {
                if (window.__mediaCrawlerExpandObserver) return;
                expandShowMore();
                const observer = new MutationObserver(scheduleExpand);
                observer.observe(document.body, { childList: true, subtree: true });
                window.__mediaCrawlerExpandObserver = observer;
              };

              if (document.readyState === "loading") {
                document.addEventListener("DOMContentLoaded", () => {
                  removeShotButton();
                  addAutoButton();
                  addFolderButton();
                  startAutoExpand();
                }, { once: true });
              } else {
                removeShotButton();
                addAutoButton();
                addFolderButton();
                startAutoExpand();
              }
            }
            """

        await context.expose_function("__mediaCrawlerCaptureScreenshot", _capture)
        await context.expose_function("__mediaCrawlerToggleLongScreenshot", _scroll_and_capture)
        await context.expose_function("__mediaCrawlerCreateScreenshotFolder", _create_screenshot_folder)
        await context.expose_function("__mediaCrawlerAutoNextAccount", _auto_next_account)
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

        accounts_file = Path(os.getcwd()) / "finance_x_accounts.txt"
        accounts: list[str] = []
        if accounts_file.exists():
            accounts = [
                line.strip()
                for line in accounts_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        def _folder_index(folder: Path) -> int | None:
            parts = folder.name.split("_", 1)
            try:
                return int(parts[0])
            except ValueError:
                return None

        existing_indices = [
            idx
            for folder in target_root.iterdir()
            if folder.is_dir() and (idx := _folder_index(folder)) is not None
        ]
        next_index = max(existing_indices, default=0) + 1

        account_name = accounts[next_index - 1] if next_index - 1 < len(accounts) else ""
        folder_name = f"{next_index}_{account_name}" if account_name else str(next_index)
        folder_path = target_root / folder_name
        while folder_path.exists():
            next_index += 1
            account_name = accounts[next_index - 1] if next_index - 1 < len(accounts) else ""
            folder_name = f"{next_index}_{account_name}" if account_name else str(next_index)
            folder_path = target_root / folder_name
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
        All values are derived from live DOM geometry so the result adapts to
        any viewport / monitor size without hardcoded pixel constants.
        """
        return await page.evaluate(
            """
            () => {
              const W   = window.innerWidth || document.documentElement.clientWidth || 0;
              const DPR = window.devicePixelRatio || 1;
              if (W <= 0) return null;

              // X.com layout formula (CSS pixels) ——————————————————————————
              // W_nav: left sidebar (icon-only below 1265 px, full above)
              const W_nav = W >= 1265 ? 275 : 80;
              // 1225 = total fixed width of 3-column block (275 nav + 600 feed + 350 sidebar)

              let X_pos;
              if (W < 685) {
                X_pos = 0;
              } else if (W < 1090) {
                X_pos = W_nav;
              } else {
                X_pos = (W - 1225) / 2 + W_nav;
              }

              const X_end = X_pos + Math.min(W, 600);

              // Multiply by DPR so the returned values are in physical pixels,
              // matching what Playwright's page.screenshot() produces.
              const PAD = 6;
              return {
                left:  Math.max(0, Math.round((X_pos - PAD) * DPR)),
                right: Math.round((X_end  + PAD) * DPR),
              };
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
