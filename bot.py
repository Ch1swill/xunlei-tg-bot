import os
import requests
import telebot
import urllib.parse
import time
import threading
import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

# 导入同目录下的 sniff.py
import sniff

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 环境变量 ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
XUNLEI_HOST = os.getenv('XUNLEI_HOST', '').rstrip('/')
SNIFF_PORT = os.getenv('SNIFF_PORT', '2345')
SNIFF_INTERFACE = os.getenv('SNIFF_INTERFACE', 'any')

RAW_SPACE = os.getenv('XUNLEI_SPACE', '')
XUNLEI_SPACE = urllib.parse.unquote(RAW_SPACE)
XUNLEI_PARENT_FILE_ID = os.getenv('XUNLEI_PARENT_FILE_ID')
HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', 3600))

CURRENT_TOKEN = os.getenv('XUNLEI_AUTH', '')
IS_SNIFFING = False
TOKEN_LOCK = threading.Lock()

# 常用视频后缀
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.rmvb', '.rm', '.mpg', '.mpeg', '.m2ts', '.iso', '.dat', '.vob'}
MIN_FILE_SIZE = 200 * 1024 * 1024  # 200MB

bot = telebot.TeleBot(BOT_TOKEN)
user_pending_tasks = {}

# ===========================
# 1. 基础功能
# ===========================

def get_headers():
    with TOKEN_LOCK:
        token = CURRENT_TOKEN
    return {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "pan-auth": token,
        "Cookie": f"xtoken={token}"
    }

def update_token(new_token):
    global CURRENT_TOKEN
    with TOKEN_LOCK:
        CURRENT_TOKEN = new_token
    logging.info(f"🔄 Token 已更新: {new_token[:10]}...")

def try_get_token_from_memory():
    """从 xlp 进程内存提取 UIAuth token，无需用户操作。成功返回 token 字符串，失败返回空字符串。"""
    import re, base64, json
    try:
        pid = None
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            try:
                with open(f'/proc/{entry}/cmdline', 'rb') as f:
                    cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                if 'xlp' in cmdline and '--chroot' in cmdline:
                    pid = entry
            except Exception:
                pass
        if not pid:
            logging.warning("内存提取：未找到 xlp 进程")
            return ""

        with open(f'/proc/{pid}/maps') as f:
            maps = f.read()

        regions = []
        for line in maps.split('\n'):
            parts = line.split()
            if len(parts) >= 2 and 'rw' in parts[1] and 'xunlei' not in line:
                addr = parts[0].split('-')
                start, end = int(addr[0], 16), int(addr[1], 16)
                if 0 < (end - start) < 50 * 1024 * 1024:
                    regions.append((start, end))

        best_tok, best_exp = "", 0
        now = int(time.time())
        with open(f'/proc/{pid}/mem', 'rb') as mem:
            for start, end in regions[:20]:
                try:
                    mem.seek(start)
                    data = mem.read(end - start)
                    for t in re.findall(rb'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', data):
                        ts = t.decode('utf-8', errors='ignore')
                        if len(ts) < 50:
                            continue
                        try:
                            p = ts.split('.')
                            pad = len(p[1]) % 4
                            pl = json.loads(base64.b64decode(p[1] + '=' * pad))
                            if pl.get('key') == 'UIAuth' and pl.get('exp', 0) > now + 60:
                                if pl['exp'] > best_exp:
                                    best_exp, best_tok = pl['exp'], ts
                        except Exception:
                            pass
                except Exception:
                    pass

        if best_tok:
            ttl = best_exp - now
            logging.info(f"内存提取 Token 成功，剩余 {ttl//3600}h {(ttl%3600)//60}m")
        return best_tok
    except Exception as e:
        logging.warning(f"内存提取 Token 失败: {e}")
        return ""

def perform_sniffing(chat_id, quiet=False):
    global IS_SNIFFING
    if IS_SNIFFING:
        if not quiet: bot.send_message(chat_id, "⚠️ 嗅探器运行中...")
        return

    IS_SNIFFING = True
    if not quiet:
        bot.send_message(chat_id, "🕵️‍♂️ **嗅探器已启动**", parse_mode="Markdown")

    def run_sniff_thread():
        global IS_SNIFFING
        try:
            # 优先：从进程内存提取（无需用户操作）
            token = try_get_token_from_memory()
            if token:
                update_token(token)
                bot.send_message(chat_id, "✅ Token 已自动从内存获取", parse_mode="Markdown")
                return
            # 兜底：tcpdump 嗅探（需要用户刷新迅雷页面）
            if not quiet:
                bot.send_message(chat_id, "💡 自动提取失败，请在迅雷Web界面刷新页面触发抓包...")
            token = sniff.capture_token(timeout=60, port=SNIFF_PORT, interface=SNIFF_INTERFACE)
            if token:
                update_token(token)
                bot.send_message(chat_id, "🎯 **Token 更新成功**", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "❌ **嗅探超时**，请检查网络或权限", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"嗅探出错: {e}")
        finally:
            IS_SNIFFING = False

    threading.Thread(target=run_sniff_thread).start()

def check_token_alive(verbose=False):
    with TOKEN_LOCK:
        if not CURRENT_TOKEN: return False
    try:
        url = f"{XUNLEI_HOST}/drive/v1/tasks"
        params = {"type": "user#runner", "device_space": ""}
        res = requests.get(url, params=params, headers=get_headers(), timeout=10)
        return res.status_code == 200
    except:
        return True

def health_check_loop():
    """
    健康检查循环
    逻辑调整：启动时立即检查一次，之后每隔 HEALTH_CHECK_INTERVAL 秒检查一次
    """
    logging.info(f"🩺 健康检查服务已启动 (周期: {HEALTH_CHECK_INTERVAL}秒)...")
    set_bot_commands()
    
    while True:
        try:
            # 1. 先执行检查
            logging.info("🩺 执行例行健康检查...")
            if not check_token_alive(verbose=True):
                logging.warning("⚠️ 检测到 Token 失效，尝试内存自动提取...")
                token = try_get_token_from_memory()
                if token:
                    update_token(token)
                    logging.info("✅ Token 已从内存静默更新")
                else:
                    logging.warning("内存提取失败，通知用户手动操作")
                    bot.send_message(CHAT_ID, "⚠️ Token 已失效且无法自动获取，请打开迅雷网页后发送 /check")
            else:
                logging.info("✅ Token 状态正常")
                
        except Exception as e:
            logging.error(f"检查异常: {e}")

        # 2. 检查完再睡觉
        time.sleep(HEALTH_CHECK_INTERVAL)

def set_bot_commands():
    try:
        bot.set_my_commands([
            BotCommand("start", "状态面板"),
            BotCommand("check", "立即检查"),
        ])
    except: pass

# ===========================
# 2. 迅雷逻辑
# ===========================

def is_video_file(filename):
    if not filename: return False
    return os.path.splitext(filename.lower())[1] in VIDEO_EXTENSIONS

def collect_all_files(resources, file_list, depth=0):
    prefix = "  " * depth + "├─ "
    
    for item in resources:
        name = item.get('name', 'Unknown')
        size = int(item.get('file_size', 0))
        idx = item.get('file_index')
        
        if idx is None: idx = 0 

        is_directory = item.get('is_dir') or \
                       item.get('kind') == 'drive#folder' or \
                       bool(item.get('dir', {}).get('resources'))

        if is_directory:
            logging.info(f"{prefix}📂 [DIR] {name}")
            sub_resources = item.get('dir', {}).get('resources', [])
            if sub_resources:
                collect_all_files(sub_resources, file_list, depth + 1)
        else:
            size_mb = size / 1024 / 1024
            logging.info(f"{prefix}📄 [FILE] {name} ({size_mb:.2f} MB) idx={idx}")
            file_list.append({
                'name': name,
                'size': size,
                'file_index': idx
            })

def analyze_magnet(magnet):
    logging.info(f"🔍 解析磁力: {magnet[:40]}...")
    url = f"{XUNLEI_HOST}/drive/v1/resource/list"
    
    headers = get_headers()
    params = {"pan_auth": headers.get('pan-auth')}
    payload = {"page_size": 1000, "urls": magnet}
    
    try:
        res = requests.post(url, params=params, json=payload, headers=headers, timeout=20)
        if res.status_code != 200:
            logging.error(f"API请求失败: {res.status_code}")
            return None
        
        data = res.json()
        if 'list' not in data or 'resources' not in data['list']:
            return None
        
        main_resource = data['list']['resources'][0]
        torrent_name = main_resource.get('name', 'Unknown')
        
        if not main_resource.get('is_dir'):
             idx = main_resource.get('file_index')
             if idx is None: idx = 0
             size = int(main_resource.get('file_size', 0))
             
             logging.info(f"✅ 识别为单文件: {torrent_name}")
             return {
                "name": torrent_name,
                "file_size": str(size),
                "total_file_count": "1",
                "sub_file_index": str(idx),
                "selected_files": [torrent_name]
            }

        top_resources = main_resource.get('dir', {}).get('resources', [])
        all_files = []
        if top_resources:
            collect_all_files(top_resources, all_files)
        
        if not all_files:
            logging.warning("❌ 未找到任何文件")
            return None

        selected_indices = []
        selected_filenames = []
        selected_size = 0
        
        # 策略A: 视频文件且大于200MB
        valid_videos = []
        for f in all_files:
            if f['file_index'] is not None and f['size'] > MIN_FILE_SIZE and is_video_file(f['name']):
                valid_videos.append(f)

        if valid_videos:
            for f in valid_videos:
                selected_indices.append(str(f['file_index']))
                selected_filenames.append(f['name'])
                selected_size += f['size']
            logging.info(f"✅ 策略A命中: 选中 {len(valid_videos)} 个文件")

        else:
            # 策略B: 最大文件
            max_file = None
            max_size = 0
            for f in all_files:
                if f['size'] > max_size:
                    max_size = f['size']
                    max_file = f
            
            if max_file and max_size > MIN_FILE_SIZE:
                idx = max_file['file_index']
                selected_indices.append(str(idx))
                selected_filenames.append(max_file['name'])
                selected_size += max_file['size']
                logging.info(f"✅ 策略B命中: {max_file['name']}")
            else:
                logging.warning(f"❌ 所有文件均太小")
                return None

        return {
            "name": torrent_name,
            "file_size": str(selected_size),
            "total_file_count": str(main_resource.get('file_count', 0)),
            "sub_file_index": ",".join(selected_indices),
            "selected_files": selected_filenames
        }
        
    except Exception as e:
        logging.error(f"解析异常: {e}")
        return None

def create_task(magnet, target_id, target_name):
    meta = analyze_magnet(magnet)
    if not meta: return False

    url = f"{XUNLEI_HOST}/drive/v1/task"
    headers = get_headers()
    payload = {
        "type": "user#download-url",
        "name": meta['name'],
        "file_name": meta['name'],
        "file_size": meta['file_size'],
        "space": XUNLEI_SPACE,
        "params": {
            "target": XUNLEI_SPACE,
            "url": magnet,
            "parent_folder_id": target_id,
            "total_file_count": meta['total_file_count'],
            "sub_file_index": meta['sub_file_index']
        }
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=20)
        return meta['selected_files'] if res.status_code == 200 else False
    except: return False

def get_sub_folders(parent_id):
    folders = []
    try:
        url = f"{XUNLEI_HOST}/drive/v1/files"
        headers = get_headers()
        params = {"parent_id": parent_id, "limit": 100, "pan_auth": headers.get('pan-auth'), "space": XUNLEI_SPACE}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            for item in res.json().get('files', []):
                if item.get('kind') == 'drive#folder' and not item.get('trashed'):
                    folders.append({'name': item.get('name'), 'id': item.get('id')})
    except: pass
    return folders

# ===========================
# 3. Telegram 交互
# ===========================

@bot.message_handler(commands=['token', 'start'])
def handle_token_cmd(message):
    if str(message.chat.id) != CHAT_ID: return
    is_alive = check_token_alive(verbose=True)
    status = "✅ 有效" if is_alive else "❌ 失效"
    msg = f"🔧 **状态面板**\n迅雷状态: {status}\nHost: `{XUNLEI_HOST}`"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔄 刷新Token", callback_data="sys_refresh_token"))
    markup.add(InlineKeyboardButton("🩺 检查连接", callback_data="sys_check_health"))
    bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['check'])
def handle_check(message):
    if str(message.chat.id) != CHAT_ID: return
    if check_token_alive(verbose=True):
        bot.reply_to(message, "✅ Token 正常")
    else:
        bot.reply_to(message, "❌ Token 失效，正在修复...")
        perform_sniffing(message.chat.id)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = str(call.message.chat.id)
    data = call.data

    if data == "sys_refresh_token":
        bot.answer_callback_query(call.id, "开始嗅探...")
        perform_sniffing(chat_id)
        return
    if data == "sys_check_health":
        alive = check_token_alive(verbose=True)
        bot.answer_callback_query(call.id, "Token 有效" if alive else "Token 失效")
        return
    if data == "cancel":
        bot.answer_callback_query(call.id, "已取消")
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        if int(chat_id) in user_pending_tasks: del user_pending_tasks[int(chat_id)]
        return

    if data.startswith("dl|"):
        try: _, target_id, target_name = data.split("|", 2)
        except: return

        magnets = user_pending_tasks.get(int(chat_id))
        if not magnets:
            bot.answer_callback_query(call.id, "任务已过期")
            return
            
        bot.answer_callback_query(call.id, "处理中...")
        status_msg = bot.edit_message_text(f"⏳ 正在添加 {len(magnets)} 个任务...", chat_id, call.message.message_id)
        
        success_files = []
        fail_count = 0
        
        for m in magnets:
            file_names = create_task(m, target_id, target_name)
            if file_names:
                success_files.extend(file_names)
            else:
                fail_count += 1
            time.sleep(1)

        safe_dir = target_name.replace("`", "")
        report = f"📂 **目录**: `{safe_dir}`\n"
        
        if success_files:
            report += f"✅ **成功添加 {len(success_files)} 个文件**:\n"
            for name in success_files[:15]:
                safe_name = name.replace("`", "")
                report += f"• `{safe_name}`\n"
            if len(success_files) > 15:
                report += f"...以及其他 {len(success_files)-15} 个文件"
        else:
            report += "❌ **所有任务添加失败**"
            
        if fail_count > 0:
            report += f"\n⚠️ 有 {fail_count} 个磁力链接解析失败"
        
        bot.edit_message_text(report, chat_id, status_msg.message_id, parse_mode="Markdown")
        if int(chat_id) in user_pending_tasks: del user_pending_tasks[int(chat_id)]

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    if str(message.chat.id) != CHAT_ID: return
    text = message.text.strip()
    magnets = [w for w in text.split() if "magnet:?" in w or w.endswith(".torrent")]
    
    if magnets:
        user_pending_tasks[message.chat.id] = magnets
        markup = InlineKeyboardMarkup()
        folders = get_sub_folders(XUNLEI_PARENT_FILE_ID)
        for f in folders:
            markup.add(InlineKeyboardButton(f"📂 {f['name']}", callback_data=f"dl|{f['id']}|{f['name']}"))
        markup.add(InlineKeyboardButton("⬇️ 默认目录", callback_data=f"dl|{XUNLEI_PARENT_FILE_ID or 'root'}|默认目录"))
        markup.add(InlineKeyboardButton("❌ 取消", callback_data="cancel"))
        bot.reply_to(message, f"⚡️ 发现 {len(magnets)} 个任务，请选择位置：", reply_markup=markup)

if __name__ == "__main__":
    print("🤖 Bot 启动...")
    t = threading.Thread(target=health_check_loop, daemon=True)
    t.start()
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            time.sleep(15)
            logging.error(f"Polling error: {e}")