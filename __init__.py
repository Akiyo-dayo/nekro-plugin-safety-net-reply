from __future__ import annotations

from typing import Any

from .fallback import (
    build_fallback_code,
    extract_message_text_from_malformed_code,
    is_plain_text_fallback_candidate,
    sanitize_plain_text,
    split_message_text,
)

try:
    from nekro_agent.api.plugin import NekroPlugin, SandboxMethodType
    from nekro_agent.api.schemas import AgentCtx
    from nekro_agent.core import logger
    from nekro_agent.services.agent import run_agent
    from nekro_agent.services.agent.resolver import ParsedCodeRunData
except ImportError:
    plugin = None
else:
    plugin = NekroPlugin(
        name="安全网回复",
        module_name="nekro_plugin_safety_net_reply",
        description="当模型误把自然语言正文作为沙盒代码返回时，自动改写为预制消息发送工具调用，避免 SyntaxError 后反复迭代失败。",
        version="0.3.0",
        author="Akiyo",
        url="https://github.com/Akiyo-dayo/nekro-plugin-safety-net-reply",
        support_adapter=["onebot_v11", "minecraft", "sse", "discord", "wechatpad", "telegram", "feishu", "wxwork", "wxwork_corp_app"],
        allow_sleep=False,
        sleep_brief="兜底处理模型纯文本回复，确保消息仍通过工具链发出。",
    )

    _ORIGINAL_LIMITED_RUN_CODE = None

    @plugin.mount_sandbox_method(
        SandboxMethodType.TOOL,
        name="安全网纯文本回复",
        description="内部兜底工具：当模型输出纯文本而不是 Python 代码时，将该文本发送到当前聊天频道。",
    )
    async def send_plain_text_response(_ctx: AgentCtx, chat_key: str, message_text: str) -> str:
        """发送由安全网兜底接管的纯文本回复。

        Args:
            chat_key: 聊天频道标识。
            message_text: 要发送的纯文本内容。

        Returns:
            str: 发送结果。
        """
        chunks = split_message_text(message_text)
        for chunk in chunks:
            await _ctx.ms.send_text(chat_key, chunk, _ctx)
        return f"安全网回复已发送，共 {len(chunks)} 段"

    async def _patched_limited_run_code(*args: Any, **kwargs: Any):
        original = _ORIGINAL_LIMITED_RUN_CODE
        if original is None:
            return await run_agent.limited_run_code(*args, **kwargs)

        code_run_data = kwargs.get("code_run_data")
        if code_run_data is None and args:
            code_run_data = args[0]

        message_text = None
        if code_run_data:
            message_text = extract_message_text_from_malformed_code(code_run_data.code_content)
        if (
            code_run_data
            and message_text is None
            and is_plain_text_fallback_candidate(
                code_run_data.code_content,
                code_run_data.raw_content,
            )
        ):
            message_text = sanitize_plain_text(code_run_data.raw_content, code_run_data.code_content)

        if code_run_data and message_text is not None:
            patched_data = ParsedCodeRunData(
                raw_content=code_run_data.raw_content,
                code_content=build_fallback_code(message_text),
                thought_chain=code_run_data.thought_chain,
            )
            if "code_run_data" in kwargs:
                kwargs["code_run_data"] = patched_data
            else:
                args = (patched_data, *args[1:])
            logger.warning(
                "[安全网回复] 检测到模型返回纯文本，已改写为 send_plain_text_response 工具调用。"
            )

        return await original(*args, **kwargs)

    @plugin.mount_init_method()
    async def initialize_plugin():
        global _ORIGINAL_LIMITED_RUN_CODE
        if getattr(run_agent.limited_run_code, "_safety_net_reply_patched", False):
            logger.info("[安全网回复] limited_run_code 已经处于接管状态")
            return
        _ORIGINAL_LIMITED_RUN_CODE = run_agent.limited_run_code
        _patched_limited_run_code._safety_net_reply_patched = True
        run_agent.limited_run_code = _patched_limited_run_code
        logger.info("[安全网回复] 已接管 limited_run_code，用于纯文本回复兜底")

    @plugin.mount_cleanup_method()
    async def cleanup_plugin():
        global _ORIGINAL_LIMITED_RUN_CODE
        if _ORIGINAL_LIMITED_RUN_CODE is not None:
            run_agent.limited_run_code = _ORIGINAL_LIMITED_RUN_CODE
            _ORIGINAL_LIMITED_RUN_CODE = None
            logger.info("[安全网回复] 已恢复 limited_run_code")
