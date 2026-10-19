"""Minimal Discord gateway intents required by the current bot features.

必要な権限（最小権限方針）
------------------------

Gateway Intents（Developer Portal 側の設定と合わせて有効化するもの）:

- ``guilds``: ギルド（サーバー）メタデータ。プレフィックス／ハイブリッド
  コマンドのコンテキスト取得に必要。
- ``guild_messages``: ギルド内メッセージイベント。``!`` プレフィックス
  コマンドの受信に必要。
- ``dm_messages``: DM メッセージイベント。DM 履歴の永続化に必要。
- ``message_content``: **特権 Intent（Message Content Intent）**。
  ``!`` コマンドの引数解析と DM メッセージ本文の保存のため、
  Developer Portal で明示的に有効化する必要がある。

有効化しない Intent（現行機能で不要）: メンバー一覧（members）、
プレゼンス（presences）、タイピング、音声、リアクション、BAN、招待、
Webhook、統合、自動モデレーション等。

Discord サーバー（ギルド）側の最小権限: チャンネルの閲覧（View Channels）
とメッセージ送信（Send Messages）のみ。Administrator / Manage Roles /
Manage Server は不要。なお、ドメイン層の「チームロール」はアプリ内データ
であり、Discord のサーバーロール操作とは無関係。
"""

import discord

__all__ = ["create_bot_intents"]


def create_bot_intents() -> discord.Intents:
    """Return the minimal intent set needed by the current Cogs/listeners.

    Returns:
        discord.Intents: ``guilds`` / ``guild_messages`` / ``dm_messages`` /
        ``message_content`` のみを有効化した Intents。
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.dm_messages = True
    # 特権 Intent: プレフィックスコマンド解析と DM 本文保存に必須。
    intents.message_content = True
    return intents
