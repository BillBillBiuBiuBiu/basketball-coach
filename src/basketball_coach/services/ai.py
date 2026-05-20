import json
import anthropic

client = anthropic.Anthropic()

PHASE_LABELS = {
    "offense": "半场进攻",
    "defense": "半场防守",
    "transition_offense": "快攻/转换进攻",
    "transition_defense": "退防/转换防守",
}


def analyze_possession(
    frame_b64_list: list[str],
    title: str,
    phase: str,
    team: str,
    players: list[str],
    description: str,
    start_time: float,
    end_time: float,
) -> dict:
    """Analyze a single possession (round) and return structured coaching insight."""
    duration = end_time - start_time
    phase_label = PHASE_LABELS.get(phase, phase)
    players_str = "、".join(players) if players else "未标注"

    content: list[dict] = []

    if frame_b64_list:
        content.append({
            "type": "text",
            "text": (
                f"以下是比赛回合的连续帧（共{len(frame_b64_list)}帧，"
                f"时长约{duration:.1f}秒）。"
                f"回合类型：{phase_label}，执行方：{team}，"
                f"相关球员：{players_str}。"
            ),
        })
        for b64 in frame_b64_list[:12]:  # max 12 frames per possession
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
    
    coach_note = f"\n教练备注：{description}" if description else ""
    content.append({
        "type": "text",
        "text": f"""分析这个篮球比赛回合中的战术执行问题。{coach_note}

请严格输出以下JSON格式，不要添加任何其他内容：
{{
  "tactical_summary": "这个回合发生了什么（2-3句，客观描述）",
  "errors": [
    {{
      "player": "球员姓名或'全队'",
      "error_type": "defensive_lapse|decision_delay|positioning|off_ball_standing|open_shot_waste|transition_defense|other",
      "error_label": "中文错误类型（4-6字）",
      "description": "具体错误描述（1-2句，直接指出问题）"
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

如果画面质量不足以判断，errors数组可为空，但仍需根据回合类型和教练备注给出训练建议。""",
    })

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
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
