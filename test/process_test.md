# 查看所有进程的命令行参数
Get-WmiObject Win32_Process | Select-Object Name, ProcessId, CommandLine

# 查看特定进程（如 qitu.exe）的参数
Get-WmiObject Win32_Process -Filter "Name='qitu.exe'" | Select-Object Name, ProcessId, CommandLine

# 查看包含特定字符串的进程
Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*qitu*" } | Select-Object Name, ProcessId, CommandLine