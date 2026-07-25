from pathlib import Path
import json
import re
import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# 基础配置
# ============================================================

WEBVPN_URL = "https://webvpn.uestc.edu.cn/"

CONFIG_PATH = Path(__file__).parent / "config.json"

# 独立浏览器用户目录，不影响你平时开的 Chrome
PROFILE_DIR = Path(__file__).parent / "uestc_auto_profile"

SERVICE_HALL_TEXT = "网上服务大厅"
JW_SYSTEM_TEXT = "教务系统"
COURSE_MANAGE_TEXT = "课程管理"

# False = 使用 Playwright 自带 Chromium，通常更少奇怪提示
# True = 尝试使用你电脑上的 Chrome
USE_SYSTEM_CHROME = False

# 最后是否保持浏览器打开
KEEP_BROWSER_OPEN = True


# ============================================================
# 速度优先参数
# ============================================================

FAST_SETTLE_MS = 150

# 登录输入阶段稍微慢一点，其他流程仍保持快
LOGIN_FIELD_WAIT_MS = 600
LOGIN_TYPE_DELAY_MS = 35
LOGIN_INPUT_RETRY = 3

# 点击后等待新标签页出现的最长时间，越小越快
NEW_PAGE_WAIT_MS = 2200

# 教务系统重复登录提示的快速检测时间
DUPLICATE_LOGIN_FAST_CHECK_SECONDS = 2.2

# 教务系统疑似白屏时，最多等几秒再刷新
JW_BLANK_WAIT_SECONDS = 2.8

# 白屏最多刷新次数
MAX_BLANK_RELOADS = 1

# 找文字时每个选择器的等待时间
TEXT_CLICK_TIMEOUT_EACH = 250

# 找文字时最多滚动几次
TEXT_CLICK_MAX_SCROLLS = 8


# ============================================================
# 登录页选择器
# ============================================================

ACCOUNT_INPUT_SELECTORS = [
    "input[placeholder*='学号']",
    "input[placeholder*='账号']",
    "input[placeholder*='用户名']",
    "input[placeholder*='用户']",
    "input[name*='student']",
    "input[name*='user']",
    "input[name*='account']",
    "input[name*='username']",
    "input[id*='student']",
    "input[id*='user']",
    "input[id*='account']",
    "input[id*='username']",
    "input[type='text']",
    "input:not([type])",
]

PASSWORD_INPUT_SELECTORS = [
    "input[placeholder*='密码']",
    "input[name*='pass']",
    "input[id*='pass']",
    "input[type='password']",
]

LOGIN_BUTTON_TEXTS = [
    "登录",
    "登 录",
    "Login",
    "LOGIN",
]

LOGIN_BUTTON_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "input[type='button']",
    "a[href='javascript:void(0)']",
    "a[href^='javascript']",
    "a",
    "button",
    "[role='button']",
    "[onclick]",
]


# ============================================================
# 重复登录提示配置
# ============================================================

DUPLICATE_LOGIN_KEYWORDS = [
    "当前用户存在重复登录",
    "已将之前的登录踢出",
    "请点击此处继续",
    "点击此处",
]


# ============================================================
# 通用工具函数
# ============================================================

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"没有找到配置文件：{CONFIG_PATH}\n"
            "请新建 config.json，内容示例：\n"
            '{\n'
            '  "student_id": "你的学号",\n'
            '  "password": "你的密码"\n'
            '}'
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    student_id = str(config.get("student_id", "")).strip()
    password = str(config.get("password", ""))

    if not student_id or not password:
        raise ValueError("config.json 里的 student_id 或 password 为空。")

    return student_id, password


def wait_short(page, ms=FAST_SETTLE_MS):
    page.wait_for_timeout(ms)


def browser_has_open_page(context) -> bool:
    try:
        return any(not page.is_closed() for page in context.pages)
    except Exception:
        return False


def wait_for_browser_closed(context, poll_seconds=0.5):
    print("浏览器保持打开。关闭浏览器窗口后脚本会自动退出。")
    while browser_has_open_page(context):
        time.sleep(poll_seconds)


def wait_for_manual_login_or_browser_close(context, page, seconds=300) -> bool:
    print("请在浏览器里手动完成登录；检测到登录成功后会自动继续。")
    end_time = time.time() + seconds

    while time.time() < end_time and browser_has_open_page(context):
        if wait_until_logged_in(page, seconds=1):
            return True
        time.sleep(0.5)

    return False


def normalize_pattern(text: str):
    return re.compile(re.escape(text), re.IGNORECASE)


def scroll_all_frames(page, dy=800):
    for frame in page.frames:
        try:
            frame.evaluate("(dy) => window.scrollBy(0, dy)", dy)
        except Exception:
            pass

    try:
        page.mouse.wheel(0, dy)
    except Exception:
        pass


def visible_locator_from_selectors(page, selectors, timeout_each=700):
    last_error = None

    for frame in page.frames:
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                loc.wait_for(state="visible", timeout=timeout_each)
                return loc
            except Exception as e:
                last_error = e

    raise RuntimeError(f"没有找到可见元素。最后错误：{last_error}")


def page_contains_any_text(page, texts, timeout_each=180) -> bool:
    for frame in page.frames:
        for text in texts:
            try:
                frame.get_by_text(text, exact=False).first.wait_for(
                    state="visible",
                    timeout=timeout_each,
                )
                return True
            except Exception:
                pass

    return False


def safe_wait_domcontentloaded(page, timeout=5000):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass


def settle_page_fast(page):
    """
    普通页面打开后的快速稳定处理。
    只做很短等待，不处理白屏，不长时间等。
    """
    safe_wait_domcontentloaded(page, timeout=5000)
    wait_short(page, FAST_SETTLE_MS)


# ============================================================
# 登录相关
# ============================================================

def is_logged_in(page) -> bool:
    for frame in page.frames:
        try:
            frame.get_by_text(SERVICE_HALL_TEXT, exact=False).first.wait_for(
                state="visible",
                timeout=250,
            )
            return True
        except Exception:
            pass

    return False


def type_like_user(locator, text, field_name="输入框"):
    """
    稳定输入：
    1. 点击并聚焦；
    2. Ctrl+A 清空；
    3. 像真人一样输入；
    4. 检查实际 value；
    5. 失败则重试；
    6. 最后用 JS 强制写入并派发事件兜底。
    """
    text = str(text)

    for attempt in range(1, LOGIN_INPUT_RETRY + 1):
        try:
            locator.wait_for(state="visible", timeout=3000)
            locator.scroll_into_view_if_needed(timeout=1500)

            locator.click(timeout=3000, force=True)
            wait_short(locator.page, LOGIN_FIELD_WAIT_MS)

            try:
                locator.press("Control+A")
                wait_short(locator.page, 80)
                locator.press("Backspace")
            except Exception:
                pass

            wait_short(locator.page, 120)

            locator.type(text, delay=LOGIN_TYPE_DELAY_MS)
            wait_short(locator.page, 200)

            try:
                locator.evaluate(
                    """
                    el => {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                    """
                )
            except Exception:
                pass

            try:
                current_value = locator.input_value(timeout=1000)
                if current_value == text:
                    print(f"{field_name}输入成功。")
                    return True
                else:
                    print(f"{field_name}第 {attempt} 次输入后校验失败，准备重试。")
            except Exception:
                print(f"{field_name}第 {attempt} 次输入后无法校验，准备重试。")

        except Exception as e:
            print(f"{field_name}第 {attempt} 次输入失败：{e}")

        wait_short(locator.page, 300)

    # JS 兜底：有些页面 type 不进去，但 JS 设置 value 可以
    print(f"{field_name}常规输入失败，使用 JS 兜底写入。")

    locator.evaluate(
        """
        (el, value) => {
            el.focus();
            el.value = value;

            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        """,
        text,
    )

    wait_short(locator.page, 300)

    try:
        current_value = locator.input_value(timeout=1000)
        if current_value == text:
            print(f"{field_name}JS 写入成功。")
            return True
    except Exception:
        pass

    raise RuntimeError(f"{field_name}输入失败，最终没有写入成功。")


def fill_login_form(page, student_id, password):
    print("填写账号密码...")

    account_input = visible_locator_from_selectors(
        page,
        ACCOUNT_INPUT_SELECTORS,
        timeout_each=1500,
    )

    type_like_user(account_input, student_id, field_name="账号")

    # 关键：账号输入后给页面一点时间，让密码框/登录组件反应过来
    wait_short(page, LOGIN_FIELD_WAIT_MS)

    password_input = visible_locator_from_selectors(
        page,
        PASSWORD_INPUT_SELECTORS,
        timeout_each=2000,
    )

    # 再等一下，避免刚定位到密码框但还没完全可输入
    wait_short(page, LOGIN_FIELD_WAIT_MS)

    type_like_user(password_input, password, field_name="密码")

    # 密码输入后不要立刻登录，给前端 input/change 事件一点处理时间
    wait_short(page, LOGIN_FIELD_WAIT_MS)

    return password_input


def click_login_button(page, password_input=None):
    """
    多策略触发登录：
    1. 密码框 Enter；
    2. 真实鼠标点击登录按钮；
    3. JS 触发 javascript:void(0) 类按钮；
    4. 提交 form。
    """

    # 方案 1：密码框按 Enter
    if password_input is not None:
        try:
            print("尝试按 Enter 登录...")
            password_input.press("Enter")
            wait_short(page, 800)
            if is_logged_in(page):
                return True
        except Exception as e:
            print(f"按 Enter 登录失败：{e}")

    print("尝试点击登录按钮...")

    # 方案 2：真实鼠标点击
    for frame in page.frames:
        locators = []

        for text in LOGIN_BUTTON_TEXTS:
            locators.extend([
                lambda f=frame, t=text: f.get_by_role("button", name=normalize_pattern(t)).first,
                lambda f=frame, t=text: f.get_by_text(t, exact=False).first,
                lambda f=frame, t=text: f.locator("a").filter(has_text=normalize_pattern(t)).first,
                lambda f=frame, t=text: f.locator("button").filter(has_text=normalize_pattern(t)).first,
                lambda f=frame, t=text: f.locator("[role='button']").filter(has_text=normalize_pattern(t)).first,
                lambda f=frame, t=text: f.locator("[onclick]").filter(has_text=normalize_pattern(t)).first,
            ])

        for get_loc in locators:
            try:
                loc = get_loc()
                loc.wait_for(state="visible", timeout=350)
                loc.scroll_into_view_if_needed(timeout=1200)

                box = loc.bounding_box()
                if box:
                    page.mouse.click(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                else:
                    loc.click(timeout=1200, force=True)

                wait_short(page, 700)
                return True
            except Exception:
                pass

    # 方案 3：JS click
    print("尝试 JS 触发登录按钮...")

    for frame in page.frames:
        try:
            clicked = frame.evaluate(
                """
                () => {
                    const visible = (el) => {
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none'
                            && s.visibility !== 'hidden'
                            && r.width > 0
                            && r.height > 0;
                    };

                    const textOf = (el) => {
                        return [
                            el.innerText,
                            el.textContent,
                            el.value,
                            el.getAttribute('aria-label'),
                            el.getAttribute('title')
                        ].filter(Boolean).join(' ');
                    };

                    const nodes = Array.from(document.querySelectorAll(
                        "a, button, input, div, span, [role='button'], [onclick]"
                    ));

                    const btn = nodes.find(el => {
                        const text = textOf(el);
                        return visible(el) && /登\\s*录|login/i.test(text);
                    });

                    if (!btn) return false;

                    btn.scrollIntoView({ block: "center", inline: "center" });

                    for (const name of ["mouseover", "mousedown", "mouseup", "click"]) {
                        btn.dispatchEvent(new MouseEvent(name, {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                    }

                    if (typeof btn.click === "function") btn.click();

                    return true;
                }
                """
            )

            if clicked:
                wait_short(page, 700)
                return True

        except Exception:
            pass

    # 方案 4：提交 form
    print("尝试提交登录表单...")

    for frame in page.frames:
        try:
            submitted = frame.evaluate(
                """
                () => {
                    const pwd = document.querySelector("input[type='password']");
                    if (!pwd || !pwd.form) return false;

                    if (pwd.form.requestSubmit) {
                        pwd.form.requestSubmit();
                    } else {
                        pwd.form.submit();
                    }

                    return true;
                }
                """
            )

            if submitted:
                wait_short(page, 700)
                return True

        except Exception:
            pass

    raise RuntimeError("没有成功触发登录按钮。")


def wait_until_logged_in(page, seconds=10) -> bool:
    end_time = time.time() + seconds

    while time.time() < end_time:
        if is_logged_in(page):
            return True

        # 登录阶段也快速扫一下重复登录提示，避免偶发情况
        handle_duplicate_login_if_needed(page, timeout_seconds=0.2)

        wait_short(page, 250)

    return False


def login_if_needed(context, page, student_id, password):
    if is_logged_in(page):
        print("检测到已经登录。")
        return

    password_input = fill_login_form(page, student_id, password)
    click_login_button(page, password_input=password_input)

    print("等待登录跳转...")

    if wait_until_logged_in(page, seconds=12):
        print("登录成功。")
        return

    print("没有自动检测到登录成功。")
    print("可能需要验证码、二次认证，或者页面选择器没匹配上。")
    print(f"请你手动完成登录，看到“{SERVICE_HALL_TEXT}”后脚本会自动继续。")

    if not wait_for_manual_login_or_browser_close(context, page, seconds=300):
        raise RuntimeError("仍未检测到登录成功，请确认是否已经进入 WebVPN 首页。")


# ============================================================
# 重复登录处理
# ============================================================

def handle_duplicate_login_if_needed(page, timeout_seconds=2.0) -> bool:
    """
    处理教务系统页面中的重复登录提示：
    当前用户存在重复登录...
    请点击此处继续

    返回 True 表示检测到并尝试处理过。
    """
    end_time = time.time() + timeout_seconds
    handled = False

    while time.time() < end_time:
        found_duplicate = page_contains_any_text(
            page,
            DUPLICATE_LOGIN_KEYWORDS,
            timeout_each=120,
        )

        if not found_duplicate:
            wait_short(page, 120)
            continue

        print("检测到重复登录提示，尝试点击“点击此处”继续...")
        handled = True

        # 方案 1：文字定位点击
        for frame in page.frames:
            candidates = [
                lambda f=frame: f.get_by_text("点击此处", exact=False).first,
                lambda f=frame: f.get_by_text("此处", exact=False).first,
                lambda f=frame: f.get_by_text("继续", exact=False).first,
                lambda f=frame: f.locator("a").filter(has_text="点击此处").first,
                lambda f=frame: f.locator("a").filter(has_text="此处").first,
                lambda f=frame: f.locator("[onclick]").filter(has_text="点击此处").first,
                lambda f=frame: f.locator("[onclick]").filter(has_text="此处").first,
            ]

            for get_loc in candidates:
                try:
                    loc = get_loc()
                    loc.wait_for(state="visible", timeout=350)
                    loc.scroll_into_view_if_needed(timeout=1200)

                    box = loc.bounding_box()
                    if box:
                        page.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    else:
                        loc.click(timeout=1200, force=True)

                    wait_short(page, 700)
                    print("已点击“点击此处”继续。")
                    return True

                except Exception:
                    pass

        # 方案 2：JS 找可点击父元素
        for frame in page.frames:
            try:
                clicked = frame.evaluate(
                    """
                    () => {
                        function visible(el) {
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== "none"
                                && s.visibility !== "hidden"
                                && r.width > 0
                                && r.height > 0;
                        }

                        function fireClick(el) {
                            el.scrollIntoView({ block: "center", inline: "center" });

                            for (const name of ["mouseover", "mousedown", "mouseup", "click"]) {
                                el.dispatchEvent(new MouseEvent(name, {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                }));
                            }

                            if (typeof el.click === "function") {
                                el.click();
                            }
                        }

                        const nodes = Array.from(document.querySelectorAll(
                            "a, button, span, div, p, font, b, strong, [onclick], [role='button']"
                        ));

                        const textNode = nodes.find(el => {
                            const text = (el.innerText || el.textContent || "").trim();
                            return visible(el) && (
                                text.includes("点击此处") ||
                                text.includes("此处继续") ||
                                text === "此处" ||
                                text.includes("继续")
                            );
                        });

                        if (!textNode) return false;

                        let clickable = textNode.closest("a, button, [onclick], [role='button']");
                        if (!clickable) clickable = textNode;

                        fireClick(clickable);
                        return true;
                    }
                    """
                )

                if clicked:
                    wait_short(page, 700)
                    print("已用 JS 点击“点击此处”继续。")
                    return True

            except Exception:
                pass

        # 方案 3：点击包含整段提示的区域
        for frame in page.frames:
            try:
                clicked = frame.evaluate(
                    """
                    () => {
                        function visible(el) {
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== "none"
                                && s.visibility !== "hidden"
                                && r.width > 0
                                && r.height > 0;
                        }

                        const nodes = Array.from(document.querySelectorAll("body *"));

                        const target = nodes.find(el => {
                            const text = (el.innerText || el.textContent || "").trim();
                            return visible(el)
                                && text.includes("当前用户存在重复登录")
                                && text.includes("点击此处");
                        });

                        if (!target) return false;

                        const clickable = target.querySelector("a, button, [onclick]")
                            || target.closest("a, button, [onclick], [role='button']")
                            || target;

                        clickable.scrollIntoView({ block: "center", inline: "center" });
                        clickable.click();
                        return true;
                    }
                    """
                )

                if clicked:
                    wait_short(page, 700)
                    print("已点击重复登录提示区域。")
                    return True

            except Exception:
                pass

        wait_short(page, 250)

    return handled


# ============================================================
# 白屏检测和教务页兜底
# ============================================================

def is_blank_page(page) -> bool:
    """
    粗略判断是否白屏。
    """
    try:
        result = page.evaluate(
            """
            () => {
                const body = document.body;
                if (!body) {
                    return {
                        blank: true,
                        textLength: 0,
                        visibleCount: 0,
                        readyState: document.readyState,
                        url: location.href
                    };
                }

                const text = (body.innerText || body.textContent || "").trim();

                const visibleCount = Array.from(
                    document.querySelectorAll("body *")
                ).filter(el => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none"
                        && style.visibility !== "hidden"
                        && rect.width > 0
                        && rect.height > 0;
                }).length;

                return {
                    blank: text.length < 5 && visibleCount < 3,
                    textLength: text.length,
                    visibleCount,
                    readyState: document.readyState,
                    url: location.href
                };
            }
            """
        )

        return bool(result.get("blank"))

    except Exception:
        return False


def settle_jw_page_fast(page, name="教务系统页面"):
    """
    只给教务系统页面使用：
    1. 快速处理重复登录；
    2. 快速判断白屏；
    3. 疑似白屏才刷新一次；
    4. 刷新后再处理重复登录。
    """
    safe_wait_domcontentloaded(page, timeout=5000)
    wait_short(page, 200)

    handle_duplicate_login_if_needed(
        page,
        timeout_seconds=DUPLICATE_LOGIN_FAST_CHECK_SECONDS,
    )

    # 先快速看是不是白屏，不是就立刻返回
    start = time.time()

    while time.time() - start < JW_BLANK_WAIT_SECONDS:
        if not is_blank_page(page):
            return

        wait_short(page, 250)

    # 仍然白屏，才刷新
    for i in range(MAX_BLANK_RELOADS):
        print(f"{name} 疑似白屏，快速刷新一次...")

        try:
            page.reload(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            try:
                page.reload(timeout=15000)
            except Exception as e:
                print(f"{name} 刷新失败：{e}")
                return

        wait_short(page, 500)

        handle_duplicate_login_if_needed(
            page,
            timeout_seconds=DUPLICATE_LOGIN_FAST_CHECK_SECONDS,
        )

        if not is_blank_page(page):
            return

    print(f"{name} 仍疑似白屏，但已达到最大刷新次数。")


# ============================================================
# 点击文字和页面切换
# ============================================================

def find_and_click_text(
    page,
    text: str,
    max_scrolls=TEXT_CLICK_MAX_SCROLLS,
    timeout_each=TEXT_CLICK_TIMEOUT_EACH,
):
    """
    在页面和所有 iframe 中快速查找文字并点击。
    找不到就快速滚动。
    """
    last_error = None
    pattern = normalize_pattern(text)

    for _ in range(max_scrolls):
        for frame in page.frames:
            locators = [
                lambda f=frame: f.get_by_role("link", name=pattern).first,
                lambda f=frame: f.get_by_role("button", name=pattern).first,
                lambda f=frame: f.get_by_text(text, exact=False).first,
            ]

            for get_loc in locators:
                try:
                    loc = get_loc()
                    loc.wait_for(state="visible", timeout=timeout_each)
                    loc.scroll_into_view_if_needed(timeout=1000)

                    box = loc.bounding_box()
                    if box:
                        page.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    else:
                        loc.click(timeout=1000, force=True)

                    return True
                except Exception as e:
                    last_error = e

        scroll_all_frames(page, dy=900)
        wait_short(page, 100)

    raise RuntimeError(f"找不到或无法点击：{text}\n最后错误：{last_error}")


def click_and_maybe_new_page(context, page, text: str, wait_ms=NEW_PAGE_WAIT_MS):
    """
    速度优先版：
    先点击，然后短时间轮询是否出现新标签页。
    如果没有新标签页，就认为当前页面跳转。
    """
    old_pages = set(context.pages)

    find_and_click_text(page, text)

    end_time = time.time() + wait_ms / 1000

    while time.time() < end_time:
        new_pages = [p for p in context.pages if p not in old_pages]

        if new_pages:
            new_page = new_pages[-1]
            settle_page_fast(new_page)
            return new_page

        wait_short(page, 100)

    # 没有新页，认为当前页跳转
    settle_page_fast(page)
    return page


def close_page_safely(page, name="页面"):
    try:
        if not page.is_closed():
            page.close()
            print(f"已关闭{name}。")
    except Exception:
        pass


# ============================================================
# 浏览器启动
# ============================================================

def launch_context(playwright):
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        no_viewport=True,
    )

    if USE_SYSTEM_CHROME:
        try:
            return playwright.chromium.launch_persistent_context(
                **kwargs,
                channel="chrome",
            )
        except Exception as e:
            print("启动本机 Chrome 失败，改用 Playwright 自带 Chromium。")
            print(e)

    return playwright.chromium.launch_persistent_context(**kwargs)


# ============================================================
# 主流程
# ============================================================

def main():
    student_id, password = load_config()

    with sync_playwright() as p:
        print("启动独立自动化浏览器窗口...")
        context = launch_context(p)

        page = context.pages[0] if context.pages else context.new_page()

        print("打开 WebVPN...")
        page.goto(WEBVPN_URL, wait_until="domcontentloaded", timeout=60000)
        settle_page_fast(page)

        login_if_needed(context, page, student_id, password)

        print(f"进入 {SERVICE_HALL_TEXT}...")
        service_page = click_and_maybe_new_page(
            context,
            page,
            SERVICE_HALL_TEXT,
        )

        if service_page != page:
            close_page_safely(page, "WebVPN 原页面")

        print(f"查找并打开 {JW_SYSTEM_TEXT}...")
        jw_page = click_and_maybe_new_page(
            context,
            service_page,
            JW_SYSTEM_TEXT,
        )

        if jw_page != service_page:
            close_page_safely(service_page, "网上服务大厅页面")

        # 重点：重复登录和白屏主要在教务系统页，只在这里做快速兜底
        settle_jw_page_fast(jw_page, name="教务系统页面")

        print(f"尝试进入 {COURSE_MANAGE_TEXT}...")

        try:
            # 先不兜底，直接点课程管理，效率最高
            find_and_click_text(
                jw_page,
                COURSE_MANAGE_TEXT,
                max_scrolls=8,
                timeout_each=250,
            )
            print(f"已进入 {COURSE_MANAGE_TEXT}。")

        except Exception as first_error:
            print(f"没有立刻找到 {COURSE_MANAGE_TEXT}，执行一次教务系统兜底后重试...")
            print(first_error)

            settle_jw_page_fast(jw_page, name="教务系统页面")

            try:
                find_and_click_text(
                    jw_page,
                    COURSE_MANAGE_TEXT,
                    max_scrolls=10,
                    timeout_each=350,
                )
                print(f"已进入 {COURSE_MANAGE_TEXT}。")

            except Exception as second_error:
                print(f"已经进入教务系统，但仍没有成功点击 {COURSE_MANAGE_TEXT}。")
                print("如果实际入口文字不是“课程管理”，请修改脚本顶部 COURSE_MANAGE_TEXT。")
                print(second_error)

        print("\n流程结束。")

        if KEEP_BROWSER_OPEN:
            wait_for_browser_closed(context)
            return

        context.close()


if __name__ == "__main__":
    main()
