import hashlib
import uuid
import platform
import subprocess
import os
from utils.log_manager import LogManager

def get_software_id():
    """
    生成唯一的软件 ID (基于硬件特征)
    在同一台机器上生成的 ID 必须一致，不同机器必须不同。
    
    使用多种硬件特征组合以提高唯一性和稳定性：
    1. Windows: 使用 wmic csproduct get uuid
    2. Linux: 使用 /etc/machine-id 或 /var/lib/dbus/machine-id
    3. Mac: 使用 ioreg -rd1 -c IOPlatformExpertDevice
    4. 兜底: 使用 uuid.getnode() (基于 MAC 地址)
    """
    machine_unique_str = ""
    
    system = platform.system()
    
    try:
        if system == "Windows":
            # 尝试获取 Windows UUID
            cmd = "wmic csproduct get uuid"
            try:
                # 使用 subprocess.check_output 执行命令
                # creationflags=0x08000000 防止弹出控制台窗口 (CREATE_NO_WINDOW)
                creation_flags = 0
                if os.name == 'nt':
                    creation_flags = 0x08000000
                    
                output = subprocess.check_output(cmd, shell=True, creationflags=creation_flags).decode().strip()
                # wmic 输出通常包含两行：UUID 和实际值
                lines = output.split('\n')
                for line in lines:
                    line = line.strip()
                    if line and "UUID" not in line:
                        machine_unique_str = line
                        break
            except Exception:
                pass
                
        elif system == "Linux":
            # 尝试读取 machine-id
            files = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
            for f in files:
                if os.path.exists(f):
                    with open(f, 'r') as file:
                        machine_unique_str = file.read().strip()
                        break
                        
        elif system == "Darwin": # macOS
            # 尝试获取 IOPlatformUUID
            cmd = "ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformUUID"
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                # 输出格式类似: "IOPlatformUUID" = "00000000-0000-1000-8000-0016CB96B193"
                if "=" in output:
                    machine_unique_str = output.split('=')[1].strip().replace('"', '')
            except Exception:
                pass
                
    except Exception as e:
        try:
            LogManager.instance().warning(f"获取硬件 ID 失败: {e}")
        except Exception:
            pass

    # 如果上述方法都失败，或者获取到的字符串为空，使用 uuid.getnode() 作为兜底
    # uuid.getnode() 获取 MAC 地址
    if not machine_unique_str:
        machine_unique_str = str(uuid.getnode())

    # 组合一些其他稳定的系统信息，增加混淆
    # 注意：不要使用主机名或用户名，因为这些可能会变
    combined_str = f"{machine_unique_str}-{platform.machine()}-{platform.processor()}"
    
    # 添加盐值 (Salt) 增加复杂度，防止轻易反推
    salt = "BirdPictureManager_Unique_Salt_2025_@#$"
    final_str = f"{salt}|{combined_str}|{salt}"

    # 计算 MD5 哈希
    m = hashlib.md5()
    m.update(final_str.encode('utf-8'))
    # 获取前 16 位作为 ID (或者更长，看需求)
    # 格式化为大写
    full_hash = m.hexdigest().upper()
    
    # 格式化为 XXXX-XXXX-XXXX-XXXX
    formatted_id = f"{full_hash[:4]}-{full_hash[4:8]}-{full_hash[8:12]}-{full_hash[12:16]}"
    
    return formatted_id

if __name__ == "__main__":
    pass
