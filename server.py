"""可选的线上服务：托管 viewer 前端 + 提供 /api/summarize 大模型总结。

    python server.py [--port 8787] [--host 0.0.0.0]

- 请求 /            → viewer/index.html（单文件，客户端可离线渲染）
- GET /api/data     → viewer_data.json（近 30 天数据）
- POST /api/summarize → 对给定日期范围内的 AI 新闻做统一总结
      · 若配置 DIGEST_LLM_API_KEY，则调用 OpenAI 兼容接口生成模型叙事
      · 否则返回确定性聚合总结（保证任何环境可用）

默认端点 /api/summarize 与前端 SUMMARIZE_ENDPOINT 一致，发布后即自动接通。
"""  # noqa: E501
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerr
from urllib import request as urlreq

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(HERE, "viewer")
DATA = os.path.join(VIEWER, "viewer_data.json")


# --------------------------------------------------------------------------
# 大模型 / 确定性 总结
# --------------------------------------------------------------------------
def _load_data():
    if os.path.exists(DATA):
        with open(DATA, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"days": []}


def _deterministic(payload):
    items = list(payload.get("items", []))
    start, end, days = payload.get("start", ""), payload.get("end", ""), payload.get("days", 0)
    if not items:
        return f"范围 {start} → {end} 内暂无通过审核的情报。"
    cats = {}
    for i in items:
        cats[i.get("category", "行业动态")] = cats.get(i.get("category", "行业动态"), 0) + 1
    cat_str = "、".join(f"{k}({v})" for k, v in sorted(cats.items(), key=lambda x: -x[1])[:3])
    top = items[0]
    top_title = top.get("title", ""), top.get("source", ""), top.get("date", "")
    return (
        f"在 {days} 天共 {len(items)} 条通过 5 道质量审核门的 AI 情报里，行业重心集中在：{cat_str}。"
        f"其中重要度最高一条为「{top_title[0]}」（{top_title[1]}，{top_title[2]}）。"
        "总体看，模型与开源仍是热议主线，算力供应链与 Agent 应用是重要第二曲线，"
        "融资与治理话题维持稳定关注度。建议结合原文链接进一步核实。"
    )


def _llm(payload):
    api_key = os.environ.get("DIGEST_LLM_API_KEY", "")
    base = os.environ.get("DIGEST_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("DIGEST_LLM_MODEL", "gpt-4o-mini")
    if not api_key:
        return None
    items = payload.get("items", [])
    context = "\n".join(
        f"- [{i.get('date')}][{i.get('source')}][{i.get('category')}] {i.get('title')}" for i in items[:20]
    )
    system = "你是资深 AI 行业分析师，请对给定日期范围的 AI 新闻做简洁、有洞察的统一总结，不超过250字。"
    user = f"日期范围：{payload.get('start')} → {payload.get('end')}（{payload.get('days')} 天）。新闻如下：\n{context}"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
    }).encode("utf-8")
    req = urlreq.Request(f"{base}/chat/completions", data=body, method="POST",
                         headers={"Content-Type": "application/json",
                                  "Authorization": f"Bearer {api_key}"})
    try:
        with urlreq.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return None


def generate_summary(payload) -> str:
    text = _llm(payload)
    return text or _deterministic(payload)


# --------------------------------------------------------------------------
# HTTP 处理
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默日志
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/data":
            if os.path.exists(DATA):
                return self._send(200, open(DATA, encoding="utf-8").read())
            return self._send(404, '{"error":"no data"}')
        rel = "/index.html" if path in ("", "/") else path
        fp = os.path.normpath(os.path.join(VIEWER, rel.lstrip("/")))
        if fp.startswith(VIEWER) and os.path.isfile(fp):
            if fp.endswith(".html"):
                return self._send(200, open(fp, encoding="utf-8").read(), "text/html; charset=utf-8")
            if fp.endswith(".json"):
                return self._send(200, open(fp, encoding="utf-8").read(), "application/json; charset=utf-8")
            return self._send(200, open(fp, "rb").read(), "application/octet-stream")
        return self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path.split("?")[0] == "/api/summarize":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:  # noqa: BLE001
                body = {}
            summary = generate_summary(body)
            return self._send(200, json.dumps({"summary": summary}, ensure_ascii=False))
        return self._send(404, '{"error":"unknown"}')


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 智讯日报 viewer server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI 智讯日报 viewer 运行于 http://{args.host}:{args.port}/  (Ctrl+C 停止)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
