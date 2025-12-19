import os
import requests
import telebot
import json
import urllib.parse
import time
import re
import base64
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- 环境变量 ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
XUNLEI_HOST = os.getenv('XUNLEI_HOST', '').rstrip('/')
XUNLEI_AUTH = os.getenv('XUNLEI_AUTH', '')
PARENT_FILE_ID = os.getenv('XUNLEI_PARENT_FILE_ID')
RAW_SPACE = os.getenv('XUNLEI_SPACE', '')
XUNLEI_SPACE = urllib.parse.unquote(RAW_SPACE)
XUNLEI_COOKIE = os.getenv('XUNLEI_COOKIE', '')
XUNLEI_SYNO_TOKEN = os.getenv('XUNLEI_SYNO_TOKEN', '')
DB_PATH = os.getenv('XUNLEI_DB_PATH', '')
# 保留环境变量作为兜底
ENV_AUTH = os.getenv('XUNLEI_AUTH', '')

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.rmvb', '.rm', '.mpg', '.mpeg', '.m2ts', '.iso'}
MIN_FILE_SIZE = 200 * 1024 * 1024

bot = telebot.TeleBot(BOT_TOKEN)
user_pending_tasks = {}


def extract_token_from_db():
    """
    暴力扫描 BoltDB 数据库文件，提取有效期最长的 JWT Token
    """
    if not DB_PATH or not os.path.exists(DB_PATH):
        return None

    try:
        # JWT 的特征头: {"alg":"HS256","typ":"JWT"} 的 base64 编码
        # 对应字节: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
        pattern = re.compile(b'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9[a-zA-Z0-9\-\._]+')
        
        with open(DB_PATH, 'rb') as f:
            content = f.read()
            matches = pattern.findall(content)
            
        if not matches:
            return None

        # 找到所有 Token，解码并检查过期时间，取最新的一个
        best_token = None
        max_exp = 0
        
        for m in matches:
            token_str = m.decode('utf-8')
            try:
                # JWT 结构: header.payload.signature
                parts = token_str.split('.')
                if len(parts) != 3: continue
                
                # 解码 payload (中间部分)
                payload_segment = parts[1]
                # 补全 padding 否则 base64 解码会报错
                padding = len(payload_segment) % 4
                if padding:
                    payload_segment += '=' * (4 - padding)
                
                payload = json.loads(base64.urlsafe_b64decode(payload_segment))
                exp = payload.get('exp', 0)
                
                # 取有效期最大的
                if exp > max_exp:
                    max_exp = exp
                    best_token = token_str
            except Exception:
                continue
                
        if best_token:
            # 打印一下日志方便调试
            print(f"🔄 自动获取 Token 成功! 过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max_exp))}")
            return best_token

    except Exception as e:
        print(f"⚠️ 读取数据库失败: {e}")
        
    return None

def get_headers():
    # 优先从数据库获取，失败则用环境变量
    current_token = extract_token_from_db() or ENV_AUTH
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "pan-auth": current_token,
    }
    # ... (Cookie 和 Syno Token 处理保持不变)
    if XUNLEI_COOKIE:
        headers["Cookie"] = XUNLEI_COOKIE
    if XUNLEI_SYNO_TOKEN:
        headers["x-syno-token"] = XUNLEI_SYNO_TOKEN
    return headers


def is_video_file(filename):
    if not filename:
        return False
    ext = os.path.splitext(filename.lower())[1]
    return ext in VIDEO_EXTENSIONS


def collect_all_files(resources, file_list):
    """
    递归收集所有文件（非目录）
    关键：使用 API 返回的 file_index 字段
    """
    for item in resources:
        name = item.get('name', 'Unknown')
        size = item.get('file_size', 0)
        is_dir = item.get('is_dir', False)
        file_index = item.get('file_index')
        
        if is_dir:
            sub_resources = item.get('dir', {}).get('resources', [])
            if sub_resources:
                collect_all_files(sub_resources, file_list)
        else:
            file_list.append({
                'name': name,
                'size': size,
                'file_index': file_index
            })


def analyze_magnet(magnet):
    """解析磁力链接，使用 file_index 字段"""
    url = f"{XUNLEI_HOST}/drive/v1/resource/list"
    params = {"pan_auth": XUNLEI_AUTH}
    payload = {"page_size": 1000, "urls": magnet}
    
    print(f"\n{'='*70}")
    print(f"🔍 [解析中] {magnet[:80]}...")
    
    try:
        res = requests.post(url, params=params, json=payload, headers=get_headers())
        
        if res.status_code != 200:
            print(f"❌ 请求失败 {res.status_code}: {res.text}")
            return None
        
        data = res.json()
        
        if 'list' not in data or 'resources' not in data['list']:
            print(f"❌ 数据结构异常")
            return None
        
        main_resource = data['list']['resources'][0]
        torrent_name = main_resource.get('name', 'Unknown')
        total_file_count = main_resource.get('file_count', 0)
        
        print(f"📁 种子名称: {torrent_name}")
        print(f"📊 文件总数: {total_file_count}")
        
        top_resources = main_resource.get('dir', {}).get('resources', [])
        
        if not top_resources:
            file_size = main_resource.get('file_size', 0)
            print(f"📄 单文件: {torrent_name} ({file_size/1024/1024:.2f} MB)")
            return {
                "name": torrent_name,
                "file_size": str(file_size),
                "total_file_count": str(total_file_count),
                "sub_file_index": "0"
            }
        
        all_files = []
        collect_all_files(top_resources, all_files)
        
        print(f"\n📋 文件列表 (共 {len(all_files)} 个文件):")
        print("-" * 70)
        
        selected_indices = []
        selected_size = 0
        
        for f in all_files:
            name = f['name']
            size = f['size']
            file_index = f['file_index']
            size_mb = size / 1024 / 1024
            
            is_video = is_video_file(name)
            size_ok = size > MIN_FILE_SIZE
            should_select = is_video and size_ok
            
            status = "✅" if should_select else "❌"
            tag = "🎬" if is_video else "📄"
            idx_str = f"{file_index:3}" if file_index is not None else "N/A"
            print(f"  {status} {tag} [idx:{idx_str}] {size_mb:>10.2f}MB | {name}")
            
            if should_select and file_index is not None:
                selected_indices.append(str(file_index))
                selected_size += size
        
        print("-" * 70)
        
        if not selected_indices:
            print("⚠️ 没有视频，回退到大小筛选...")
            for f in all_files:
                if f['size'] > MIN_FILE_SIZE and f['file_index'] is not None:
                    selected_indices.append(str(f['file_index']))
                    selected_size += f['size']
        
        if not selected_indices:
            print("⚠️ 下载全部...")
            for f in all_files:
                if f['file_index'] is not None:
                    selected_indices.append(str(f['file_index']))
                    selected_size += f['size']
        
        print(f"\n✨ 最终选择: {len(selected_indices)} 个文件")
        print(f"   总大小: {selected_size/1024/1024/1024:.2f} GB")
        print(f"   file_index 列表: {','.join(selected_indices)}")
        print(f"{'='*70}\n")
        
        return {
            "name": torrent_name,
            "file_size": str(selected_size),
            "total_file_count": str(total_file_count),
            "sub_file_index": ",".join(selected_indices)
        }
        
    except Exception as e:
        print(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_task(magnet, target_id, target_name):
    meta = analyze_magnet(magnet)
    if not meta:
        return False

    url = f"{XUNLEI_HOST}/drive/v1/task"
    
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
    
    print(f"🚀 创建任务:")
    print(f"   name: {meta['name']}")
    print(f"   total_file_count: {meta['total_file_count']}")
    print(f"   sub_file_index: {meta['sub_file_index']}")
    
    try:
        res = requests.post(url, json=payload, headers=get_headers())
        
        if res.status_code == 200:
            result = res.json()
            if result.get('error'):
                print(f"❌ API错误: {result}")
                return False
            print(f"✅ 成功: {meta['name']}")
            return meta['name']
        else:
            print(f"❌ 失败 {res.status_code}: {res.text}")
            return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


def get_sub_folders(parent_id):
    folders = []
    try:
        url = f"{XUNLEI_HOST}/drive/v1/files"
        params = {"parent_id": parent_id, "limit": 100, "pan_auth": XUNLEI_AUTH, "space": XUNLEI_SPACE}
        res = requests.get(url, params=params, headers=get_headers(), timeout=10)
        if res.status_code == 200:
            data = res.json()
            for item in data.get('files', []):
                if item.get('kind') == 'drive#folder' and not item.get('trashed'):
                    folders.append({'name': item.get('name'), 'id': item.get('id')})
    except Exception as e:
        print(f"获取文件夹失败: {e}")
    return folders


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if str(message.chat.id) != CHAT_ID:
        return
    
    text = message.text.strip()
    all_parts = text.split()
    magnets = [p for p in all_parts if p.startswith("magnet:?") or p.endswith(".torrent")]
    
    if magnets:
        user_pending_tasks[message.chat.id] = magnets
        count = len(magnets)
        
        sub_folders = get_sub_folders(PARENT_FILE_ID)
        
        markup = InlineKeyboardMarkup()
        markup.row_width = 2
        
        if sub_folders:
            buttons = [InlineKeyboardButton(f['name'], callback_data=f"dl|{f['id']}|{f['name'][:10]}") for f in sub_folders]
            markup.add(*buttons)
        else:
            markup.add(InlineKeyboardButton("直接下载", callback_data=f"dl|{PARENT_FILE_ID}|root"))
        
        markup.add(InlineKeyboardButton("❌ 取消", callback_data="cancel"))
        bot.reply_to(message, f"⚡️ 识别到 {count} 个磁力链接\n请选择下载位置：", reply_markup=markup)
    else:
        bot.reply_to(message, "请发送磁力链接")


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    data = call.data
    
    if data == "cancel":
        bot.answer_callback_query(call.id, "已取消")
        bot.delete_message(chat_id, call.message.message_id)
        if chat_id in user_pending_tasks:
            del user_pending_tasks[chat_id]
        return

    if data.startswith("dl|"):
        try:
            _, target_id, target_name = data.split("|", 2)
        except ValueError:
            return

        magnets = user_pending_tasks.get(chat_id)
        if not magnets:
            bot.answer_callback_query(call.id, "任务过期")
            return
        
        bot.answer_callback_query(call.id, f"处理中...")
        bot.edit_message_text(f"⏳ 处理 {len(magnets)} 个任务...", chat_id, call.message.message_id)
        
        success_list = []
        fail_count = 0
        
        for i, magnet in enumerate(magnets, 1):
            print(f"\n{'#'*70}")
            print(f"# 任务 {i}/{len(magnets)}")
            print(f"{'#'*70}")
            
            result_name = create_task(magnet, target_id, target_name)
            
            if result_name:
                success_list.append(result_name)
            else:
                fail_count += 1
            
            if i < len(magnets):
                time.sleep(10)

        report = f"✅ 完成\n📂 {target_name}\n📊 成功:{len(success_list)} 失败:{fail_count}\n"
        if success_list:
            for name in success_list[:5]:
                report += f"🔹 {name}\n"
        
        bot.edit_message_text(report, chat_id, call.message.message_id)
        
        if chat_id in user_pending_tasks:
            del user_pending_tasks[chat_id]


if __name__ == "__main__":
    print("🤖 Bot 启动...")
    print(f"   HOST: {XUNLEI_HOST}")
    
    while True:
        try:
            # 增加 timeout 设置，让连接更持久
            # long_polling_timeout: 告诉 TG 服务器我们要挂多久
            # timeout: 本地客户端等待多久
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ 网络连接中断 ({e})，15秒后重试...")
            time.sleep(15)
