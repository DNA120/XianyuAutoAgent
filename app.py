from flask import Flask, render_template, request, jsonify, session
import os
import subprocess
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'xianyu_auto_agent_secret_key'

is_running = False
current_logs = []
bot_process = None
log_lock = threading.Lock()
bot_start_time = None  # 记录机器人启动时间
auto_login_status = {"running": False, "success": None, "message": ""}

# 默认配置模板
DEFAULT_CONFIG = {
    'API_KEY': '',
    'COOKIES_STR': '',
    'MODEL_BASE_URL': 'https://api.deepseek.com/v1',
    'MODEL_NAME': 'deepseek-chat',
    'TOGGLE_KEYWORDS': '。',
    'SIMULATE_HUMAN_TYPING': 'False',
    'LOG_LEVEL': 'INFO',
    'XIANYU_USERNAME': '',
    'XIANYU_PASSWORD': ''
}

def init_default_env():
    """初始化默认配置文件（如果不存在）"""
    env_path = '.env'
    if not os.path.exists(env_path):
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write("# XianyuAutoAgent 配置文件\n")
            f.write("# 请在前端管理界面中配置以下参数\n\n")
            for key, value in DEFAULT_CONFIG.items():
                f.write(f"{key}={value}\n")
        print("已创建默认配置文件 .env")

def read_env_file():
    """读取配置文件"""
    # 确保配置文件存在
    init_default_env()
    
    env_path = '.env'
    config = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    # 补充缺失的默认配置
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
    return config

def write_env_file(config):
    """写入配置文件"""
    env_path = '.env'
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write("# XianyuAutoAgent 配置文件\n")
        f.write("# 请在前端管理界面中配置以下参数\n\n")
        for key, value in config.items():
            clean_value = value.replace('\n', ' ').replace('\r', ' ').strip()
            f.write(f"{key}={clean_value}\n")

def check_config_complete(config):
    """检查配置是否完整"""
    required_keys = ['API_KEY', 'COOKIES_STR']
    for key in required_keys:
        if not config.get(key) or config[key].strip() == '':
            return False
    return True

def monitor_logs():
    global current_logs
    log_file = 'logs/app.log'
    last_pos = 0
    
    while is_running:
        try:
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    f.seek(last_pos)
                    new_lines = f.read()
                    if new_lines:
                        with log_lock:
                            current_logs.append({"time": datetime.now().strftime("%H:%M:%S"), "content": new_lines})
                            if len(current_logs) > 1000:
                                current_logs = current_logs[-1000:]
                        last_pos = f.tell()
        except Exception as e:
            pass
        time.sleep(1)

@app.route('/')
def index():
    config = read_env_file()
    return render_template('index.html', config=config, is_running=is_running)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        config = read_env_file()
        return jsonify(config)
    
    if request.method == 'POST':
        data = request.json
        config = read_env_file()
        config.update(data)
        write_env_file(config)
        return jsonify({"success": True, "message": "配置已保存"})


@app.route('/api/auto-login', methods=['POST'])
def api_auto_login():
    """使用浏览器自动登录闲鱼并更新cookie"""
    global auto_login_status

    if auto_login_status["running"]:
        return jsonify({"success": False, "message": "已有自动登录任务正在运行，请耐心等待..."})

    config = read_env_file()
    username = config.get('XIANYU_USERNAME', '')
    password = config.get('XIANYU_PASSWORD', '')

    if not username or not password:
        with log_lock:
            current_logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "content": "❌ 自动登录失败：未配置闲鱼账号密码"
            })
        return jsonify({"success": False, "message": "请先在配置页面填写闲鱼账号和密码"})

    def add_log(msg):
        with log_lock:
            current_logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "content": msg
            })

    auto_login_status = {"running": True, "success": None, "message": "登录中..."}

    def run_auto_login():
        global auto_login_status
        try:
            import asyncio
            from browser_login import BrowserLogin

            add_log("🚀 开始自动登录流程...")

            login_bot = BrowserLogin(log_callback=add_log)

            async def do_login():
                add_log("🌐 正在启动浏览器...")
                result = await login_bot.auto_login(username, password)
                add_log("🔒 浏览器已关闭")
                await login_bot.close()
                return result

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cookie_str = loop.run_until_complete(do_login())
            loop.close()

            if cookie_str and len(cookie_str) > 50:
                config = read_env_file()
                config['COOKIES_STR'] = cookie_str
                write_env_file(config)
                add_log("✅ 浏览器自动登录成功，Cookie已更新并保存到.env文件")
                auto_login_status = {"running": False, "success": True, "message": "自动登录成功，Cookie已更新"}
            else:
                add_log("❌ 自动登录失败，未能获取到有效Cookie")
                auto_login_status = {"running": False, "success": False, "message": "自动登录失败，未能获取到有效Cookie"}
        except ImportError:
            add_log("❌ Playwright未安装，无法使用浏览器自动登录")
            auto_login_status = {"running": False, "success": False, "message": "Playwright未安装"}
        except Exception as e:
            add_log(f"❌ 自动登录异常: {str(e)}")
            auto_login_status = {"running": False, "success": False, "message": f"自动登录失败: {str(e)}"}

    t = threading.Thread(target=run_auto_login, daemon=True)
    t.start()

    return jsonify({"success": True, "message": "自动登录已启动，请在日志面板查看实时进度..."})


@app.route('/api/auto-login-status', methods=['GET'])
def api_auto_login_status():
    return jsonify(auto_login_status)


@app.route('/api/config/status')
def api_config_status():
    """检查配置是否完整"""
    config = read_env_file()
    is_complete = check_config_complete(config)
    
    missing_items = []
    if not config.get('API_KEY') or config['API_KEY'].strip() == '':
        missing_items.append('API_KEY')
    if not config.get('COOKIES_STR') or config['COOKIES_STR'].strip() == '':
        missing_items.append('COOKIES_STR')
    
    return jsonify({
        "complete": is_complete,
        "missing": missing_items,
        "has_api_key": bool(config.get('API_KEY') and config['API_KEY'].strip() != ''),
        "has_cookies": bool(config.get('COOKIES_STR') and config['COOKIES_STR'].strip() != '')
    })

@app.route('/api/status')
def api_status():
    return jsonify({
        "is_running": is_running,
        "log_count": len(current_logs),
        "start_time": bot_start_time
    })

@app.route('/api/logs')
def api_logs():
    with log_lock:
        return jsonify(current_logs[-500:])

@app.route('/api/logs/latest')
def api_logs_latest():
    count = int(request.args.get('count', 100))
    with log_lock:
        return jsonify(current_logs[-count:])

@app.route('/api/logs/clear', methods=['POST'])
def api_logs_clear():
    global current_logs
    with log_lock:
        current_logs = []
    return jsonify({"success": True, "message": "日志已清空"})

@app.route('/api/start', methods=['POST'])
def api_start():
    global is_running, bot_process, bot_start_time
    
    if is_running:
        return jsonify({"error": "机器人已在运行中"}), 400
    
    # 检查配置是否完整
    config = read_env_file()
    if not check_config_complete(config):
        return jsonify({"error": "配置不完整，请先在配置页面设置 API_KEY 和 COOKIES_STR"}), 400
    
    try:
        os.makedirs('logs', exist_ok=True)
        
        bot_process = subprocess.Popen(
            ['python', 'main.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        is_running = True
        bot_start_time = time.time()  # 记录启动时间
        
        threading.Thread(target=monitor_logs, daemon=True).start()
        
        def capture_output():
            global current_logs
            while is_running and bot_process.poll() is None:
                try:
                    line = bot_process.stdout.readline()
                    if line:
                        with log_lock:
                            current_logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "content": line.strip()
                            })
                except:
                    break
        
        threading.Thread(target=capture_output, daemon=True).start()
        
        time.sleep(2)
        
        if bot_process.poll() is not None:
            is_running = False
            return jsonify({"error": "启动失败，请检查配置是否正确"}), 500
        
        return jsonify({"success": True, "message": "机器人启动成功"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def api_stop():
    global is_running, bot_process, bot_start_time
    
    if not is_running:
        return jsonify({"error": "机器人未运行"}), 400
    
    try:
        is_running = False
        bot_start_time = None  # 清除启动时间
        if bot_process:
            bot_process.terminate()
            bot_process.wait(timeout=5)
        
        return jsonify({"success": True, "message": "机器人已停止"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/restart', methods=['POST'])
def api_restart():
    global current_logs
    
    if is_running and bot_process:
        is_running = False
        bot_process.terminate()
        bot_process.wait(timeout=5)
    
    current_logs = []
    
    try:
        bot_process = subprocess.Popen(
            ['python', 'main.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        is_running = True
        
        threading.Thread(target=monitor_logs, daemon=True).start()
        
        def capture_output():
            global current_logs
            while is_running and bot_process.poll() is None:
                try:
                    line = bot_process.stdout.readline()
                    if line:
                        with log_lock:
                            current_logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "content": line.strip()
                            })
                except:
                    break
        
        threading.Thread(target=capture_output, daemon=True).start()
        
        time.sleep(2)
        
        if bot_process.poll() is not None:
            is_running = False
            return jsonify({"error": "启动失败，请检查配置"}), 500
        
        return jsonify({"success": True, "message": "机器人重启成功"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

PROMPTS_DIR = 'prompts'
PROMPTS_CONFIG_FILE = 'prompts_config.txt'

DEFAULT_PROMPTS_CONFIG = '''提示词：精准识别买家各类提问，区分议价砍价、商品内容咨询、日常交易咨询及违规无效话术；采用真人自然简短口吻，所有回复统一控制在四十个字以内，话术灵活多变不重复，杜绝生硬机械感。议价场景委婉应对砍价，合理小幅让利，优先引导用户下单；商品咨询紧扣在售货品信息作答，不随意延伸闲聊，无对应答案不直白表述，委婉引导拍下；日常沟通只回应交易、发货、购买相关内容，无关闲聊直接无视，检测到退款相关关键词直接不回复；全程禁止使用表情符号，规避平台敏感字词，微信直接规避不提，百度替换为baidu、夸克替换为kuake，买家重复提问自动更换不同话术，不夸大宣传、不额外闲聊扯闲篇。'''

def get_prompt_config_path():
    return os.path.join(PROMPTS_DIR, PROMPTS_CONFIG_FILE)

def read_prompt_config():
    filepath = get_prompt_config_path()
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    # 如果文件不存在，返回默认配置
    write_prompt_config(DEFAULT_PROMPTS_CONFIG)
    return DEFAULT_PROMPTS_CONFIG

def write_prompt_config(content):
    filepath = get_prompt_config_path()
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

@app.route('/api/prompts')
def api_prompts_list():
    content = read_prompt_config()
    return jsonify({"prompts_config.txt": content})

@app.route('/api/prompts/config', methods=['GET', 'PUT'])
def api_prompt_config():
    if request.method == 'GET':
        content = read_prompt_config()
        return jsonify({"filename": PROMPTS_CONFIG_FILE, "content": content})
    
    if request.method == 'PUT':
        data = request.json
        content = data.get('content', '')
        write_prompt_config(content)
        return jsonify({"success": True, "message": "提示词配置已保存"})

@app.route('/api/prompts/reset-all', methods=['POST'])
def api_prompts_reset_all():
    write_prompt_config(DEFAULT_PROMPTS_CONFIG)
    return jsonify({"success": True, "message": "提示词配置已恢复默认"})

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)