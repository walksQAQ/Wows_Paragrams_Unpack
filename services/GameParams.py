"""
GameParams 桩类 —— pickle.loads 反序列化旧版 .data 文件所需。

Wargaming 的 GameParams.data 使用 pickle 序列化，其中引用了
GameParams.TypeInfo / GPData / GameParams / UIParams 等类。
此文件提供最小桩类，使 pickle.loads 能成功加载数据。
"""


class TypeInfo(object):
    pass


class GPData(object):
    pass


class GameParams:
    pass


class UIParams:
    pass
