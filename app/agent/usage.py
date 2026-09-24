"""
用量采集模块（01 文档 §3.2）

链路位置：llm_factory.create_llm() 创建模型实例时，把 LLMUsageTracker 作为实例级
callback 挂载上去 —— LangChain 在每次 LLM 调用开始/结束/失败时回调对应钩子，
tracker 零侵入地记账。消费方有两个：
  1. QueryService：请求结束时调用 summary() 打日志（在线可观测）
  2. 03 评估 runner：逐用例收集 tracker 明细，喂给 cost_metrics.py（成本指标）
设计决策：采集用 callback 而非改节点代码 —— 节点只管调 chain.ainvoke，
计量对业务代码完全透明。
"""
import time
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.callbacks import BaseCallbackHandler


@dataclass
class LLMCallRecord:
    """一次 LLM 调用的完整记账条目。

    token 字段可能为 None：OpenAI 兼容端点通常返回 usage，但个别厂商/错误响应
    不带 —— 缺失时成本计算降级为仅延迟统计，绝不因缺字段抛异常（01 §3.2 约束）
    """
    stage: str                       # 归属环节 = 最近祖先 chain 名（LangGraph 节点函数名）
    model: str                       # 模型名（如 deepseek-flash）
    input_tokens: Optional[int]      # usage_metadata.input_tokens
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: int                  # 本次调用耗时（开始到结束）
    success: bool                    # False = on_llm_error 路径
    error: Optional[str]             # 失败时的异常摘要
    ts: float                        # 调用开始时间戳（03 成本模块按此判峰谷档位）
    prompt_cache_hit_tokens: Optional[int] = None   # [05 §3.4] DeepSeek 扩展字段，验证 KV cache 改造效果
    prompt_cache_miss_tokens: Optional[int] = None  # [05 §3.4] 其它 provider 恒为 None