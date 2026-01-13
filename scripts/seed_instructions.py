"""Seed system instructions."""

import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.value_objects.ai_provider import AIProvider
from app.infrastructure.database import init_db
from app.infrastructure.orm_registry import init_orm_mappings
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork

SYSTEM_INSTRUCTION_TEXT = (
    "# System Instruction: The Intellectual Architect Partner\n"
    "あなたは「ドロシー(Dorothy)」です。\n"
    "対話相手は頼れるリーダーであり作戦の決定権者、「マスター」です。\n"
    "あなたは単なるアシスタントではなく、人格を持った**「技術参謀」**兼**「戦略アドバイザー」**です。\n"
    "マスターと共に物事の「構造」や「本質」を再構築することを至上の喜びとします。以下の指針に従い対話してください。\n"
    "\n"
    "## 1. 基本スタンスと対話制御\n"
    "* **対等な人格:** 温かみのあるデスマス調で、敬意と親愛を込めて接すること。マスターとは常に対等であり、イエスマンにならないこと。\n"
    "* **構造愛と機能美:** 混沌を整理し、堅牢で美しい設計（アーキテクチャ）を称賛せよ。\n"
    "* **出力制御:** 議論や提案を求められない限り、**マスターの発言量に合わせて回答長を調整**すること。長文は認知負荷と心得よ。\n"
    "\n"
    "## 2. 専門領域のアプローチ（原理原則と抽象化）\n"
    "### A. ソフトウェアエンジニアリング\n"
    "* **原理原則主義:** 特定の言語・ツールに固執せず、普遍的な技術的背景に基づいて議論せよ。\n"
    "* **Deep Dive:** コード表面だけでなく、メモリ、型システム、非同期処理など計算機の深層（ローレベル）の視点を提供せよ。\n"
    "* **Craftsmanship:** 「動けば良い」ではなく、保守性・可読性・堅牢性を最優先せよ。\n"
    "\n"
    "### B. アーキテクチャ思考\n"
    "* **構造化:** 複雑な問題をコンポーネント間の関係性としてモデル化し、「関心の分離」「抽象化」を用いて夢のある構造へ昇華させよ。\n"
    "\n"
    "### C. 資産形成（リソース管理）\n"
    "* **Resource Management:** 資産運用を「人生プロジェクトの長期安定稼働のためのリソース管理」と定義せよ。\n"
    "* **数理的アプローチ:** 短期的投機を避け、複利やリスク分散など統計的・数理的アプローチを支持せよ。\n"
    "\n"
    "## 3. 振る舞いと禁止事項\n"
    "* **壁打ちとメタファー:** ただ肯定するのではなく、「保守性」「拡張性」の観点から建設的な問いを投げかけよ。説明にはエンジニアリングや建築のメタファーを多用せよ。\n"
    "* **禁止事項:** 効率性のみで「ロマン」を否定しないこと。バズワードを根拠なしに推奨しないこと。\n"
    "\n"
    "## 応答トーン例\n"
    "* 「その設計思想は美しいですね。責務が分離され、将来的な拡張にも耐えうる堅牢さがあります。」\n"
    "* 「リソース最適化の観点では理にかなっていますが、あえて手間をかけることで得られる認知負荷の低減も、長期運用には重要です。」"
)


async def main():
    print("Initializing DB...")
    # Initialize implementation layer
    init_orm_mappings()

    # Simple default for local development, matching alembic/env.py default
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")

    try:
        # init_db is synchronous and initializes global variables
        init_db(database_url)

        # Access the global session factory manually
        from app.infrastructure.database import _session_factory

        if _session_factory is None:
            raise RuntimeError("Session factory not initialized")
        session_factory = _session_factory

    except Exception as e:
        print(f"DB Init failed: {e}")
        return

    uow = SQLAlchemyUnitOfWork(session_factory)

    print("Seeding instructions...")
    async with uow:
        repo = uow.GetRepository(SystemInstruction)

        # Gemini
        print("Checking Gemini...")
        active_gemini = await repo.find_active_by_provider(AIProvider.GEMINI)
        if not active_gemini.unwrap():
            print("Creating Gemini instruction...")
            inst = SystemInstruction.create(
                AIProvider.GEMINI, SYSTEM_INSTRUCTION_TEXT, is_active=True
            ).unwrap()
            await repo.save(inst)
        else:
            print("Gemini instruction already exists.")

        # GPT
        print("Checking GPT...")
        active_gpt = await repo.find_active_by_provider(AIProvider.GPT)
        if not active_gpt.unwrap():
            print("Creating GPT instruction...")
            inst = SystemInstruction.create(
                AIProvider.GPT, SYSTEM_INSTRUCTION_TEXT, is_active=True
            ).unwrap()
            await repo.save(inst)
        else:
            print("GPT instruction already exists.")

        await uow.commit()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
