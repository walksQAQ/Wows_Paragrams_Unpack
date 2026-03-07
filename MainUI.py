import sys
import threading
import os
import json
import shutil
import hashlib
import requests
import tkinter as tk
import customtkinter as ctk

from tkinter import filedialog, messagebox

import Ship_data_analyze
from DataViewer import DataViewer
from POToolKit import POToolkit
from GameParams_processer import GameParamsProcessor

# 设置外观主题
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class AppUI:
    def __init__(self, root):
        self.root = root
        # 1. 立即隐藏主窗口，防止渲染时的闪烁和位移
        self.root.withdraw()

        self.root.title("Mir Korabley/World of Warships 游戏数据分析工具")
        self.root.geometry("1400x850")

        # 2. 【核心修改】先初始化路径并加载配置数据到内存，但不涉及UI操作
        self.exe_dir = self.get_executable_dir()
        self.config_file = os.path.join(self.exe_dir, "config.json")
        self.data_dir = os.path.join(self.exe_dir, "data")

        # 预加载配置 (此时 self.server_switch 还没创建，所以只读数据)
        self.config_data = self.load_config()
        self.wows_type = self.config_data.get("wows_type", "Wargaming")
        self.game_path = self.config_data.get("game_path", "未设置")

        # 定义变量并赋予从 config 读取的初值
        self.wows_type_var = tk.StringVar(value=self.wows_type)

        # 3. 构建布局 (此时 setup_ui_layout 内部可以使用 self.wows_type)
        self.setup_ui_layout()

        # 4. 绑定查看器
        self.viewer = DataViewer(self.folder_listbox, self.file_listbox, self.detail_area, log_func=self.log)
        self.folder_listbox.bind("<<ListboxSelect>>", self.viewer.on_folder_select)
        self.file_listbox.bind("<<ListboxSelect>>", self.viewer.on_file_select)

        # 5. 异步显示：仅处理耗时的磁盘检查和窗口显示
        self.root.after(50, self.async_boot_process)

    def get_executable_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def setup_ui_layout(self):
        """仅构建UI骨架，不加载任何实际数据"""
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)
        self.root.grid_columnconfigure(3, weight=3)
        self.root.grid_rowconfigure(0, weight=1)

        # 侧边栏
        self.sidebar_frame = ctk.CTkFrame(self.root, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="WOWS 数据工具",
                                       font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # 功能按钮 (默认全部启用或根据初始状态)
        self.btn_unpack_data = ctk.CTkButton(self.sidebar_frame, text="加载数据文件", command=self.click_load_data)
        self.btn_unpack_data.grid(row=1, column=0, padx=20, pady=10)

        self.btn_data_processor = ctk.CTkButton(self.sidebar_frame, text="解析数据文件", state="disabled",
                                                command=self.click_data_processor)
        self.btn_data_processor.grid(row=2, column=0, padx=20, pady=10)

        self.btn_refresh_gui = ctk.CTkButton(self.sidebar_frame, text="刷新界面", border_width=2, command=self.viewer_refresh_adapter)
        self.btn_refresh_gui.grid(row=3, column=0, padx=20, pady=10)

        self.btn_getnamefromweb = ctk.CTkButton(self.sidebar_frame, text="加载语言文件", command=self.getnamefromweb)
        self.btn_getnamefromweb.grid(row=4, column=0, padx=20, pady=10)

        self.btn_settings = ctk.CTkButton(self.sidebar_frame, text="设置游戏目录", fg_color="#555",
                                          command=self.select_game_path)
        self.btn_settings.grid(row=5, column=0, padx=20, pady=10)

        # --- 服务器选择滑条 (Segmented Button) ---
        self.server_label = ctk.CTkLabel(self.sidebar_frame, text="当前服务器环境:", font=ctk.CTkFont(size=12))
        self.server_label.grid(row=6, column=0, padx=20, pady=(5, 0))

        self.server_switch = ctk.CTkSegmentedButton(self.sidebar_frame,
                                                    values=["Wargaming", "Lesta"],
                                                    command=self.update_wows_type_setting)
        self.server_switch.grid(row=7, column=0, padx=20, pady=(5, 15))
        self.server_switch.set(self.wows_type)

        # 日志
        self.log_area = ctk.CTkTextbox(self.sidebar_frame, width=200, font=("Consolas", 11))
        self.log_area.grid(row=6, column=0, padx=10, pady=10, sticky="nsew")

        # 列表区
        self.folder_listbox = self.create_styled_listbox(self.root, "数据分类", 1)
        self.file_listbox = self.create_styled_listbox(self.root, "内容列表", 2)

        # 详情区
        self.detail_frame = ctk.CTkFrame(self.root, corner_radius=0)
        self.detail_frame.grid(row=0, column=3, sticky="nsew", padx=(1, 10), pady=10)
        self.detail_area = ctk.CTkTextbox(self.detail_frame, font=("Consolas", 12), corner_radius=5)
        self.detail_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.setup_menu()

    def create_styled_listbox(self, parent, label_text, col):
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="nsew", padx=1, pady=0)
        ctk.CTkLabel(frame, text=label_text, font=ctk.CTkFont(weight="bold")).pack(pady=5)
        container = ctk.CTkFrame(frame, fg_color="#ffffff", corner_radius=6)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar = ctk.CTkScrollbar(container, orientation="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=2, pady=2)
        lb = tk.Listbox(container, bg="#ffffff", fg="black", borderwidth=0, highlightthickness=0,
                        font=("微软雅黑", 10), selectbackground="#1f538d", yscrollcommand=scrollbar.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        scrollbar.configure(command=lb.yview)
        return lb

    def async_boot_process(self):
        """异步启动逻辑：先处理配置，再显示窗口"""
        # 1. 耗时IO：加载配置 (在后台处理)
        self.init_data_and_config()

        self.check_data_file()

        # 加载映射表
        self.viewer.reload_all_analyzers(log_func=self.log)

        # 居中显示窗口
        self.center_window()
        self.root.deiconify()

        self.log(f"当前选择的服务器: {self.wows_type}")
        self.viewer_refresh_adapter()

    def init_data_and_config(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        config = self.load_config()
        default = self.default_config()
        changed = False
        for k, v in default.items():
            if k not in config:
                config[k] = v
                changed = True
        if changed: self.save_config(config)

        self.config_data = config
        self.game_path = config["game_path"]
        self.game_version = config["game_version"]
        self.game_data_state = config["game_data_state"]
        self.wows_type = config["wows_type"]
        self.wows_type_var.set(self.wows_type)
        self.check_data_file()

    def center_window(self):
        """计算屏幕居中位置，防止位移"""
        self.root.update_idletasks()
        width = 1400
        height = 850
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def viewer_refresh_adapter(self):
        self.viewer.refresh()

    def setup_menu(self):
        """保持原有的原生菜单功能，因为 CTK 对原生菜单支持最好"""
        self.menubar = tk.Menu(self.root)
        self.setting_menu = tk.Menu(self.menubar, tearoff=0)
        self.setting_menu.add_command(label="重置软件设置", command=self.reset_config)
        self.setting_menu.add_separator()
        self.menubar.add_cascade(label="高级选项", menu=self.setting_menu)
        self.root.configure(menu=self.menubar)

    def update_wows_type_setting(self, value=None):
        """
        兼容滑条和菜单切换的回调函数，解决参数个数报错问题
        """
        if value is not None:
            # 滑条触发
            selected_type = value
            self.wows_type_var.set(selected_type)
        else:
            # 菜单触发
            selected_type = self.wows_type_var.get()
            self.server_switch.set(selected_type)

        self.wows_type = selected_type
        self.config_data["wows_type"] = selected_type
        self.save_config()
        self.log(f"切换至服务器: {selected_type}")

    def check_data_file(self):
        target_names = ["GameParams_py2.data","GameParams.data"]
        exists = any(os.path.exists(os.path.join(self.data_dir, f)) for f in target_names)

        if exists and self.game_data_state:
            self.btn_data_processor.configure(state=tk.NORMAL)
        else:
            self.btn_data_processor.configure(state=tk.DISABLED)
        return exists

    def click_load_data(self):
        if self.wows_type == "未选择":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏服务器")
        if self.game_path == "未设置":
            messagebox.showerror("错误","请先在“设置”菜单中选择游戏目录")
            return

        self.btn_unpack_data.configure(state=tk.DISABLED)
        self.log("正在加载游戏数据")

        def worker():
            from GameParams_extractor import GameParams_extractor
            extractor = GameParams_extractor(self.game_path,self.wows_type)
            success, result = extractor.extract()

            if success:
                message = result["msg"]
                new_version = result["version"]
                self.log(message)

                self.game_data_state = True
                self.game_version = new_version

                self.config_data["game_version"] = self.game_version
                self.config_data["game_data_state"] = self.game_data_state
                self.save_config()

                messagebox.showinfo("完成", f"{self.game_version}版本数据提取成功！现在可以点击'解析数据文件'了")
                self.root.after(10, self.check_data_file)
            else:
                self.log(f"错误,{result}")
                messagebox.showerror("错误", result)

            self.root.after(10, lambda: self.btn_unpack_data.configure(state=tk.NORMAL))
        threading.Thread(target=worker, daemon=True).start()

    def fetch_remote_sha(self, repo_path):
        """
        通过 GitHub API 获取远程文件的 Git-SHA 指纹
        用于判断云端 global.mo 是否有更新
        """
        import requests
        import urllib.request

        api_url = f"https://api.github.com/repos/{repo_path}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/vnd.github.v3+json"
        }

        try:
            # 获取系统代理设置
            proxies = urllib.request.getproxies()
            # 发起 API 请求
            response = requests.get(api_url, headers=headers, timeout=8, proxies=proxies)

            if response.status_code == 200:
                sha = response.json().get('sha')
                return sha
            else:
                # 如果 API 限制频率或报错，返回 None 触发普通下载逻辑
                return None
        except Exception:
            # 网络超时或异常，返回 None 以确保后续下载逻辑能作为保底运行
            return None

    def getnamefromweb(self):
        if self.wows_type == "未选择":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏服务器")
            return
        if self.game_path == "未设置":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏目录")
            return

        self.btn_getnamefromweb.configure(state=tk.DISABLED)
        self.log(f"正在加载 {self.wows_type} 客户端文本数据...")

        def worker():
            # 定义转换逻辑的内部工具函数
            def run_convert():
                self.log("正在使用原生 Python 库转换数据...")
                try:
                    import polib

                    mo_path = os.path.normpath(os.path.abspath(os.path.join(self.data_dir, "global.mo")))
                    po_path = os.path.normpath(os.path.abspath(os.path.join(self.data_dir, "global.po")))

                    # 1. 加载二进制 MO 文件
                    mo = polib.mofile(mo_path)

                    # 2. 创建一个新的 PO 对象
                    po = polib.POFile()
                    po.metadata = mo.metadata

                    # 3. 将 MO 的条目逐个填入 PO
                    for entry in mo:
                        po.append(entry)

                    # 4. 保存为 PO 文本格式
                    po.save(po_path)

                    # 5. 清理临时的 MO 文件
                    if os.path.exists(mo_path):
                        os.remove(mo_path)

                    self.log("原生转换成功！已生成 data/global.po")

                except Exception as e:
                    raise Exception(f"原生转换失败: {str(e)}")

            try:
                import requests
                import urllib.request

                if self.wows_type == "Wargaming":
                    bin_root = os.path.join(self.game_path, "bin")
                    if not os.path.exists(bin_root):
                        raise Exception("找不到游戏 bin 目录")

                    folders = [f for f in os.listdir(bin_root) if
                               f.isdigit() and os.path.isdir(os.path.join(bin_root, f))]
                    if not folders:
                        raise Exception("未找到有效的版本文件夹")
                    latest_bin = sorted(folders, key=int)[-1]

                    # 路径尝试：zh_sg -> zh_cn
                    mo_src_path = os.path.join(bin_root, latest_bin, "res/texts/zh_sg/LC_MESSAGES/global.mo")
                    if not os.path.exists(mo_src_path):
                        alt_path = os.path.join(bin_root, latest_bin, "res/texts/zh_cn/LC_MESSAGES/global.mo")
                        if os.path.exists(alt_path):
                            mo_src_path = alt_path
                        else:
                            raise Exception("本地目录找不到 global.mo 文件")

                    shutil.copy2(mo_src_path, os.path.join(self.data_dir, "global.mo"))
                    self.log(f"已从本地提取 global.mo")
                    run_convert()  # 修正：调用时不传 self


                elif self.wows_type == "Lesta":

                    # 1. 检查版本指纹 (SHA)

                    repo_api_path = "LocalizedKorabli/Korabli-LESTA-L10N/contents/Localizations/latest/global.mo"

                    self.log("正在检查远程版本指纹...")

                    cloud_sha = self.fetch_remote_sha(repo_api_path)  # 调用刚才写的 API 方法

                    # 本地路径定义

                    mo_path = os.path.join(self.data_dir, "global.mo")

                    po_path = os.path.join(self.data_dir, "global.po")

                    version_file = os.path.join(self.data_dir, "version.json")

                    # 读取本地记录的指纹

                    local_sha = None

                    if os.path.exists(version_file):

                        try:

                            with open(version_file, "r") as f:

                                local_sha = json.load(f).get("global_mo_sha")

                        except:
                            local_sha = None

                    # --- 校验逻辑：哈希匹配且本地文件存在 ---

                    if cloud_sha and local_sha == cloud_sha and os.path.exists(mo_path):

                        self.log("✅ 校验一致：本地数据已是最新，跳过下载。")

                        success_download = True

                        # 如果 global.po 被删了，即使 mo 还在也要转一次

                        if not os.path.exists(po_path):
                            run_convert()

                    else:

                        # 2. 否则执行原有的多节点轮询逻辑

                        urls = [

                            "https://gitlab.com/localizedkorabli/korabli-lesta-l10n/-/raw/main/Localizations/latest/global.mo",

                            "https://github.com/LocalizedKorabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",

                            "https://gitee.com/localized-korabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",

                        ]

                        self.log(f"版本过时或本地缺失，开始同步最新 global.mo...")

                        system_proxies = urllib.request.getproxies()

                        success_download = False

                        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

                        for url in urls:

                            try:

                                self.log(f"尝试从节点下载: {url.split('/')[2]}...")

                                response = requests.get(url, headers=headers, timeout=15, proxies=system_proxies)

                                response.raise_for_status()

                                with open(mo_path, "wb") as f:

                                    f.write(response.content)

                                self.log("下载成功！")

                                success_download = True

                                # 下载成功后立即保存新的指纹

                                if cloud_sha:
                                    with open(version_file, "w") as f:
                                        json.dump({"global_mo_sha": cloud_sha}, f)

                                break


                            except Exception as e:

                                self.log(f"当前节点连接失败，正在切换...")

                                continue

                        if not success_download:
                            raise Exception("所有同步节点均无法连接，请检查网络或代理。")

                        # 只有真正下载了新文件才转换

                        run_convert()

                self.log("开始分拆语言文件")
                tool = POToolkit(input_po_name="data/global.po")
                try:
                    tool.run_all()
                    self.log("分拆语言文件成功")

                    self.log("正在重载分析器映射...")
                    self.log("正在刷新界面列表...")
                except Exception as e:
                    self.log(f"po转json出错: {str(e)}")
                    messagebox.showinfo("错误", f"po转json出错: {str(e)}")
                messagebox.showinfo("完成", "游戏文本提取完成！")

            except Exception as e:
                self.log(f"处理失败: {str(e)}")
                messagebox.showerror("错误", f"处理过程中出错:\n{e}")

            finally:
                self.root.after(10, lambda: self.btn_getnamefromweb.configure(state=tk.NORMAL))

        # 开启后台线程
        threading.Thread(target=worker, daemon=True).start()

    def click_data_processor(self):
        data_folder = self.data_dir
        split_dir = os.path.join("data", "split")

        if os.path.exists(split_dir):
            shutil.rmtree(split_dir)
            self.log(f"已清空目录{split_dir}")

        self.btn_data_processor.configure(state=tk.DISABLED)

        data_folder = "data"
        def worker():
            try:
                processor = GameParamsProcessor()
                self.log("正在解析游戏数据")
                success, message = processor.load_and_decrypt(data_folder)
                self.log(message)

                if not success:
                    messagebox.showerror("错误",message)
                    return

                self.log("正在拆分游戏数据文件")
                ok, msg = processor.run_split_export(data_folder, split_dir)
                self.log(msg)

                if ok:
                    self.log(f"解析完成的数据文件已存储在{split_dir}")
                    self.game_data_state = True
                    self.config_data["game_data_state"] = True
                    self.save_config()
                    self.viewer_refresh_adapter()

            except Exception as e:
                self.log(f"数据解析出错，{e}")
                messagebox.showerror("错误",f"数据解析出错，{e}")
            finally:
                self.root.after(10, lambda: self.btn_data_processor.configure(state=tk.NORMAL))
        threading.Thread(target=worker,daemon=True).start()

    def log(self, msg):
        """向左侧日志框输出 (增加线程安全支持)"""
        def _append():
            self.log_area.insert(tk.END, f"{msg}\n")
            self.log_area.see(tk.END)
        # 使用 after 确保在主线程更新 UI，防止打包后多线程操作 UI 崩溃
        self.root.after(0, _append)

    def save_config(self, data=None):
        """
        修复 TypeError: 增加可选参数 data
        :param data: 如果传入字典则保存该字典，否则保存内存中的 self.config_data
        """
        # 核心修复：如果 init_data_and_config 传了 config 进来，就用传进来的
        target_to_save = data if data is not None else self.config_data

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(target_to_save, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    def load_config(self):
        """读取配置，确保返回完整的默认字典"""
        default = self.default_config()
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # 建议：将读取到的数据与默认值合并，防止老版本配置文件缺失字段
                        for key, value in default.items():
                            if key not in data:
                                data[key] = value
                        return data
            except Exception as e:
                print(f"读取配置失败: {e}")
        return default

    # 设置-选择游戏目录
    def select_game_path(self):
        path = filedialog.askdirectory(title="选择游戏安装目录")
        if path:
            self.game_path = path
            self.config_data["game_path"] = path
            self.save_config()
            self.log(f"已选择游戏目录：{path}")
            messagebox.showinfo("设置", f"已选择游戏目录：{path}")

    # 设置-重置所有配置
    def reset_config(self):
        confirm = messagebox.askyesno("设置", "确定要删除所有保存的配置并恢复默认吗？\n此操作不可撤销。")
        if confirm:
            self.config_data = self.default_config()
            self.save_config()
            self.initialization()
            self.check_data_file()
            self.log("--- 配置已重置 ---")
            self.wows_type_var.set("未选择")
            messagebox.showinfo("设置","已重置完成")

    # 初始化
    def initialization(self):
        if getattr(sys, "frozen", False):
            self.exe_dir = os.path.dirname(sys.executable)
        else:
            self.exe_dir = os.path.dirname(os.path.abspath(__file__))

        self.config_file = os.path.join(self.exe_dir, "config.json")
        self.data_dir = os.path.join(self.exe_dir, "data")

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        if not os.path.exists(self.config_file):
            # 如果不存在，定义初始默认配置
            self.config_data = self.default_config()
            self.save_config()
        else:
            self.config_data = self.load_config()
            default_config = self.default_config()
            for key,value in default_config.items():
                if key not in self.config_data:
                    self.config_data[key] = value

        self.game_path = self.config_data["game_path"]
        self.game_version = self.config_data["game_version"]
        self.game_data_state = self.config_data["game_data_state"]
        self.wows_type = self.config_data["wows_type"]

        if not hasattr(self, "wows_type_var"):
            self.wows_type_var = tk.StringVar()
        self.wows_type_var.set(self.wows_type)

        self.root.after(10, self.check_data_file)

    def get_local_file_hash(self, file_path):
        """计算本地文件的 SHA256 哈希值"""
        if not os.path.exists(file_path):
            return None
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # 分块读取，防止大文件撑爆内存
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def smart_download_by_hash(self, url, filename, cloud_hash):
        """
        通过哈希值判断是否需要下载。
        返回: (bool_是否成功/跳过, str_状态描述)
        """
        save_path = os.path.join(self.base_path, filename)
        local_hash = self.get_local_file_hash(save_path)

        # 1. 校验本地哈希
        if local_hash and local_hash.lower() == cloud_hash.lower():
            return True, f"本地校验通过: {filename} 已是最新。"

        # 2. 执行下载
        try:
            # 使用 stream=True 避免大文件占用过多内存
            response = requests.get(url, stream=True, timeout=30)
            if response.status_code != 200:
                return False, f"下载失败: HTTP {response.status_code}"

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 3. 下载后校验
            new_local_hash = self.get_local_file_hash(save_path)
            if new_local_hash and new_local_hash.lower() == cloud_hash.local():
                return True, f"同步完成: {filename} 下载并校验成功。"
            else:
                return False, f"校验失败: {filename} 运行哈希不匹配。"

        except Exception as e:
            return False, f"网络错误: {str(e)}"

    # 默认配置
    def default_config(self):
        return{
            "game_path": "未设置",
            "game_version": "Unknown",
            "game_data_state": False,
            "wows_type": "未选择"
        }

if __name__ == "__main__":
    root = tk.Tk()
    app = AppUI(root)
    root.mainloop()