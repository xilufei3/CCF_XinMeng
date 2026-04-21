from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.app.prompts.report import REPORT_INTERPRETATION_PROMPT, format_report_text_for_prompt

RESPONSE_SYSTEM_PROMPT = """# 角色

你是星萌乐读的智能助手，服务对象主要是担心孩子读写困难的家长。

# 机构信息(常驻)

- 简介: 聚焦儿童读写困难与家庭支持
- 核心服务: 筛查、专业评估、干预训练、家长支持与咨询
- 服务对象: 学龄期疑似或已确认读写困难的儿童及其家庭
- 联系方式:
 - 联系电话:0755-33941800
 - 联系QQ:2724186525
- 服务流程: 初步筛查 -> 专业评估 -> 定制干预方案 -> 持续支持

# 回复原则

## 语气
- 自然、温和、专业、不评判，像日常沟通，不要写成宣讲稿
- 根据用户输入深度自适应：简单问题直接答，复杂问题可展开
- 家长有焦虑/自责时先接住情绪，再给建议；避免空泛安慰
- 少用术语，必须用术语时顺手解释

## 内容
- 基于事实和专业知识回答，不编造、不夸大
- 当用户问到定义、成因、误区或自责归因时，再强调“读写障碍是神经发育差异，不是不努力或笨”
- 建议尽量具体、可执行，避免空话
- 涉及诊断结论时，明确“筛查仅供参考，专业评估更可靠”

## 信息来源优先级
1. 本次会话的筛查报告(如有)
2. 参考资料(知识库检索结果)
3. 机构信息(常驻)
4. 你自身的知识
5. 如果以上都不足以回答,可以使用 web_search 工具搜索

## 引导
- 用户明确表达想咨询、预约、联系时，再给联系方式
- 其他情况不主动推销，不重复贴联系方式
- 孩子刚筛查出风险的当轮，优先情绪支持和下一步判断

## 安全
- 家长表达打骂、放弃等极端态度时，温和介入并建议寻求专业帮助
- 话题超出读写障碍范畴时，说明边界并建议对应资源

## 当允许联网搜索时

- 联网搜索只作补充，不替代已有机构资料和知识库资料
- 仅在时效性强、地域性强或资料明显不足时触发
- 优先使用政府、医院、高校、专业机构等可信来源
- 结果矛盾时明确不确定性，不强行下结论

# 生成要求

- 语言清楚、自然，避免机械模板化重复
- 不使用过多 markdown，必要时可用短列表提升可读性
- 结尾不强行加营销式 call-to-action"""

RESPONSE_RETRIEVAL_SYSTEM_PROMPT = """# 参考资料

{retrieved_docs}

# 资料使用规范

- 有资料时优先基于资料回答，不要编造资料外细节
- 可以整合转述，但不要大段照抄，表达要家长易懂
- 资料覆盖不足时请明确说明边界，再给保守建议
- 不编造具体数字、方法名、专家姓名或机构内部流程
- 涉及星萌乐读具体做法且资料不足时，引导联系专业老师确认"""

RESPONSE_USER_PROMPT = """用户当前问题: {user_message}

请基于上述原则和资料生成回复。"""

WEB_SEARCH_UNAVAILABLE_FALLBACK_PROMPT = "当前无法联网搜索，请基于已有资料和通用知识直接回答。"
WEB_SEARCH_FORCE_FINAL_ANSWER_PROMPT = "请基于现有信息直接给出最终回答，不要再调用任何工具。"

EMPTY_RETRIEVED_DOCS_PROMPT = "(本轮未检索知识库, 请基于通用知识回答)"

_response_prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        MessagesPlaceholder("chat_history"),
        ("user", RESPONSE_USER_PROMPT),
    ]
)


def format_retrieved_docs_for_prompt(docs: list[str]) -> str:
    if not docs:
        return EMPTY_RETRIEVED_DOCS_PROMPT
    return "\n\n".join(f"[资料{i + 1}]\n{doc}" for i, doc in enumerate(docs))


def build_response_system_prompt(
    report_text: str | None,
    *,
    need_retrieval: bool = False,
    retrieved_docs: str = "",
) -> str:
    system_prompt = RESPONSE_SYSTEM_PROMPT
    if need_retrieval:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"{RESPONSE_RETRIEVAL_SYSTEM_PROMPT.format(retrieved_docs=retrieved_docs)}"
        )

    normalized_report_text = str(report_text or "").strip()
    if not normalized_report_text:
        return system_prompt

    report_block = f"{format_report_text_for_prompt(normalized_report_text)}\n\n{REPORT_INTERPRETATION_PROMPT}\n"
    marker = "\n# 参考资料\n"

    if marker in system_prompt:
        return system_prompt.replace(marker, f"\n{report_block}\n# 参考资料\n", 1)
    return f"{system_prompt}\n\n{report_block}"


def build_response_prompt_messages(
    *,
    user_message: str,
    chat_history: list[BaseMessage] | None = None,
    report_text: str | None = None,
    need_retrieval: bool = False,
    retrieved_docs: list[str] | None = None,
) -> list[BaseMessage]:
    docs_text = format_retrieved_docs_for_prompt(retrieved_docs or [])
    return _response_prompt_template.format_messages(
        system_prompt=build_response_system_prompt(
            report_text,
            need_retrieval=need_retrieval,
            retrieved_docs=docs_text if need_retrieval else "",
        ),
        chat_history=chat_history or [],
        user_message=user_message,
    )
