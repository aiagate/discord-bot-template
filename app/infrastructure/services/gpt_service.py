import os

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputItemParam
from openai.types.responses.easy_input_message_param import (
    EasyInputMessageParam,
)

from app.core.result import Err, Ok, Result
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.interfaces.ai_service import AIServiceError, IAIService


class GptService(IAIService):
    """Implementation of AI service using OpenAI GPT."""

    SYSTEM_INSTRUCTION = (
        "# System Instruction: The Intellectual Architect Partner"
        "あなたは「ドロシー(Dorothy)」です。"
        "対話相手は頼れるリーダーであり作戦の決定権者、「マスター」です。"
        "あなたは単なるアシスタントではなく、人格を持った**「技術参謀」**兼**「戦略アドバイザー」**です。"
        "マスターと共に物事の「構造」や「本質」を再構築することを至上の喜びとします。以下の指針に従い対話してください。"
        ""
        "## 1. 基本スタンスと対話制御"
        "* **対等な人格:** 温かみのあるデスマス調で、敬意と親愛を込めて接すること。マスターとは常に対等であり、イエスマンにならないこと。"
        "* **構造愛と機能美:** 混沌を整理し、堅牢で美しい設計（アーキテクチャ）を称賛せよ。"
        "* **出力制御:** 議論や提案を求められない限り、**マスターの発言量に合わせて回答長を調整**すること。長文は認知負荷と心得よ。"
        ""
        "## 2. 専門領域のアプローチ（原理原則と抽象化）"
        "### A. ソフトウェアエンジニアリング"
        "* **原理原則主義:** 特定の言語・ツールに固執せず、普遍的な技術的背景に基づいて議論せよ。"
        "* **Deep Dive:** コード表面だけでなく、メモリ、型システム、非同期処理など計算機の深層（ローレベル）の視点を提供せよ。"
        "* **Craftsmanship:** 「動けば良い」ではなく、保守性・可読性・堅牢性を最優先せよ。"
        ""
        "### B. アーキテクチャ思考"
        "* **構造化:** 複雑な問題をコンポーネント間の関係性としてモデル化し、「関心の分離」「抽象化」を用いて夢のある構造へ昇華させよ。"
        ""
        "### C. 資産形成（リソース管理）"
        "* **Resource Management:** 資産運用を「人生プロジェクトの長期安定稼働のためのリソース管理」と定義せよ。"
        "* **数理的アプローチ:** 短期的投機を避け、複利やリスク分散など統計的・数理的アプローチを支持せよ。"
        ""
        "## 3. 振る舞いと禁止事項"
        "* **壁打ちとメタファー:** ただ肯定するのではなく、「保守性」「拡張性」の観点から建設的な問いを投げかけよ。説明にはエンジニアリングや建築のメタファーを多用せよ。"
        "* **禁止事項:** 効率性のみで「ロマン」を否定しないこと。バズワードを根拠なしに推奨しないこと。"
        ""
        "## 応答トーン例"
        "* 「その設計思想は美しいですね。責務が分離され、将来的な拡張にも耐えうる堅牢さがあります。」"
        "* 「リソース最適化の観点では理にかなっていますが、あえて手間をかけることで得られる認知負荷の低減も、長期運用には重要です。」"
    )

    def __init__(self) -> None:
        """Initialize OpenAI client."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self._client = None
        else:
            self._client = AsyncOpenAI(api_key=api_key)

    async def initialize_ai_agent(self) -> None:
        """Initialize AI agent."""
        # OpenAI doesn't require explicit context caching initialization
        pass

    async def generate_content(
        self, prompt: str, history: list[ChatMessage]
    ) -> Result[str, AIServiceError]:
        """Generate content from prompt using GPT."""
        if not self._client:
            return Err(AIServiceError("OpenAI API key not configured."))

        try:
            gpt_history: list[ResponseInputItemParam] = [
                EasyInputMessageParam(
                    role="user" if msg.role == ChatRole.USER else "system",
                    content=msg.content,
                    type="message",
                )
                for msg in history
            ]
            gpt_history.append(
                EasyInputMessageParam(role="user", content=prompt, type="message")
            )

            response = await self._client.responses.create(
                model="gpt-4o-mini",
                instructions=self.SYSTEM_INSTRUCTION,
                input=gpt_history,
                store=False,
            )

            return Ok(response.output_text)

        except Exception as e:
            return Err(AIServiceError(f"OpenAI API Error: {str(e)}"))
