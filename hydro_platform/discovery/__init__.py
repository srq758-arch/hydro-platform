"""数据源发现模块（设计文档 §7）：四级自动发现数据源。

Discovery 只负责找到可能包含目标数据的候选来源，不负责下载和解析。
返回 SourceCandidate 列表，由 Reliability Scoring 排序后选择最佳候选。
"""
