"""
Measures retrieval quality: dense-only vs hybrid, on YOUR papers and YOUR questions.

1. Upload papers into a workspace through the app, note the workspace id.
2. Write eval/questions.jsonl, one JSON object per line:
     {"question": "Which dataset was used for training?", "expect": ["ImageNet", "1.2 million"]}
   `expect` = any of these substrings must appear in a correct chunk (case-insensitive).
3. Run (from backend/, with DATABASE_URL and GEMINI_API_KEY set):
     python -m eval.retrieval_eval <workspace_id> eval/questions.jsonl

Reports hit@k (is a correct chunk in the top k?) and MRR for both modes. ~30 questions is enough to
see a real difference; keep the numbers for your README / resume.
"""
from __future__ import annotations
import json
import sys

from app.services import indexing, storage


def evaluate(workspace_id: str, path: str, ks=(1, 3, 5, 8)) -> dict:
    paper_ids = [p.paper_id for p in storage.list_papers(workspace_id) if p.status == "indexed"]
    if not paper_ids:
        raise SystemExit("No indexed papers in that workspace.")
    questions = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    results = {}
    for mode, hybrid in (("dense", False), ("hybrid", True)):
        hits = {k: 0 for k in ks}
        rr_total = 0.0
        for q in questions:
            expect = [e.lower() for e in q["expect"]]
            ranked = indexing.search_chunks(q["question"], paper_ids, top_k=max(ks), hybrid=hybrid)
            rank = next((i for i, c in enumerate(ranked, 1) if any(e in c["text"].lower() for e in expect)), None)
            if rank:
                rr_total += 1.0 / rank
                for k in ks:
                    hits[k] += rank <= k
        n = len(questions)
        results[mode] = {**{f"hit@{k}": round(hits[k] / n, 3) for k in ks}, "MRR": round(rr_total / n, 3), "n": n}
    return results


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    out = evaluate(sys.argv[1], sys.argv[2])
    for mode, row in out.items():
        print(f"{mode:7s}", "  ".join(f"{k}={v}" for k, v in row.items()))
