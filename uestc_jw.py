from pathlib import Path
import json
import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


WEBVPN_URL = "https://webvpn.uestc.edu.cn/"

CONFIG_PATH = Path(__file__).parent / "config.json"
PROFILE_DIR = Path(__file__).parent / "uestc_auto_profile"

SERVICE_HALL_TEXT = "网上服务大厅"
JW_SYSTEM_TEXT = "教务系统"
COURSE_MANAGE_TEXT = "课程管理"
DUPLICATE_LOGIN_TEXT = "点击此处"

ACCOUNT_INPUT_SELECTOR = "input[placeholder*='学号']"
PASSWORD_INPUT_SELECTOR = "input[placeholder*='密码']"

LOGIN_FIELD_WAIT_MS = 600
LOGIN_TYPE_DELAY_MS = 35
LOGIN_SUCCESS_TIMEOUT_SECONDS = 12
NEW_PAGE_WAIT_MS = 5000

KEEP_BROWSER_OPEN = True


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"没有找到配置文件：{CONFIG_PATH}\n"
            "请新建 config.json，内容示例：\n"
            "{\n"
            '  "student_id": "你的学号",\n'
            '  "password": "你的密码"\n'
            "}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    student_id = str(config.get("student_id", "")).strip()
    password = str(config.get("password", ""))

    if not student_id or not password:
        raise ValueError("config.json 里的 student_id 或 password 为空。")

    return student_id, password


def browser_has_open_page(context):
    return any(not page.is_closed() for page in context.pages)


def wait_for_browser_closed(context, poll_seconds=0.5):
    print("浏览器保持打开。关闭浏览器窗口后脚本会自动退出。")
    while browser_has_open_page(context):
        time.sleep(poll_seconds)


def wait_page_ready(page):
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    page.wait_for_timeout(150)


def is_logged_in(page):
    try:
        page.get_by_role(
            "link",
            name=SERVICE_HALL_TEXT,
            exact=False,
        ).first.wait_for(state="visible", timeout=250)
        return True
    except PlaywrightTimeoutError:
        return False


def type_login_field(locator, value, field_name):
    locator.wait_for(state="visible", timeout=5000)
    locator.scroll_into_view_if_needed(timeout=2000)
    locator.click(timeout=3000, force=True)
    locator.press("Control+A")
    locator.press("Backspace")
    locator.type(str(value), delay=LOGIN_TYPE_DELAY_MS)
    locator.evaluate(
        """
        el => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        """
    )

    if locator.input_value(timeout=1000) != str(value):
        raise RuntimeError(f"{field_name}输入后校验失败。")

    print(f"{field_name}输入成功。")


def fill_login_form(page, student_id, password):
    print("填写账号密码...")

    account_input = page.locator(ACCOUNT_INPUT_SELECTOR).first
    type_login_field(account_input, student_id, "账号")
    page.wait_for_timeout(LOGIN_FIELD_WAIT_MS)

    password_input = page.locator(PASSWORD_INPUT_SELECTOR).first
    type_login_field(password_input, password, "密码")
    page.wait_for_timeout(LOGIN_FIELD_WAIT_MS)

    return password_input


def wait_until_logged_in(page):
    end_time = time.time() + LOGIN_SUCCESS_TIMEOUT_SECONDS

    while time.time() < end_time:
        if is_logged_in(page):
            return True
        page.wait_for_timeout(250)

    return False


def login_if_needed(page, student_id, password):
    if is_logged_in(page):
        print("检测到已经登录。")
        return

    password_input = fill_login_form(page, student_id, password)
    print("按 Enter 登录...")
    password_input.press("Enter")

    if not wait_until_logged_in(page):
        raise RuntimeError("登录后未在规定时间内进入 WebVPN 首页。")

    print("登录成功。")


def open_new_page(context, source_page, locator, source_name):
    locator.wait_for(state="visible", timeout=10000)
    locator.scroll_into_view_if_needed(timeout=2000)

    with context.expect_page(timeout=NEW_PAGE_WAIT_MS) as page_info:
        locator.click(timeout=5000)

    new_page = page_info.value
    wait_page_ready(new_page)
    source_page.close()
    print(f"已关闭{source_name}。")
    return new_page


def handle_duplicate_login(page):
    continue_link = page.get_by_text(
        DUPLICATE_LOGIN_TEXT,
        exact=False,
    ).first

    try:
        continue_link.wait_for(state="visible", timeout=2500)
    except PlaywrightTimeoutError:
        return False

    continue_link.click(timeout=3000)
    page.wait_for_timeout(700)
    print("已处理重复登录提示。")
    return True


def launch_context(playwright):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        no_viewport=True,
    )


def main():
    student_id, password = load_config()

    with sync_playwright() as playwright:
        print("启动独立 Chromium 浏览器窗口...")
        context = launch_context(playwright)
        page = context.pages[0] if context.pages else context.new_page()

        print("打开 WebVPN...")
        page.goto(WEBVPN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(150)
        login_if_needed(page, student_id, password)

        print(f"进入 {SERVICE_HALL_TEXT}...")
        service_page = open_new_page(
            context,
            page,
            page.get_by_role(
                "link",
                name=SERVICE_HALL_TEXT,
                exact=False,
            ).first,
            "WebVPN 原页面",
        )

        print(f"打开 {JW_SYSTEM_TEXT}...")
        service_page.mouse.wheel(0, 900)
        service_page.wait_for_timeout(100)
        jw_page = open_new_page(
            context,
            service_page,
            service_page.get_by_text(JW_SYSTEM_TEXT, exact=False).first,
            "网上服务大厅页面",
        )

        handle_duplicate_login(jw_page)

        print(f"进入 {COURSE_MANAGE_TEXT}...")
        course_manage = jw_page.get_by_text(
            COURSE_MANAGE_TEXT,
            exact=False,
        ).first
        course_manage.wait_for(state="visible", timeout=10000)
        course_manage.click(timeout=5000)
        print(f"已进入 {COURSE_MANAGE_TEXT}。")

        print("\n流程结束。")

        if KEEP_BROWSER_OPEN:
            wait_for_browser_closed(context)
            return

        context.close()


if __name__ == "__main__":
    main()
