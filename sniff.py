import subprocess
import re
import time
import logging
import select

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def capture_token(timeout=60, port="2345", interface="any"):
    """
    启动 tcpdump 监听，逻辑复刻自用户验证成功的脚本
    """
    logging.info(f"🕵️‍♂️ [Sniffer] 启动监听... (端口: {port}, 接口: {interface}, 超时: {timeout}s)")
    
    # 你的成功脚本用的参数：-i any -A -s 0 -l
    cmd = ["tcpdump", "-i", interface, "-A", "-s", "0", "-l", "-n", f"port {port}"]
    
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.DEVNULL, 
        universal_newlines=False # 保持字节流
    )

    start_time = time.time()
    found_token = None

    try:
        # 使用 select 实现带超时的读取，避免 for line 死循环卡死 Bot
        while time.time() - start_time < timeout:
            # 检查是否有数据可读 (超时 1 秒)
            reads = [process.stdout.fileno()]
            ret = select.select(reads, [], [], 1.0)

            if ret[0]:
                line = process.stdout.readline()
                if not line:
                    continue
                
                try:
                    line_str = line.decode('utf-8', errors='ignore')
                except:
                    continue

                # 🟢 核心修改：删除了 "GET" 判断
                # 你的截图显示 POST 请求也带 pan_auth，所以只要有 pan_auth 就抓
                if "pan_auth=" in line_str:
                    match = re.search(r'pan_auth=([a-zA-Z0-9\-\._]+)', line_str)
                    if match:
                        found_token = match.group(1)
                        logging.info(f"🎯 [Sniffer] 捕获成功: {found_token[:15]}...")
                        break
            
            # 检查进程是否意外退出
            if process.poll() is not None:
                break

    except Exception as e:
        logging.error(f"❌ [Sniffer] 错误: {e}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    return found_token

# 本地测试用
if __name__ == "__main__":
    # 如果你在本地跑，记得确认端口和网卡
    token = capture_token(port="2345", interface="any") 
    if token:
        print(f"Token: {token}")
    else:
        print("Timeout.")