"""Offline planning calculator, not a billing implementation or a forecast."""
import argparse
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    return json.loads(Path(path or ROOT / "planning/assumptions.json").read_text())


def video_seconds(shots, attempts, block=5):
    if attempts < 1 or block <= 0 or any(s <= 0 for s in shots):
        raise ValueError("Positive shot duration/block and at least one attempt required")
    return sum(math.ceil(s / block) * block for s in shots) * attempts


def tts_cost(chars, requests, rate):
    # Conservative upper bound for per-request minimum/rounding, not exact billing.
    if chars < 0 or requests < 0 or rate < 0 or (chars > 0 and requests == 0):
        raise ValueError("Invalid TTS usage")
    if chars == 0:
        return 0.0
    return (math.ceil(chars / 50) + requests - 1) * rate


def provider_cost(c, video, lip, images, chars, requests, input_tokens, output_tokens):
    costs = {
        "video": video * c["video_usd_per_second"],
        "lipsync": lip * c["lipsync_fps"] * c["lipsync_usd_per_frame"],
        "images": images * c["image_usd_each"],
        "voice": tts_cost(chars, requests, c["tts_usd_per_50_characters"]),
        "story": (input_tokens * c["llm_input_usd_per_million"]
                  + output_tokens * c["llm_output_usd_per_million"]) / 1_000_000,
    }
    jpy = {k: v * c["usd_jpy"] for k, v in costs.items()}
    jpy["provider_reserve"] = sum(jpy.values()) * c["provider_overhead_rate"]
    return jpy


def plan_cost(c, name, utilization=1):
    if not 0 <= utilization <= 1:
        raise ValueError("Utilization must be between zero and one")
    p = c["plans"][name]
    cost = provider_cost(c, p["video_seconds"], p["lipsync_seconds"], p["images"],
                         p["tts_characters"], p["tts_requests"],
                         p["llm_input_tokens"], p["llm_output_tokens"])
    cost = {k: v * utilization for k, v in cost.items()}
    gross = p["price_gross"]
    net = gross / (1 + c["tax_rate"])
    # Top-ups conservatively include Billing charge too; not an exact invoice.
    cost["payments"] = gross * (c["payment_rate"] + c["billing_rate"])
    cost["refund_reserve"] = net * c["refund_reserve_rate_net_revenue"]
    for k in ("storage_delivery_jpy", "render_jpy", "support_jpy"):
        cost[k] = p[k]
    total = sum(cost.values())
    return {"gross": gross, "net": net, "cost": total, "contribution": net-total,
            "margin": (net-total)/net, "breakdown": cost}


def work_cost(c, attempts):
    w = c["work"]
    seconds = video_seconds(w["shot_seconds"], attempts, c["video_billing_block_seconds"])
    costs = provider_cost(c, seconds, w["lipsync_seconds_per_attempt"] * attempts,
                          w["images"], w["spoken_characters_per_attempt"] * attempts,
                          w["spoken_requests_per_attempt"] * attempts,
                          w["llm_input_tokens"], w["llm_output_tokens"])
    costs["render_delivery"] = w["render_jpy"] + w["delivery_jpy"]
    return {"seconds": seconds, "total": sum(costs.values()), "breakdown": costs}


def fixed_cost(c, stage):
    f = c["fixed_costs"][stage]
    return (f["technology"] + f["labor"] + f["acquisition"] + f["other"]
            + f["free_activations"] * c["free_activation_cost_jpy"])


def required_users(c, annual_revenue, name="creator"):
    return math.ceil(annual_revenue / (plan_cost(c, name)["net"] * 12))


def report(c):
    lines = ["# 費用モデルの計算結果", "", f"基準日 {c['as_of']}。全て予算・仮説。実測ではない。",
             f"`assumptions.json` から自動生成。JPY/USD={c['usd_jpy']}は計画レート。料金は税込、売上は税抜。",
             "生成量を100%消化して計算。再生成は枠内消費であり、枠に再生成倍率を再乗算しない。", "",
             "## 月額プラン・追加枠", "", "| 区分 | 税込価格 | 税抜売上 | 変動費 | 限界利益 | 限界利益率 |",
             "|---|---:|---:|---:|---:|---:|"]
    for name in c["plans"]:
        p = plan_cost(c, name)
        lines.append(f"| {name} | {p['gross']:,.0f}円 | {p['net']:,.0f}円 | {p['cost']:,.0f}円 | {p['contribution']:,.0f}円 | {p['margin']:.1%} |")
    lines += ["", "## Creator 内訳（1人・1か月）", "", "| 項目 | 金額 |", "|---|---:|"]
    for k, v in plan_cost(c, "creator")["breakdown"].items():
        lines.append(f"| {k} | {v:,.1f}円 |")
    lines += ["", "## 30秒作品の制作原価", "", "6カット各5秒、画像18枚、各試行で発話150字・6呼出・口同期10秒。",
              "完成までの各カット平均試行数を変化。脚本・画像18枚は固定し、動画・音声・口同期を再試行。決済・月額固定費は含まない。", "",
              "| 平均試行数（初回含む） | 課金対象動画秒 | 制作原価 |", "|---|---:|---:|"]
    for a in (1, 2, 4):
        w = work_cost(c, a)
        lines.append(f"| {a} | {w['seconds']}秒 | {w['total']:,.0f}円 |")
    lines += ["", "## Creator 全枠消化の感度分析", "", "| 為替 | 動画USD/秒 | 変動費 | 限界利益率 |", "|---:|---:|---:|---:|"]
    for fx in (140, 160, 180):
        for rate in (0.05, 0.12):
            scenario = copy.deepcopy(c)
            scenario.update(usd_jpy=fx, video_usd_per_second=rate)
            p = plan_cost(scenario, "creator")
            lines.append(f"| {fx} | {rate:.2f} | {p['cost']:,.0f}円 | {p['margin']:.1%} |")
    lines += ["", "## 利用者規模と月次営業収支の予算例", "", "全員Creator、全枠消化。100人まではpilot、500人以上はgrowth体制を仮置き。",
              "体制変更は利用者数で自動決定するルールではない。獲得費は新規・補充の双方を含む。", "",
              "| 有料人数 | 税抜売上 | 変動費 | 固定費等 | 税引前収支 |", "|---:|---:|---:|---:|---:|"]
    p = plan_cost(c, "creator")
    for n in (20, 100, 500, 1000, 2000):
        f = fixed_cost(c, "pilot" if n <= 100 else "growth")
        lines.append(f"| {n:,} | {p['net']*n:,.0f}円 | {p['cost']*n:,.0f}円 | {f:,.0f}円 | {p['contribution']*n-f:,.0f}円 |")
    lines += ["", "## 売上目標", ""]
    for target in (100_000_000, 120_000_000):
        lines.append(f"- 年商{target:,}円に必要な年間平均Creator人数：{required_users(c, target):,}人。")
    lines.append(f"- growth固定費等での損益分岐：{math.ceil(fixed_cost(c, 'growth')/p['contribution']):,}人。")
    lines += ["", "現金収支・法人税・決済入金の時間差・外注前払・APIクレジット前払を別途管理する。",
              "正確な会計処理ではない。手数料の税、請求書ごとの丸め、個別契約費用は見積時に置換する。", ""]
    studio = c.get("studio")
    if studio:
        comic = provider_cost(c, 0, 0, studio["comic_panels"] + studio["comic_reference_images"], 0, 0,
                              c["work"]["llm_input_tokens"], c["work"]["llm_output_tokens"])
        lines += ["", "## v2 漫画・アニメ（仮説）", "",
                  f"漫画4コマ+人物参照2枚のAPI等予算: {sum(comic.values()) + studio['comic_render_delivery_jpy']:.1f}円。再生成なし。",
                  "アニメは上記30秒試算を参照。モデル品質・再生成率・固定契約費は未測定。",
                  f"ローカルデモ: 漫画4コマ {studio_quote('comic',4,c)['credits']}cr / アニメ6場面 {studio_quote('anime',6,c)['credits']}cr。",
                  "デモcrは販売価格・円換算ではない。外部API実費は0円。旧月額プランと二重に販売しない。", ""]
    if "gemini" in c:
        g = c["gemini"]
        lines += ["", "## Gemini実APIの検証安全枠", "",
                  f"テキスト {g['text_model']} / 画像 {g['image_model']}。計画為替{g['usd_jpy_planning']}円/USD。",
                  f"会話1回{g['text_request_cap_jpy']}円、画像1枚{g['image_request_cap_jpy']}円を呼出前に予約。累計上限{g['budget_jpy']}円。",
                  f"成功時はusageMetadata推定費用×{g['safety_multiplier']}を枠から消費し、未使用予約を解放。不明/失敗は予約を保持。",
                  "推定は請求確定額ではない。画像出力の全トークンを画像単価で保守的に計上。実測はevaluation/gemini-results.json。", ""]
    lines += membership_report(c)
    return "\n".join(lines)


def gemini_usage_estimate(kind, usage, config=None):
    c = (config or load_config())["gemini"]
    output = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    return (usage.get("promptTokenCount", 0) * c[kind+"_input_usd_million"] + output*c[kind+"_output_usd_million"])/1_000_000*c["usd_jpy_planning"]


def studio_quote(mode, count, config=None):
    c = (config or load_config())["studio"]
    if mode not in ("comic", "anime") or type(count) is not int or count < 1:
        raise ValueError("Invalid mode or count")
    limit = c["comic_panels"] if mode == "comic" else c["anime_shots"]
    if count > limit:
        raise ValueError("Too many scenes")
    return {"credits": count * c["comic_credits_per_panel" if mode == "comic" else "anime_credits_per_shot"],
            "images": count, "video_seconds": count * c["shot_seconds"] if mode == "anime" else 0,
            "external_api_cost_jpy": 0, "kind": "local_demo"}


def membership_report(config):
    m=config.get('membership')
    if not m:return []
    lines=['','## Free / Plus / Pro（仮説、販売前の利用枠）','',
           '| プラン | 税込価格 | 内部USD停止枠/月 | 漫画保存数 |',
           '|---|---:|---:|---:|']
    e=m['economics']
    for name in ['free','plus','pro']:
        p=m[name]
        lines.append(f"| {p['label']} | {p['price_gross']:,}円 | ${p['monthly_budget_usd']} | {p['projects']} |")
    lines+=['','会話・画像を単価でUSD換算し、共通月間枠で停止。ユーザーには%のみ表示。旧回数・トークン上限は適用しない。画像は三面図と再生成を含む。広告は提供せず、Freeは本人のAPIキーを使い運営の生成枠を付与しない。以下は固定費・税務を確定するものではない。','']
    for name in ['plus','pro']:
        p=m[name];net=p['price_gross']/(1+config['tax_rate']);fees=p['price_gross']*(config['payment_rate']+config['billing_rate'])
        margin=net-fees-p['monthly_budget_usd']*config['gemini']['usd_jpy_planning']-e['support_storage_jpy'][name]
        lines.append(f"- {p['label']}: API停止枠まで消費した場合の固定費前利益 {margin:.0f}円/人（既存の決済料仮説と保管・サポート仮説を控除）。")
    cost=m['free']['monthly_budget_usd']*config['gemini']['usd_jpy_planning']+e['support_storage_jpy']['free']
    lines+=['',f'Freeの運営負担の月間保管・サポート仮説原価 {cost:.2f}円/人。生成API料金は本人がGoogleへ負担する。広告収入は前提にしない。','',
            'Freeの生成枠付与は0。保存数は1件を維持し、API利用料は運営原価に含めない。','']
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = report(load_config(args.config))
    if args.write:
        path = ROOT / "planning/cost-summary.md"
        path.write_text(result)
        print(path)
    else:
        print(result)


if __name__ == "__main__":
    main()
