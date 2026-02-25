import sys
import threading
import os
import json
import shutil
import tkinter as tk

from tkinter import scrolledtext, filedialog, messagebox
from DataViewer import DataViewer
from POToolKit import POToolkit
from GameParams_processer import GameParamsProcessor

class AppUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mir Korabley游戏数据查看工具")
        self.root.geometry("1600x900")

        # 初始化
        self.initialization()

        # 顶部菜单栏
        self.menubar = tk.Menu(self.root)

        # 子菜单-设置
        self.setting_menu = tk.Menu(self.menubar, tearoff=0)
        self.setting_menu.add_command(label="设置游戏目录", command=self.select_game_path)
        self.setting_menu.add_command(label="重置软件设置", command=self.reset_config)
        # 分割线
        self.setting_menu.add_separator()
        self.setting_menu.add_radiobutton(
            label="Wargaming服(直营服)/360服(国服)",
            variable = self.wows_type_var,
            value = "Wargaming",
            command = self.update_wows_type_setting
        )
        self.setting_menu.add_radiobutton(
            label="Lesta服(俄服)",
            variable = self.wows_type_var,
            value = "Lesta",
            command = self.update_wows_type_setting
        )

        # 向顶部菜单添加子菜单
        self.menubar.add_cascade(label="设置", menu=self.setting_menu)
        self.root.config(menu=self.menubar)

        # 左侧侧边拦容器 (Frame)
        self.left_side = tk.Frame(self.root, width=300)
        self.left_side.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=10)
        self.left_side.pack_propagate(False)

        # 中间：数据分类 (向左对齐)
        self.folder_frame = tk.Frame(self.root, width=200)
        self.folder_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=10)
        f_list_container = tk.Frame(self.folder_frame)
        f_list_container.pack(fill=tk.BOTH, expand=True)
        self.folder_listbox = tk.Listbox(f_list_container, width=25, font=("微软雅黑", 10), exportselection=False)
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.folder_scrollbar = tk.Scrollbar(f_list_container, orient=tk.VERTICAL, command=self.folder_listbox.yview)
        self.folder_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=self.folder_scrollbar.set)

        # 中间：分类内容列表 (向左对齐)
        self.file_frame = tk.Frame(self.root, width=250)
        self.file_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=10)
        file_list_container = tk.Frame(self.file_frame)
        file_list_container.pack(fill=tk.BOTH, expand=True)
        self.file_listbox = tk.Listbox(file_list_container, width=35, font=("微软雅黑", 10), exportselection=False)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_scrollbar = tk.Scrollbar(file_list_container, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=self.file_scrollbar.set)

        # 最右侧：JSON 详情展示 (填充剩余空间)
        self.detail_frame = tk.Frame(self.root)
        self.detail_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=10)
        self.detail_area = scrolledtext.ScrolledText(self.detail_frame, font=("Consolas", 10), bg="#f8f8f8")
        self.detail_area.pack(fill=tk.BOTH, expand=True)

        # 初始化 DataViewer 并绑定二级点击事件
        self.viewer = DataViewer(self.folder_listbox, self.file_listbox, self.detail_area)
        self.folder_listbox.bind("<<ListboxSelect>>", self.viewer.on_folder_select)
        self.file_listbox.bind("<<ListboxSelect>>", self.viewer.on_file_select)

        # 左侧侧边栏 - 按钮容器（Frame）
        self.btn_frame = tk.Frame(self.left_side)
        self.btn_frame.pack(anchor="w", padx=10, pady=10)
        self.left_side.pack_propagate(False)

        # 按钮-加载数据文件
        self.btn_unpack_data = tk.Button(
            self.btn_frame,
            text="加载数据文件",
            width=16,
            anchor=tk.CENTER,
            command=self.click_load_data
        )
        self.btn_unpack_data.pack(padx=10, pady=5)

        # 按钮-解析数据文件
        self.btn_data_processor = tk.Button(
            self.btn_frame,
            text="解析数据文件",
            width=16,
            anchor=tk.CENTER,
            command=self.click_data_processor,
            state=tk.DISABLED
        )
        self.btn_data_processor.pack(padx=10, pady=5)

        # 按钮-刷新数据信息
        self.btn_refresh_gui = tk.Button(
            self.btn_frame,
            text="刷新数据信息",
            width=16,
            anchor=tk.CENTER,
            command=self.viewer.refresh
        )
        self.btn_refresh_gui.pack(padx=10, pady=5)

        # 按钮-加载语言文件
        self.btn_getnamefromweb = tk.Button(
            self.btn_frame,
            text="加载语言文件",
            width=16,
            anchor=tk.CENTER,
            command=self.getnamefromweb
        )
        self.btn_getnamefromweb.pack(padx=10, pady=5)

        # 左下侧-运行日志区
        # 运行日志框架（Frame）
        self.log_frame = tk.Frame(self.left_side)
        self.log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题
        self.log_label = tk.Label(self.log_frame, text="运行日志")
        self.log_label.pack(anchor="w", padx=15, pady=5)

        # 日志显示区
        self.log_area = scrolledtext.ScrolledText(self.log_frame, width=32, height=18, font=("Consolas", 9))
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        # 初始填充一行文字# 初始填充信息
        self.root.after(10, self.viewer.refresh)
        self.log(f"当前设置的游戏目录：{self.game_path}")
        if self.wows_type == "未选择":
            self.log(f"当前未选择对应游戏服务器")
        else:
            self.log(f"当前选择的游戏服务器:{self.wows_type}")

    def check_data_file(self):
        target_names = ["GameParams_py2.data","GameParams.data"]
        exists = any(os.path.exists(os.path.join(self.data_dir, f)) for f in target_names)

        if exists and self.game_data_state:
            self.btn_data_processor.config(state=tk.NORMAL)
        else:
            self.btn_data_processor.config(state=tk.DISABLED)
        return exists

    def click_load_data(self):
        if self.wows_type == "未选择":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏服务器")
        if self.game_path == "未设置":
            messagebox.showerror("错误","请先在“设置”菜单中选择游戏目录")
            return

        self.btn_unpack_data.config(state=tk.DISABLED)
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

            self.root.after(10, lambda: self.btn_unpack_data.config(state=tk.NORMAL))
        threading.Thread(target=worker, daemon=True).start()

    def getnamefromweb(self):
        if self.wows_type == "未选择":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏服务器")
            return
        if self.game_path == "未设置":
            messagebox.showerror("错误", "请先在“设置”菜单中选择游戏目录")
            return

        self.btn_getnamefromweb.config(state=tk.DISABLED)
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
                    # 增加 jsDelivr 镜像源提高国内成功率
                    urls = [
                        "https://github.com/LocalizedKorabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",
                        "https://gitlab.com/localizedkorabli/korabli-lesta-l10n/-/raw/main/Localizations/latest/global.mo",
                        "https://gitee.com/localized-korabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",
                    ]

                    self.log(f"正在从仓库下载最新的 global.mo...")

                    # 自动获取系统代理设置
                    system_proxies = urllib.request.getproxies()
                    success_download = False
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

                    for url in urls:
                        try:
                            self.log(f"尝试从服务器下载: {url.split('/')[2]}...")
                            response = requests.get(url, headers=headers, timeout=15, proxies=system_proxies)
                            response.raise_for_status()

                            with open(os.path.join(self.data_dir, "global.mo"), "wb") as f:
                                f.write(response.content)

                            self.log("下载成功！")
                            success_download = True
                            break

                        except Exception:
                            self.log(f"当前节点不可用，尝试切换...")
                            continue

                    if not success_download:
                        raise Exception("所有节点均无法连接，请检查网络或开启代理。")

                    run_convert()  # 修正：调用时不传 self

                self.log("开始分拆语言文件")
                tool = POToolkit(input_po_name="data/global.po")
                try:
                    tool.run_all()
                    self.log("分拆语言文件成功")
                    self.log("正在刷新界面列表...")
                    self.root.after(10, self.viewer.refresh)
                except Exception as e:
                    self.log(f"po转json出错: {str(e)}")
                    messagebox.showinfo("错误", f"po转json出错: {str(e)}")
                messagebox.showinfo("完成", "游戏文本提取完成！")

            except Exception as e:
                self.log(f"处理失败: {str(e)}")
                messagebox.showerror("错误", f"处理过程中出错:\n{e}")

            finally:
                self.root.after(10, lambda: self.btn_getnamefromweb.config(state=tk.NORMAL))

        # 开启后台线程
        threading.Thread(target=worker, daemon=True).start()

    def click_data_processor(self):
        data_folder = self.data_dir
        split_dir = os.path.join("data", "split")

        if os.path.exists(split_dir):
            shutil.rmtree(split_dir)
            self.log(f"已清空目录{split_dir}")

        self.btn_data_processor.config(state=tk.DISABLED)

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
                    self.root.after(10, self.viewer.refresh)
            except Exception as e:
                self.log(f"数据解析出错，{e}")
                messagebox.showerror("错误",f"数据解析出错，{e}")
            finally:
                self.root.after(10, lambda: self.btn_data_processor.config(state=tk.NORMAL))
        threading.Thread(target=worker,daemon=True).start()

    def log(self, msg):
        """向左侧日志框输出"""
        self.log_area.insert(tk.END, f"{msg}\n")
        self.log_area.see(tk.END)

    def save_config(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, indent=4, ensure_ascii=False)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                print(f"读取配置失败: {e}")
                messagebox.showwarning("警告", f"配置文件读取失败，将尝试使用备份或默认设置。\n错误: {e}")
        return {
                    # 初始化设置文件配置
                    "game_path": "未设置"
                }

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

    def update_wows_type_setting(self):
        selected_type = self.wows_type_var.get()
        self.wows_type = selected_type
        self.config_data["wows_type"] = selected_type
        self.save_config()
        self.log(f"已将游戏服务器切换为{selected_type}")

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