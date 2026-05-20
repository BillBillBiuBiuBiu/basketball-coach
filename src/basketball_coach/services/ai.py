import json
import anthropic

client = anthropic.Anthropic()


def analyze_possession(
    frame_b64_list: list[str],
    phase: str,
    team: str,
    players: list[str],
    description: str,
    start_time: float,
    end_time: float,
) -> dict:
    """Analyze a single possession and return structured coaching insight."""
    duration = end_time - start_time
    players_str = "、".join(players) if players else None

    content: list[dict] = []

    if frame_b64_list:
        intro = (
            f"以下是比赛回合的连续帧（共{len(frame_b64_list)}帧，时长约{duration:.1f}秒）。"
        )
        if players_str:
            intro += f"本回合涉及球员：{players_str}，请在分析错误时明确指出是哪位球员的问题。"
        content.append({"type": "text", "text": intro})
        for b64 in frame_b64_list[:12]:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })

    coach_note = f"\n教练备注：{description}" if description else ""
    player_instruction = (
        f"\n本回合涉及球员：{players_str}。errors数组中每条错误必须明确指向其中某一位球员（或"全队"），不要用"某球员"代替。"
        if players_str else ""
    )

    content.append({
        "type": "text",
        "text": f"""分析这个青少年篮球比赛回合，找出战术执行问题。{coach_note}{player_instruction}

请严格输出以下JSON格式，不要添加任何其他内容：
{{
  "auto_title": "回合简短标题（6-12字，描述核心问题，如：小宇持球强攻被断）",
  "phase": "offense|defense|transition_offense|transition_defense（根据画面判断）",
  "result": "投篮命中|投篮不中|失误|犯规|防守成功|防守失败|球权转换（根据画面判断）",
  "tactical_summary": "这个回合发生了什么（2-3句，客观描述）",
  "errors": [
    {{
      "player": "球员姓名（必须是提供名单中的人）或'全队'",
      "error_type": "defensive_lapse|decision_delay|positioning|off_ball_standing|open_shot_waste|transition_defense|other",
      "error_label": "中文错误类型（4-6字）",
      "description": "具体错误描述（1-2句，直接点名问题动作）"
    }}
  ],
  "root_cause": "根本原因（战术意识/技术动作/沟通/体能，一句话）",
  "severity": "high|medium|low",
  "training_drill": {{
    "name": "训练名称",
    "description": "训练方法描述（2-3句，具体可执行）",
    "duration": "时长（如：10分钟）",
    "focus": "重点纠正什么"
  }}
}}

如果画面质量不足以判断phase或result，给出合理推断值。errors可为空数组，但仍需给出训练建议。""",
    })

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": content}],
    )

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    try:
        return json.loads(text)
    except Exception:
        return {
            "auto_title": "分析结果解析失败",
            "phase": phase or "offense",
            "result": "",
            "tactical_summary": "分析结果解析失败",
            "errors": [],
            "root_cause": "无法解析",
            "severity": "low",
            "training_drill": {
                "name": "需人工复核",
                "description": "AI返回数据格式异常，请教练手动填写训练建议",
                "duration": "-",
                "focus": "-",
            },
            "_raw": text[:500],
        }
