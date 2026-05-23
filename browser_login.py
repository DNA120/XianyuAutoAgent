import asyncio
import json
import os
import random
import re
import time
from loguru import logger

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 未安装，浏览器自动登录功能不可用")

_IS_WINDOWS = os.name == 'nt'


def generate_slider_track(distance):
    tracks = []
    current = 0
    mid = distance * random.uniform(0.6, 0.8)
    while current < mid:
        move = random.randint(2, 5)
        current += move
        tracks.append(current)
    while current < distance:
        move = random.randint(1, 3)
        current += move
        if current > distance:
            current = distance
        tracks.append(current)
    if random.random() > 0.5:
        overshoot = min(distance + random.randint(1, 3), distance + 5)
        tracks.append(overshoot)
        time.sleep(random.uniform(0.05, 0.15))
        tracks.append(distance)
    return tracks


class BrowserLogin:
    def __init__(self, log_callback=None):
        self.login_url = 'https://www.goofish.com/'
        self.taobao_login_url = 'https://login.taobao.com/'
        self.browser = None
        self.context = None
        self.page = None
        self._log_callback = log_callback

    def _log(self, msg):
        logger.info(msg)
        if self._log_callback:
            self._log_callback(msg)

    def _log_success(self, msg):
        logger.success(msg)
        if self._log_callback:
            self._log_callback(f"✅ {msg}")

    def _log_error(self, msg):
        logger.error(msg)
        if self._log_callback:
            self._log_callback(f"❌ {msg}")

    def _log_warning(self, msg):
        logger.warning(msg)
        if self._log_callback:
            self._log_callback(f"⚠️ {msg}")

    async def _create_browser(self, headless=True):
        if not PLAYWRIGHT_AVAILABLE:
            self._log_error("Playwright 未安装，无法创建浏览器")
            return None

        p = await async_playwright().start()
        self.browser = await p.chromium.launch(
            headless=headless,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--window-size=1280,800',
            ]
        )

        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )

        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            window.chrome = { runtime: {} };
        """)

        self.page = await self.context.new_page()
        return self.page

    async def _collect_cookies(self):
        cookies = await self.context.cookies()
        cookie_parts = []
        for c in cookies:
            domain = c.get('domain', '')
            if 'goofish' in domain or 'taobao' in domain or 'alibaba' in domain or 'alicdn' in domain:
                cookie_parts.append(f"{c['name']}={c['value']}")
        return '; '.join(cookie_parts)

    async def _try_solve_slider(self, page):
        try:
            self._log("等待滑块验证码出现...")
            await page.wait_for_selector('[class*="nc"]', timeout=5000)
            await page.wait_for_timeout(1000)

            slider_selectors = [
                '.nc_iconfont.btn_slide', '.nc_iconfont',
                '#nc_1_n1z', '#nc_2_n1z',
                '.nc_scale span', '.slidetounlock',
                '.nc-lang-cnt', '[class*="nc_"]',
            ]

            slider_element = None
            for selector in slider_selectors:
                try:
                    slider = await page.query_selector(selector)
                    if slider:
                        self._log(f"找到滑块元素: {selector}")
                        slider_element = slider
                        break
                except:
                    continue

            if not slider_element:
                self._log_warning("未找到滑块元素")
                return False

            slider_box = await slider_element.bounding_box()
            if not slider_box:
                self._log_warning("无法获取滑块位置")
                return False

            track_selectors = ['.nc_scale', '.nc_wrapper', '[class*="nc_scale"]']
            track_width = 300
            for selector in track_selectors:
                try:
                    te = await page.query_selector(selector)
                    if te:
                        tb = await te.bounding_box()
                        if tb:
                            track_width = tb['width']
                            break
                except:
                    continue

            drag_distance = track_width - slider_box['width'] - 5
            start_x = slider_box['x'] + slider_box['width'] / 2
            start_y = slider_box['y'] + slider_box['height'] / 2
            end_x = start_x + drag_distance

            self._log(f"开始模拟滑块拖动: 距离={drag_distance}px")
            tracks = generate_slider_track(drag_distance)

            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            for track_x in tracks:
                await page.mouse.move(start_x + track_x, start_y + random.uniform(-2, 2))
                await page.wait_for_timeout(random.randint(5, 15))
            await page.mouse.move(end_x, start_y + random.uniform(-1, 1))
            await page.wait_for_timeout(random.randint(50, 150))
            await page.mouse.up()
            await page.wait_for_timeout(2000)

            success = await self._check_slider_result(page)
            if success:
                self._log_success("滑块验证通过！")
                return True

            self._log_warning("滑块验证失败，尝试备用方案...")
            return False

        except PlaywrightTimeout:
            self._log_warning("滑块未出现，可能不需要验证")
            return True
        except Exception as e:
            self._log_error(f"滑块处理异常: {e}")
            return False

    async def _check_slider_result(self, page):
        try:
            for sel in ['.nc_iconfont.ok', '.nc_iconfont.btn_ok', '[class*="nc_ok"]', '.errloading']:
                try:
                    if await page.query_selector(sel):
                        return True
                except:
                    continue
            text = await page.text_content('body')
            if text and '验证通过' in text:
                return True
            for sel in ['.nc_iconfont.btn_error', '.errloading', '.nc-lang-cnt:has-text("请控制")']:
                try:
                    if await page.query_selector(sel):
                        return False
                except:
                    continue
            return None
        except Exception as e:
            return False

    async def auto_login(self, username, password, max_slider_retries=5):
        if not username or not password:
            self._log_error("未配置账号密码")
            return None

        headless = not _IS_WINDOWS
        self._log(f"启动浏览器 ({'可视模式' if not headless else '后台模式'})...")
        self._log(f"当前系统: {'Windows' if _IS_WINDOWS else 'Linux'}")
        if headless:
            self._log("NAS系统检测，使用后台模式运行...")
        else:
            self._log("本机检测，自动弹出浏览器窗口，请观察操作过程")

        try:
            page = await self._create_browser(headless=headless)
            if not page:
                return None

            # ===== 第一步：打开闲鱼首页 =====
            self._log("正在打开闲鱼首页...")
            await page.goto(self.login_url, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            self._log_success("闲鱼首页已打开")

            # ===== 第二步：点击登录按钮 =====
            self._log("查找登录按钮...")
            login_btn = None
            try:
                login_btn = await page.wait_for_selector('span:has-text("登录")', timeout=5000)
            except:
                try:
                    login_btn = await page.wait_for_selector('button:has-text("登录")', timeout=5000)
                except:
                    pass

            if login_btn:
                self._log("点击登录按钮...")
                await login_btn.click(force=True)
                await page.wait_for_timeout(3000)
            else:
                self._log("未找到登录按钮，尝试链接方式...")
                try:
                    await page.goto('https://www.goofish.com/user/login', wait_until='networkidle', timeout=10000)
                except:
                    pass
                await page.wait_for_timeout(3000)

            # 等待登录弹窗出现
            self._log("等待登录弹窗...")
            try:
                await page.wait_for_selector('.ant-modal-wrap, [class*="login"], iframe', timeout=8000)
                await page.wait_for_timeout(2000)
            except:
                self._log("未检测到登录弹窗，继续尝试...")
            self._log_success("登录弹窗已出现")

            # ===== 第三步：找到登录iframe并切换到密码登录 =====
            self._log("查找登录弹窗中的iframe...")

            # 等待iframe出现并切换进去
            login_frame = None
            for attempt in range(10):
                frames = page.frames
                for f in frames:
                    url = f.url
                    if 'login' in url or 'taobao' in url or 'alibaba' in url or 'passport' in url:
                        if url != 'about:blank' and 'goofish' not in url:
                            login_frame = f
                            self._log(f"找到登录iframe: {url[:60]}")
                            break
                if login_frame:
                    break
                await page.wait_for_timeout(1000)

            if not login_frame:
                self._log("未通过URL找到iframe，尝试查找页面中的iframe元素...")
                iframe_elements = await page.query_selector_all('iframe')
                for iframe_el in iframe_elements:
                    try:
                        src = await iframe_el.get_attribute('src')
                        if src and ('login' in src or 'taobao' in src or 'alibaba' in src):
                            login_frame = await iframe_el.content_frame()
                            if login_frame:
                                self._log(f"找到登录iframe元素: {src[:60]}")
                                break
                    except:
                        continue

            if login_frame:
                self._log_success("已切换到登录iframe")

                # 在iframe中切换到密码登录
                self._log("切换到密码登录...")
                try:
                    await login_frame.wait_for_selector('.ant-tabs-tab, [class*="password"], [class*="pwd"]', timeout=5000)
                    await login_frame.evaluate("""
                        () => {
                            const tabs = document.querySelectorAll('.ant-tabs-tab, .ant-tabs-tab-btn, div[role="tab"], [class*="tab"]');
                            for (const tab of tabs) {
                                const text = tab.textContent || '';
                                if (text.includes('密码登录') || text.includes('账号密码')) {
                                    tab.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    await page.wait_for_timeout(2000)
                    self._log_success("已切换到密码登录")
                except Exception as e:
                    self._log(f"切换密码登录异常(可能已经在密码登录): {e}")

                # 在iframe中填写账号
                self._log("填写账号...")
                safe_username = json.dumps(username, ensure_ascii=True)
                try:
                    acc_filled = await login_frame.evaluate(f"""
                        () => {{
                            const inputs = document.querySelectorAll('input');
                            for (const inp of inputs) {{
                                const id = inp.id || '';
                                const name = inp.name || '';
                                const p = inp.placeholder || '';
                                const type = inp.type || '';
                                if (type !== 'password' && (id === 'fm-login-id' || name === 'loginId' || p.indexOf('手机号') >= 0 || p.indexOf('账号') >= 0 || p.indexOf('邮箱') >= 0)) {{
                                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                    setter.call(inp, {safe_username});
                                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    inp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                    """)
                except Exception as e:
                    acc_filled = False
                    self._log(f"iframe填账号异常: {e}")

                if acc_filled:
                    self._log_success("账号已填写")
                else:
                    self._log("iframe填账号失败，尝试在主页面查找输入框...")
                    for sel in ['#fm-login-id', 'input[name="loginId"]']:
                        try:
                            el = await page.query_selector(sel)
                            if el:
                                await el.fill(username, force=True)
                                self._log_success("账号已填写(主页面)")
                                break
                        except:
                            continue

                # 在iframe中填写密码
                self._log("填写密码...")
                safe_password = json.dumps(password, ensure_ascii=True)
                try:
                    pwd_filled = await login_frame.evaluate(f"""
                        () => {{
                            const inputs = document.querySelectorAll('input[type="password"]');
                            for (const inp of inputs) {{
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                setter.call(inp, {safe_password});
                                inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                inp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                return true;
                            }}
                            return false;
                        }}
                    """)
                except Exception as e:
                    pwd_filled = False
                    self._log(f"iframe填密码异常: {e}")

                if pwd_filled:
                    self._log_success("密码已填写")
                else:
                    for sel in ['#fm-login-password', 'input[type="password"]']:
                        try:
                            el = await page.query_selector(sel)
                            if el:
                                await el.fill(password, force=True)
                                self._log_success("密码已填写(主页面)")
                                break
                        except:
                            continue

                await page.wait_for_timeout(1000)

                # 勾选协议
                try:
                    await login_frame.evaluate("""
                        () => {
                            const checks = document.querySelectorAll('.ant-checkbox-input, [class*="agree"], [class*="protocol"]');
                            for (const cb of checks) {
                                try { cb.click(); } catch(e) {}
                            }
                        }
                    """)
                except:
                    pass

                # 提交登录（在iframe中点击登录按钮）
                self._log("提交登录...")
                try:
                    submitted = await login_frame.evaluate("""
                        () => {
                            const btns = document.querySelectorAll('button');
                            for (const btn of btns) {
                                if (btn.textContent && (btn.textContent.trim() === '登录' || btn.textContent.trim() === '登 录') && btn.type === 'submit') {
                                    btn.click();
                                    return true;
                                }
                            }
                            for (const btn of btns) {
                                if (btn.textContent && btn.textContent.includes('登录')) {
                                    btn.click();
                                    return true;
                                }
                            }
                            const pwdInputs = document.querySelectorAll('input[type="password"]');
                            if (pwdInputs.length > 0) {
                                const evt = new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true});
                                pwdInputs[0].dispatchEvent(evt);
                                return true;
                            }
                            return false;
                        }
                    """)
                except Exception as e:
                    submitted = False
                    self._log(f"iframe提交异常: {e}")
                    await page.keyboard.press('Enter')

                if submitted:
                    self._log_success("登录请求已提交")
                else:
                    self._log("iframe提交未生效，尝试Enter键...")
                    await page.keyboard.press('Enter')
            else:
                self._log_warning("未找到登录iframe，尝试在主页面直接操作...")
                # 在主页面直接找密码登录的tab和输入框
                self._log("切换到密码登录...")
                await page.evaluate("""
                    () => {
                        const tabs = document.querySelectorAll('.ant-tabs-tab, .ant-tabs-tab-btn, a, span, div[role="tab"]');
                        for (const tab of tabs) {
                            const text = tab.textContent || '';
                            if (text.includes('密码登录') || text.includes('账号密码')) {
                                tab.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                await page.wait_for_timeout(2000)

                self._log("填写账号...")
                safe_username = json.dumps(username, ensure_ascii=True)
                await page.evaluate(f"""
                    () => {{
                        const inputs = document.querySelectorAll('input');
                        for (const inp of inputs) {{
                            const id = inp.id || '';
                            const name = inp.name || '';
                            const p = inp.placeholder || '';
                            if (id === 'fm-login-id' || name === 'loginId' || p.indexOf('账号') >= 0 || p.indexOf('手机号') >= 0) {{
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                setter.call(inp, {safe_username});
                                inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                return true;
                            }}
                        }}
                        return false;
                    }}
                """)
                self._log_success("账号已填写")

                self._log("填写密码...")
                safe_password = json.dumps(password, ensure_ascii=True)
                await page.evaluate(f"""
                    () => {{
                        const inputs = document.querySelectorAll('input[type="password"]');
                        for (const inp of inputs) {{
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(inp, {safe_password});
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                        return false;
                    }}
                """)
                self._log_success("密码已填写")

                await page.wait_for_timeout(1000)
                await page.evaluate("""
                    () => {
                        const checks = document.querySelectorAll('.ant-checkbox-input, [class*="agree"], [class*="protocol"]');
                        for (const cb of checks) { try { cb.click(); } catch(e) {} }
                    }
                """)

                self._log("提交登录...")
                submitted = await page.evaluate("""
                    () => {
                        const btns = document.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent && btn.textContent.includes('登录')) {
                                btn.click();
                                return true;
                            }
                        }
                        const pwdInputs = document.querySelectorAll('input[type="password"]');
                        if (pwdInputs.length > 0) {
                            const evt = new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true});
                            pwdInputs[0].dispatchEvent(evt);
                            return true;
                        }
                        return false;
                    }
                """)
                if not submitted:
                    await page.keyboard.press('Enter')

            await page.wait_for_timeout(3000)

            # ===== 第六步：处理滑块验证 =====
            self._log("检测滑块验证...")
            slider_success = False
            for attempt in range(max_slider_retries):
                result = await self._try_solve_slider(page)
                if result:
                    slider_success = True
                    break
                if attempt < max_slider_retries - 1:
                    self._log(f"第 {attempt+1} 次滑块尝试失败，重试...")
                    await page.wait_for_timeout(2000)

            if not slider_success:
                self._log_warning("自动滑块验证失败")
                if not headless:
                    self._log("⏳ 浏览器窗口已打开，请手动完成滑块验证（30秒内）...")
                    for i in range(30):
                        await page.wait_for_timeout(1000)
                        url = page.url
                        if url and 'goofish.com' in url and '/login' not in url:
                            self._log_success("检测到用户已完成滑块验证")
                            slider_success = True
                            break
                else:
                    self._log_error("自动滑块验证失败，NAS无界面无法手动操作")
                    await self.close()
                    return None

            # ===== 第七步：等待登录完成，跳转回首页 =====
            self._log("登录完成，等待页面跳转...")
            await page.wait_for_timeout(5000)

            try:
                await page.goto(self.login_url, wait_until='networkidle', timeout=15000)
            except:
                pass
            await page.wait_for_timeout(3000)

            # ===== 第八步：收集Cookie =====
            self._log("收集Cookie中...")
            cookie_str = await self._collect_cookies()
            await self.close()

            if cookie_str and len(cookie_str) > 50:
                self._log_success(f"浏览器自动登录成功！已获取Cookie ({len(cookie_str)}字符)")
                return cookie_str
            else:
                self._log_error("获取到的Cookie不完整")
                if not headless:
                    self._log("⏳ 浏览器窗口保持打开，请手动刷新闲鱼页面后等待...")
                    for i in range(30):
                        await page.wait_for_timeout(1000)
                    try:
                        await page.goto(self.login_url, wait_until='networkidle', timeout=15000)
                    except:
                        pass
                    cookie_str2 = await self._collect_cookies()
                    await self.close()
                    if cookie_str2 and len(cookie_str2) > 50:
                        self._log_success("重试获取Cookie成功！")
                        return cookie_str2
                return None

        except Exception as e:
            self._log_error(f"自动登录异常: {e}")
            try:
                await self.close()
            except:
                pass
            return None

    async def get_cookies_via_browser(self, headless=True):
        try:
            page = await self._create_browser(headless=headless)
            if not page:
                return None
            self._log("打开闲鱼网页...")
            await page.goto(self.login_url, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            self._log("收集浏览器Cookie...")
            cookie_str = await self._collect_cookies()
            await self.close()
            if cookie_str and len(cookie_str) > 50:
                self._log_success("已从浏览器获取Cookie")
                return cookie_str
            self._log_warning("未能获取到有效Cookie")
            return None
        except Exception as e:
            self._log_error(f"获取Cookie失败: {e}")
            try:
                await self.close()
            except:
                pass
            return None

    async def close(self):
        try:
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
        except Exception as e:
            logger.warning(f"关闭浏览器异常: {e}")


if __name__ == '__main__':
    async def test():
        bot = BrowserLogin()
        cookie = await bot.get_cookies_via_browser(headless=False)
        if cookie:
            logger.info(f"Cookie: {cookie[:100]}...")
        await bot.close()
    asyncio.run(test())
